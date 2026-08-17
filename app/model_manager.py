from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import replace
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.database import Database
from app.llm import LLMError, OpenAICompatibleExtractor
from app.schemas import ModelExtraction


class ModelConfigError(ValueError):
    pass


def _mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:3]}••••{value[-4:]}" if len(value) > 8 else "••••••••"


class ModelManager:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self._lock = asyncio.Lock()
        self._fernet = self._build_fernet(settings.model_config_master_key)
        self._source = "environment"
        self._profile_id: str | None = None
        self._profile_name = "环境变量配置"
        self._extractor = OpenAICompatibleExtractor(settings)

    @staticmethod
    def _build_fernet(key: str) -> Fernet | None:
        if not key:
            return None
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ModelConfigError("MODEL_CONFIG_MASTER_KEY 不是有效的 Fernet 密钥") from exc

    def initialize(self) -> None:
        if not self.settings.model_profile_from_database:
            return
        profile = self.database.active_model_profile()
        if profile:
            self._set_active_from_profile(profile)

    def _decrypt(self, encrypted: str | None) -> str:
        if not encrypted:
            return ""
        if not self._fernet:
            raise ModelConfigError("未配置 MODEL_CONFIG_MASTER_KEY，无法解密模型密钥")
        try:
            return self._fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ModelConfigError("模型密钥无法使用当前主密钥解密") from exc

    def _encrypt(self, secret: str) -> str | None:
        if not secret:
            return None
        if not self._fernet:
            raise ModelConfigError("未配置 MODEL_CONFIG_MASTER_KEY，不能保存模型密钥")
        return self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")

    def _settings_for(self, profile: dict[str, Any]) -> Settings:
        return replace(
            self.settings,
            llm_base_url=profile["base_url"], llm_model=profile["model"],
            llm_api_key=self._decrypt(profile.get("encrypted_api_key")),
            llm_timeout_seconds=float(profile["timeout_seconds"]),
            llm_json_mode=bool(profile["json_mode"]),
            llm_disable_thinking=bool(profile["disable_thinking"]),
        )

    def _set_active_from_profile(self, profile: dict[str, Any]) -> None:
        self._extractor = OpenAICompatibleExtractor(self._settings_for(profile))
        self._source, self._profile_id = "database", profile["profile_id"]
        self._profile_name = profile["name"]

    async def extract(self, history: list[dict[str, str]], message: str,
                      expected_tag: str | None = None) -> ModelExtraction:
        extractor = self._extractor
        return await extractor.extract(history, message, expected_tag)

    def status(self) -> dict[str, Any]:
        return {
            "source": self._source, "profile_id": self._profile_id,
            "profile_name": self._profile_name,
            "model": self._extractor.settings.llm_model,
            "configured": self._extractor.settings.llm_configured,
            "healthy": self._extractor.settings.llm_configured,
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        result = []
        for row in self.database.list_model_profiles():
            encrypted = row.pop("encrypted_api_key", None)
            try:
                masked = _mask_secret(self._decrypt(encrypted)) if encrypted else None
            except ModelConfigError:
                masked = "无法解密"
            row["api_key_masked"] = masked
            row["json_mode"] = bool(row["json_mode"])
            row["disable_thinking"] = bool(row["disable_thinking"])
            row["is_active"] = bool(row["is_active"])
            result.append(row)
        return result

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = f"mdl_{uuid.uuid4().hex}"
        self.database.save_model_profile({
            "profile_id": profile_id, "name": payload["name"],
            "provider": payload.get("provider", "OpenAI兼容"),
            "base_url": payload["base_url"].rstrip("/"), "model": payload["model"],
            "encrypted_api_key": self._encrypt(payload.get("api_key", "")),
            "timeout_seconds": payload.get("timeout_seconds", 30),
            "json_mode": int(payload.get("json_mode", True)),
            "disable_thinking": int(payload.get("disable_thinking", False)),
        })
        return next(p for p in self.list_profiles() if p["profile_id"] == profile_id)

    def update_profile(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self.database.get_model_profile(profile_id)
        if not profile:
            raise ModelConfigError("模型配置不存在")
        if profile["is_active"]:
            raise ModelConfigError("激活中的配置不能直接修改，请复制为新配置")
        allowed = {"name", "provider", "base_url", "model", "timeout_seconds", "json_mode", "disable_thinking"}
        changes = {key: value for key, value in payload.items() if key in allowed and value is not None}
        if "json_mode" in changes: changes["json_mode"] = int(changes["json_mode"])
        if "disable_thinking" in changes: changes["disable_thinking"] = int(changes["disable_thinking"])
        if payload.get("clear_api_key"):
            changes["encrypted_api_key"] = None
        elif payload.get("api_key"):
            changes["encrypted_api_key"] = self._encrypt(payload["api_key"])
        self.database.update_model_profile(profile_id, changes)
        return next(p for p in self.list_profiles() if p["profile_id"] == profile_id)

    async def test_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.database.get_model_profile(profile_id)
        if not profile: raise ModelConfigError("模型配置不存在")
        started = time.perf_counter()
        try:
            extractor = OpenAICompatibleExtractor(self._settings_for(profile))
            await extractor.extract([], "这是模型连通性测试，请按格式返回。")
            latency = round((time.perf_counter() - started) * 1000, 2)
            self.database.record_model_test(profile_id, True, latency, None)
            return {"success": True, "latency_ms": latency, "message": "连接和结构化输出正常"}
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000, 2)
            error = type(exc).__name__
            self.database.record_model_test(profile_id, False, latency, error)
            return {"success": False, "latency_ms": latency, "message": "模型测试失败", "error_type": error}

    async def activate(self, profile_id: str) -> dict[str, Any]:
        profile = self.database.get_model_profile(profile_id)
        if not profile: raise ModelConfigError("模型配置不存在")
        if profile.get("last_test_status") != "success":
            raise ModelConfigError("配置必须测试成功后才能激活")
        new_extractor = OpenAICompatibleExtractor(self._settings_for(profile))
        async with self._lock:
            self.database.activate_model_profile(profile_id)
            self._extractor = new_extractor
            self._source, self._profile_id, self._profile_name = "database", profile_id, profile["name"]
        return self.status()

    def delete(self, profile_id: str) -> None:
        if not self.database.delete_model_profile(profile_id):
            raise ModelConfigError("激活中的配置不能删除，或配置不存在")

    async def _complete(self, messages: list[dict[str, str]], json_mode: bool,
                        max_tokens: int = 600) -> str:
        settings = self._extractor.settings
        if not settings.llm_configured:
            raise LLMError("内网大模型尚未配置")
        extractor = OpenAICompatibleExtractor(settings)
        headers = extractor.headers()
        endpoint = extractor.endpoint
        payload: dict[str, Any] = {
            "model": settings.llm_model, "messages": messages,
            "temperature": 0, "max_tokens": max_tokens,
        }
        if json_mode and settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if settings.llm_disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        last_error: Exception | None = None
        for _ in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=settings.llm_timeout_seconds,
                    verify=extractor.tls_verify(),
                ) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                return str(response.json()["choices"][0]["message"]["content"]).strip()
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
        raise LLMError(f"模型文本生成失败（{type(last_error).__name__}）") from last_error

    async def generate_suggestions(
        self, history: list[dict[str, str]], target_intents: list[str]
    ) -> list[dict[str, str]]:
        if not history:
            return []
        import json
        prompt = (
            "你是尽调助手的猜你想问生成器。根据用户历史，为指定的每个功能各生成1个简短中文问题。"
            "不得重复，不得超出指定功能。仅返回JSON："
            '{"suggestions":[{"text":"问题","intent":"recommendation|filter|statistics|qa"}]}。'
            f"指定功能：{json.dumps(target_intents, ensure_ascii=False)}"
        )
        history_text = json.dumps(history[-20:], ensure_ascii=False)
        try:
            content = await self._complete([
                {"role": "system", "content": prompt},
                {"role": "user", "content": history_text},
            ], True, 500)
            data = json.loads(content)
            result = []
            for item in data.get("suggestions", []):
                intent, text = item.get("intent"), str(item.get("text", "")).strip()[:80]
                if intent in target_intents and text and intent not in {x["intent"] for x in result}:
                    result.append({"text": text, "intent": intent})
            return result
        except Exception:
            return []

    async def match_reports_from_tags(
        self, question: str, report_tags: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Use the active model to interpret non-normalized report tags.

        The caller validates every returned ID and builds the final answer, so
        the model cannot introduce reports that are absent from the snapshot.
        """
        import json

        prompt = (
            "你是银行尽调报告标签统计分析器。用户会询问哪些报告满足某个语义或数值条件。"
            "你必须在一次分析中完成全部报告的判断，并一次性输出所有符合条件的报告ID。"
            "输入中的每个对象是一份报告，包含report_id及本次条件相关的selected_tags。"
            "必须逐对象判断标签值是否满足条件，再汇总所有符合的report_id。"
            "标签值未经规范化，你需要结合标签名称和原始值理解同义表达，例如科技企业可能体现在"
            "行业、主营业务、企业资质等不同标签中。金额比较必须正确换算元、万和亿，并理解区间。"
            "对于金额区间，条件“大于X”表示区间内存在严格大于X的金额；例如1亿-5亿元符合大于1亿元。"
            "只能依据输入JSON，不得使用外部事实，不得编造报告。只返回JSON："
            '{"matched_report_ids":["输入中存在的report_id"],"criteria_summary":"简短判断口径"}。'
            "不确定时保守匹配，matched_report_ids不得包含输入中不存在的ID。"
        )
        all_columns = report_tags.get("tag_columns", {})
        available_names = list(all_columns)
        selected_names = await self.select_statistic_tag_names(question, available_names)
        report_ids = report_tags.get("report_ids", [])
        selected_reports = [
            {
                "report_id": report_id,
                "selected_tags": {
                    name: all_columns[name][index]
                    for name in selected_names
                    if name in all_columns and index < len(all_columns[name])
                },
            }
            for index, report_id in enumerate(report_ids)
        ]
        payload = {"question": question, "reports": selected_reports}
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        for _ in range(2):
            try:
                content = await self._complete(messages, True, 8000)
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    start, end = content.find("{"), content.rfind("}")
                    if start < 0 or end <= start:
                        raise
                    data = json.loads(content[start : end + 1])
                valid_ids = set(report_ids)
                result_ids: list[str] = []
                for report_id in data.get("matched_report_ids", []):
                    report_id = str(report_id)
                    if report_id in valid_ids and report_id not in result_ids:
                        result_ids.append(report_id)
                return {
                    "matched_report_ids": result_ids,
                    "criteria_summary": str(data.get("criteria_summary") or "按全量原始标签进行语义判断")[:300],
                }
            except Exception:
                continue
        return None

    async def select_statistic_tag_names(
        self, question: str, available_names: list[str]
    ) -> list[str]:
        """Select relevant columns generically before the one full ID-matching call."""
        import json

        prompt = (
            "你是尽调报告统计字段选择器。根据用户条件，从给定标准标签名中选择判断报告是否符合条件"
            "所必需的全部标签。组合条件必须选择多列；不得选择无关列。只返回JSON："
            '{"tag_names":["给定标签名"]}。'
        )
        payload = {"question": question, "available_tag_names": available_names}
        try:
            content = await self._complete([
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ], True, 500)
            data = json.loads(content)
            selected = []
            for name in data.get("tag_names", []):
                name = str(name)
                if name in available_names and name not in selected:
                    selected.append(name)
            if selected:
                return selected
        except Exception:
            pass
        # A failed selector must not silently discard relevant data. The full
        # snapshot remains the safe fallback and the matching call can report
        # its own timeout/error explicitly.
        return available_names

    async def answer_competition(self, history: list[dict[str, str]], question: str) -> str:
        prompt = (
            "你是比赛信息问答助手。只回答与比赛要求、规则、评分、时间、报名和参赛相关的问题。"
            "当前没有接入官方比赛资料，不得虚构文件、条款、日期或引用；不确定时明确说明。"
            "回答简洁，并建议用户最终以主办方官方通知为准。"
        )
        return await self._complete([
            {"role": "system", "content": prompt}, *history[-10:],
            {"role": "user", "content": question},
        ], False, 800)
