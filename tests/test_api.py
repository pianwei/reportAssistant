from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import ModelExtraction


class FakeExtractor:
    def __init__(self, outputs: list[dict]):
        self.outputs = outputs
        self.expected_tags: list[str | None] = []

    async def extract(self, history, message, expected_tag=None):
        self.expected_tags.append(expected_tag)
        return ModelExtraction.model_validate(self.outputs.pop(0))


def settings_for(data_dir, tmp_path) -> Settings:
    return Settings(
        data_dir=data_dir,
        database_path=tmp_path / "runtime" / "test.db",
        llm_base_url="http://model.test/v1",
        llm_model="test-model",
        llm_api_key="",
        llm_timeout_seconds=1,
        cors_origins=("http://localhost:3000",),
        log_level="INFO",
    )


def test_health_and_report_detail(data_dir, tmp_path):
    extractor = FakeExtractor([])
    app = create_app(settings_for(data_dir, tmp_path), extractor)
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ready"
        assert health.json()["report_count"] == 1
        assert health.json()["tag_count"] == 2

        detail = client.get("/api/v1/reports/report-1")
        assert detail.status_code == 200
        assert detail.json()["report_name"] == "测试尽调报告"


def test_model_and_rules_agree_can_return_recommendation_in_one_turn(data_dir, tmp_path):
    message = "请推荐科学研究和技术服务业小微企业申请300万元流动资金贷款的报告"
    extractor = FakeExtractor([{
        "intent": "report_recommendation",
        "tags": [
            {"name": "行业分类", "value": "科学研究和技术服务业", "evidence": message, "confidence": 0.99},
            {"name": "企业规模", "value": "小微企业", "evidence": message, "confidence": 0.99},
            {"name": "授信金额", "value": "300万元", "evidence": message, "confidence": 0.99},
            {"name": "授信品种", "value": "流动资金贷款", "evidence": message, "confidence": 0.99},
        ],
    }])
    app = create_app(settings_for(data_dir, tmp_path), extractor)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"user_id": "user-1", "message": message},
        )
        payload = response.json()
        assert response.status_code == 200
        assert payload["status"] == "recommendations"
        assert payload["recommendations"][0]["report_id"] == "report-1"
        assert {tag["name"] for tag in payload["collected_tags"]} == {
            "行业分类", "企业规模", "授信金额", "授信品种"
        }


def test_result_first_does_not_force_an_expected_tag(data_dir, tmp_path):
    extractor = FakeExtractor(
        [
            {"intent": "report_recommendation", "tags": []},
            {
                "intent": "provide_information",
                "tags": [{
                    "name": "最新一期财报总资产",
                    "value": "300万元",
                    "evidence": "300万元",
                    "confidence": 0.99,
                }],
            },
        ]
    )
    app = create_app(settings_for(data_dir, tmp_path), extractor)
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={"user_id": "user-1", "message": "请推荐报告"}).json()
        second = client.post(
            "/api/v1/chat",
            json={"session_id": first["session_id"], "message": "300万元"},
        ).json()
        assert extractor.expected_tags == [None, None]
        assert first["status"] == "recommendations"
        assert second["status"] == "recommendations"


def test_unknown_session_uses_error_envelope(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), FakeExtractor([]))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat", json={"session_id": "missing", "message": "继续"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
        assert response.headers["X-Request-ID"]


def test_rule_amount_is_returned_as_confirmation_without_blocking_results(data_dir, tmp_path):
    message = "科学研究和技术服务业小微企业申请300万元流动资金贷款"
    extractor = FakeExtractor([
        {
            "intent": "report_recommendation",
            "tags": [
                {"name": "行业分类", "value": "科学研究和技术服务业", "evidence": "科学研究和技术服务业", "confidence": 1},
                {"name": "企业规模", "value": "小微企业", "evidence": "小微企业", "confidence": 1},
                {"name": "授信品种", "value": "流动资金贷款", "evidence": "流动资金贷款", "confidence": 1},
            ],
        },
        {"intent": "provide_information", "tags": []},
    ])
    app = create_app(settings_for(data_dir, tmp_path), extractor)
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/chat", json={"user_id": "user-1", "message": message}
        ).json()
    assert first["status"] == "recommendations"
    assert first["recommendations"]
    assert first["follow_up"]["kind"] == "confirmation"
