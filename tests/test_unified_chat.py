from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.llm import LLMError
from app.main import create_app
from app.schemas import ExtractedTag, ModelExtraction
from conftest import make_report
from test_api import settings_for


class IntentExtractor:
    async def extract(self, history, message, expected_tag=None):
        if "统计" in message or "多少篇" in message:
            return ModelExtraction(intent="report_statistics", tags=[])
        if "天气" in message:
            return ModelExtraction(intent="unsupported", tags=[])
        if "筛选" in message:
            return ModelExtraction(intent="report_filter", tags=[])
        return ModelExtraction(intent="report_recommendation", tags=[])


class FailingExtractor:
    async def extract(self, history, message, expected_tag=None):
        raise LLMError("test failure")


class CompleteExtractor:
    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction(intent="report_recommendation", tags=[
            ExtractedTag(
                name="行业分类", value="科学研究和技术服务业",
                evidence="科学研究和技术服务业", confidence=1,
            ),
            ExtractedTag(
                name="授信金额", value="300万元", evidence="申请300万元", confidence=1,
            ),
        ])


def test_explicit_intent_switch_marks_session_mixed(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), IntentExtractor())
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "推荐几个报告"
        }).json()
        switched = client.post("/api/v1/chat", json={
            "session_id": first["session_id"], "message": "现在统计有多少篇报告"
        }).json()
        detail = client.get(f"/api/v1/conversations/{first['session_id']}").json()
        recommendation_sessions = client.get(
            "/api/v1/ops/conversations", params={"feature": "recommendation"}
        ).json()["items"]
        statistics_sessions = client.get(
            "/api/v1/ops/conversations", params={"feature": "statistics"}
        ).json()["items"]
    assert switched["intent"] == "statistics"
    assert switched["status"] == "statistics"
    assert detail["feature"] == "mixed"
    assert {message["intent"] for message in detail["messages"]} >= {"recommendation", "statistics"}
    assert first["session_id"] in {item["session_id"] for item in recommendation_sessions}
    assert first["session_id"] in {item["session_id"] for item in statistics_sessions}


def test_keyword_router_falls_back_when_model_is_unavailable(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), FailingExtractor())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "现在有多少篇报告？"
        })
    assert response.status_code == 200
    assert response.json()["intent"] == "statistics"
    assert response.json()["statistic"]["value"] == 1


def test_intent_extractor_receives_only_the_latest_five_rounds(data_dir, tmp_path):
    class RecordingExtractor:
        def __init__(self):
            self.histories = []

        async def extract(self, history, message, expected_tag=None):
            self.histories.append(list(history))
            return ModelExtraction(intent="report_recommendation", tags=[])

    extractor = RecordingExtractor()
    app = create_app(settings_for(data_dir, tmp_path), extractor)
    with TestClient(app) as client:
        session_id = None
        for index in range(1, 8):
            body = {"session_id": session_id or "", "message": f"推荐报告，第{index}轮"}
            if session_id:
                body["session_id"] = session_id
            else:
                body["user_id"] = "alice"
            session_id = client.post("/api/v1/chat", json=body).json()["session_id"]

    latest_history = extractor.histories[-1]
    assert len(latest_history) == 5
    assert {item["role"] for item in latest_history} == {"user"}
    assert "第1轮" not in " ".join(item["content"] for item in latest_history)
    assert "第2轮" in latest_history[0]["content"]


def test_provide_information_continues_statistics_intent(data_dir, tmp_path):
    class ContextExtractor:
        async def extract(self, history, message, expected_tag=None):
            if not history:
                return ModelExtraction(intent="report_statistics", tags=[])
            return ModelExtraction(intent="provide_information", tags=[])

    app = create_app(settings_for(data_dir, tmp_path), ContextExtractor())
    async def fake_statistics(_question):
        return "统计完成。", {"metric": "test", "title": "测试", "value": 1, "breakdown": []}
    app.state.feature_service.statistics_for_question = fake_statistics
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "统计报告数量",
        }).json()
        followup = client.post("/api/v1/chat", json={
            "session_id": first["session_id"], "message": "那小微企业呢",
        }).json()

    assert followup["session_id"] == first["session_id"]
    assert followup["intent"] == "statistics"
    assert followup["status"] == "statistics"


def test_greeting_uses_fixed_capability_message_without_model_routing(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), IntentExtractor())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "您好"
        }).json()
    assert response["status"] == "greeting"
    assert response["intent"] == "greeting"
    assert "推荐或筛选尽调报告" in response["assistant_message"]


def test_unsupported_question_is_politely_rejected(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), IntentExtractor())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "今天天气如何？"
        }).json()
    assert response["status"] == "unsupported"
    assert "超出了我目前的回答范围" in response["assistant_message"]
    assert "推荐或筛选尽调报告" in response["assistant_message"]


def test_competition_qa_requires_explicit_competition_context(data_dir, tmp_path):
    class MisclassifiedQA:
        async def extract(self, history, message, expected_tag=None):
            return ModelExtraction(intent="competition_qa", tags=[])

    app = create_app(settings_for(data_dir, tmp_path), MisclassifiedQA())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={
            "user_id": "alice", "session_id": "", "message": "量子计算是什么？"
        }).json()
    assert response["status"] == "unsupported"


def test_related_reports_excludes_source_report(data_dir, tmp_path):
    (data_dir / "second.json").write_text(
        json.dumps(make_report("report-2", "第二份报告"), ensure_ascii=False), encoding="utf-8"
    )
    app = create_app(settings_for(data_dir, tmp_path), CompleteExtractor())
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={
            "user_id": "alice",
            "session_id": "",
            "message": "推荐科学研究和技术服务业申请300万元的报告",
        }).json()
        related = client.post("/api/v1/chat", json={
            "session_id": first["session_id"],
            "action": {"type": "related_reports", "report_id": "report-1"},
        }).json()
    assert related["status"] == "recommendations"
    assert all(item["report_id"] != "report-1" for item in related["recommendations"])
    assert related["recommendations"][0]["report_id"] == "report-2"
