from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.database import Database
from app.features import FeatureService
from app.llm import Extractor, LLMError, OpenAICompatibleExtractor
from app.loader import load_reports
from app.model_manager import ModelConfigError, ModelManager
from app.schemas import (
    ChatRequest, ChatResponse, ErrorBody, ErrorResponse,
    ModelProfileCreate, ModelProfileUpdate, SuggestionsRequest,
)
from app.service import ChatService, ReportActionError, SessionUserError, UnknownSessionError


LOGGER = logging.getLogger("due_diligence_assistant")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", f"req_{uuid.uuid4().hex}")


def _error(request: Request, status: int, code: str, message: str, retryable: bool) -> JSONResponse:
    body = ErrorResponse(
        request_id=_request_id(request),
        error=ErrorBody(code=code, message=message, retryable=retryable),
    )
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(settings: Settings | None = None, extractor: Extractor | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    model_manager = ModelManager(settings, database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.data_loaded = False
        app.state.load_error = None
        reports = load_reports(settings.data_dir)
        report_count, tag_count = database.rebuild(reports)
        model_manager.initialize()
        app.state.report_count = report_count
        app.state.tag_count = tag_count
        app.state.data_loaded = True
        LOGGER.info("startup_data_loaded reports=%s tags=%s", report_count, tag_count)
        yield

    app = FastAPI(
        title="尽调报告智能推荐服务",
        version="1.0.0",
        description="根据多轮会话提取客户及业务标签，推荐匹配的尽调报告。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.model_manager = model_manager
    app.state.feature_service = FeatureService(database, model_manager)
    app.state.chat_service = ChatService(
        database, extractor or model_manager, model_manager, app.state.feature_service,
        use_model_copy=extractor is None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        LOGGER.info(
            "request request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        return _error(request, 422, "INVALID_REQUEST", "请求参数校验失败", False)

    @app.exception_handler(UnknownSessionError)
    async def unknown_session(request: Request, exc: UnknownSessionError):
        return _error(request, 404, "SESSION_NOT_FOUND", str(exc), False)

    @app.exception_handler(SessionUserError)
    async def session_user_error(request: Request, exc: SessionUserError):
        return _error(request, 409 if "不属于" in str(exc) else 422, "SESSION_USER_ERROR", str(exc), False)

    @app.exception_handler(ReportActionError)
    async def report_action_error(request: Request, exc: ReportActionError):
        return _error(request, 404, "REPORT_NOT_FOUND", str(exc), False)

    @app.exception_handler(ModelConfigError)
    async def model_config_error(request: Request, exc: ModelConfigError):
        return _error(request, 400, "MODEL_CONFIG_ERROR", str(exc), False)

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, exc: LLMError):
        LOGGER.warning("llm_error request_id=%s type=%s", _request_id(request), type(exc).__name__)
        return _error(request, 503, "MODEL_UNAVAILABLE", str(exc), True)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error(request, exc.status_code, "NOT_FOUND", str(exc.detail), False)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        LOGGER.exception(
            "unexpected_error request_id=%s type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _error(request, 500, "INTERNAL_ERROR", "服务内部错误", True)

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        return await app.state.chat_service.chat(
            request_id=_request_id(request),
            requested_session=payload.session_id,
            message=payload.message,
            user_id=payload.user_id,
            action=payload.action.model_dump() if payload.action else None,
        )

    @app.get("/api/v1/ui/bootstrap")
    async def ui_bootstrap(user_id: str):
        return app.state.feature_service.bootstrap(user_id)

    @app.post("/api/v1/suggestions")
    async def suggestions(payload: SuggestionsRequest):
        return await app.state.feature_service.suggestions(
            payload.user_id, payload.session_id, payload.previous_batch_id
        )

    @app.get("/api/v1/users/{user_id}/conversations")
    async def user_conversations(user_id: str, limit: int = 20, cursor: str | None = None):
        return database.list_conversations(user_id=user_id, limit=limit, cursor=cursor)

    @app.get("/api/v1/conversations/{session_id}")
    async def conversation_detail(session_id: str):
        value = database.get_conversation(session_id)
        if not value: raise HTTPException(404, "会话不存在")
        return value

    @app.get("/api/v1/ops/conversations")
    async def ops_conversations(user_id: str | None = None, limit: int = 20,
                                cursor: str | None = None, feature: str | None = None,
                                keyword: str | None = None):
        return database.list_conversations(user_id, limit, cursor, feature, keyword)

    @app.get("/api/v1/ops/conversations/{session_id}")
    async def ops_conversation_detail(session_id: str):
        value = database.get_conversation(session_id)
        if not value: raise HTTPException(404, "会话不存在")
        return value

    @app.get("/api/v1/ops/metrics")
    async def ops_metrics():
        result = database.metrics()
        result["model"] = model_manager.status()
        result["recent_conversations"] = database.list_conversations(limit=5)["items"]
        return result

    @app.get("/api/v1/ops/model-status")
    async def model_status():
        return model_manager.status()

    @app.get("/api/v1/ops/model-profiles")
    async def model_profiles():
        return {"items": model_manager.list_profiles(), "master_key_configured": bool(settings.model_config_master_key)}

    @app.post("/api/v1/ops/model-profiles", status_code=201)
    async def create_model_profile(payload: ModelProfileCreate):
        return model_manager.create_profile(payload.model_dump())

    @app.patch("/api/v1/ops/model-profiles/{profile_id}")
    async def update_model_profile(profile_id: str, payload: ModelProfileUpdate):
        return model_manager.update_profile(profile_id, payload.model_dump(exclude_unset=True))

    @app.post("/api/v1/ops/model-profiles/{profile_id}/test")
    async def test_model_profile(profile_id: str):
        return await model_manager.test_profile(profile_id)

    @app.post("/api/v1/ops/model-profiles/{profile_id}/activate")
    async def activate_model_profile(profile_id: str):
        return await model_manager.activate(profile_id)

    @app.delete("/api/v1/ops/model-profiles/{profile_id}", status_code=204)
    async def delete_model_profile(profile_id: str):
        model_manager.delete(profile_id)

    @app.get("/api/v1/reports/{report_id}")
    async def report_detail(report_id: str):
        report = database.get_report(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="报告不存在")
        return report

    @app.get("/api/v1/health")
    async def health():
        data_loaded = bool(getattr(app.state, "data_loaded", False))
        report_count, tag_count = database.counts() if data_loaded else (0, 0)
        model_configured = model_manager.status()["configured"]
        return {
            "status": "ready" if data_loaded and model_configured else "degraded",
            "data_loaded": data_loaded,
            "database": "ok" if data_loaded else "unavailable",
            "model": "configured" if model_configured else "not_configured",
            "report_count": report_count,
            "tag_count": tag_count,
            "model_source": model_manager.status()["source"],
        }

    @app.api_route(
        "/api/{full_path:path}", methods=["GET", "POST", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def unknown_api(full_path: str):
        raise HTTPException(status_code=404, detail="接口不存在")

    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend_dist.is_dir():
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="接口不存在")
            candidate = (frontend_dist / full_path).resolve()
            if candidate.is_file() and frontend_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()
