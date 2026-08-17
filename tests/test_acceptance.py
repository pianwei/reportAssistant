from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.loader import DataLoadError, load_reports
from app.main import create_app
from app.schemas import ModelExtraction
from conftest import make_report, mysql_test_url


class SequenceExtractor:
    def __init__(self, outputs: list[dict]):
        self.outputs = outputs

    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction.model_validate(self.outputs.pop(0))


def _settings(data_dir: Path, database_key: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        llm_base_url="http://model.test/v1",
        llm_model="test-model",
        llm_api_key="",
        llm_timeout_seconds=1,
        cors_origins=("http://localhost:3000",),
        log_level="INFO",
        database_url=mysql_test_url(database_key),
    )


def test_current_production_sample_loads_all_tags(tmp_path):
    root = Path(__file__).resolve().parents[1]
    expected_reports = load_reports(root / "data")
    expected_tag_count = sum(
        len(item.report.tag_collection.tags) for item in expected_reports
    )
    app = create_app(
        _settings(root / "data", tmp_path / "sample.db"), SequenceExtractor([])
    )
    with TestClient(app) as client:
        health = client.get("/api/v1/health").json()
        assert health["report_count"] == len(expected_reports)
        assert health["tag_count"] == expected_tag_count


def test_report_data_is_frozen_until_restart(data_dir, tmp_path):
    database_key = tmp_path / "frozen"
    settings = _settings(data_dir, database_key)
    app = create_app(settings, SequenceExtractor([]))
    with TestClient(app) as client:
        before = client.get("/api/v1/reports/report-1").json()
        changed = make_report("report-1", "重启后报告")
        (data_dir / "report.json").write_text(
            json.dumps(changed, ensure_ascii=False), encoding="utf-8"
        )
        during = client.get("/api/v1/reports/report-1").json()
        assert before["report_name"] == "测试尽调报告"
        assert during["report_name"] == "测试尽调报告"

    restarted = create_app(settings, SequenceExtractor([]))
    with TestClient(restarted) as client:
        after = client.get("/api/v1/reports/report-1").json()
        assert after["report_name"] == "重启后报告"


def test_invalid_source_prevents_startup(data_dir, tmp_path):
    (data_dir / "report.json").write_text("{invalid", encoding="utf-8")
    app = create_app(_settings(data_dir, tmp_path / "invalid.db"), SequenceExtractor([]))
    with pytest.raises(DataLoadError, match="无法读取"):
        with TestClient(app):
            pass


def test_openapi_has_no_runtime_import_endpoint(data_dir, tmp_path):
    app = create_app(_settings(data_dir, tmp_path / "routes.db"), SequenceExtractor([]))
    with TestClient(app) as client:
        paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/v1/chat",
        "/api/v1/health",
        "/api/v1/reports/{report_id}",
    }.issubset(paths)
    assert not any("import" in path or "reload" in path for path in paths)
    assert not {
        "/api/v1/filter-options", "/api/v1/reports/search",
        "/api/v1/statistics/reports", "/api/v1/qa/mock",
    } & paths


def test_validation_and_not_found_use_error_envelope(data_dir, tmp_path):
    app = create_app(_settings(data_dir, tmp_path / "errors.db"), SequenceExtractor([]))
    with TestClient(app) as client:
        invalid = client.post("/api/v1/chat", json={"session_id": "", "message": "   "})
        missing = client.get("/api/v1/reports/not-found")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_recommendation_without_details_returns_immediate_result(data_dir, tmp_path):
    outputs = [{"intent": "report_recommendation", "tags": []}]
    app = create_app(_settings(data_dir, tmp_path / "rounds.db"), SequenceExtractor(outputs))
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"user_id": "user-1", "session_id": "", "message": "请推荐报告"})
        payload = response.json()
    assert payload["status"] == "recommendations"
    assert payload["recommendations"]
    assert payload["information_incomplete"] is True
