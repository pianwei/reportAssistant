from __future__ import annotations

import sqlite3
from dataclasses import replace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import ExtractedTag, ModelExtraction
from test_api import settings_for


class EmptyExtractor:
    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction(intent="report_recommendation", tags=[])


class RoutingExtractor:
    async def extract(self, history, message, expected_tag=None):
        if "统计" in message or "多少篇" in message:
            return ModelExtraction(intent="report_statistics", tags=[], statistic_query="报告总数")
        if "比赛" in message:
            return ModelExtraction(intent="competition_qa", tags=[])
        if "筛选" in message:
            value = "科学研究和技术服务业"
            return ModelExtraction(intent="report_filter", tags=[
                ExtractedTag(name="行业分类", value=value, evidence=value, confidence=1)
            ])
        return ModelExtraction(intent="provide_information", tags=[])


def test_user_history_survives_report_rebuild(data_dir, tmp_path):
    settings = settings_for(data_dir, tmp_path)
    app = create_app(settings, EmptyExtractor())
    with TestClient(app) as client:
        created = client.post("/api/v1/chat", json={"user_id": "alice", "message": "请推荐报告"})
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        owner_conflict = client.post("/api/v1/chat", json={"user_id": "bob", "session_id": session_id, "message": "继续"})
        assert owner_conflict.status_code == 409

    restarted = create_app(settings, EmptyExtractor())
    with TestClient(restarted) as client:
        listing = client.get("/api/v1/users/alice/conversations").json()
        assert listing["items"][0]["session_id"] == session_id
        detail = client.get(f"/api/v1/conversations/{session_id}").json()
        assert len(detail["messages"]) == 2


def test_new_chat_requires_user_id(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), EmptyExtractor())
    with TestClient(app) as client:
        response = client.post("/api/v1/chat", json={"message": "请推荐报告"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SESSION_USER_ERROR"


def test_unified_filter_statistics_qa_and_ops_metrics(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), RoutingExtractor())
    async def fake_competition_answer(history, question):
        return "请以主办方发布的正式比赛规则为准。"
    app.state.model_manager.answer_competition = fake_competition_answer
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={
            "user_id": "alice", "message": "筛选科学研究和技术服务业的报告"
        }).json()
        search = client.post("/api/v1/chat", json={
            "session_id": first["session_id"], "message": "直接筛选"
        })
        assert search.status_code == 200
        assert search.json()["status"] == "filter_results"
        assert len(search.json()["recommendations"]) == 1

        statistics = client.post("/api/v1/chat", json={
            "user_id": "alice", "message": "现在有多少篇报告？"
        }).json()
        assert statistics["status"] == "statistics"
        assert statistics["statistic"]["value"] == 1

        qa = client.post("/api/v1/chat", json={"user_id": "alice", "message": "比赛规则是什么？"})
        assert qa.status_code == 200
        assert qa.json()["status"] == "answer"
        assert qa.json()["answer"]["official"] is False
        assert "未接入官方比赛资料" in qa.json()["answer"]["disclaimer"]

        for path in ("/api/v1/reports/search", "/api/v1/statistics/reports", "/api/v1/qa/mock", "/api/v1/filter-options"):
            assert client.get(path).status_code == 404

        metrics = client.get("/api/v1/ops/metrics").json()
        assert metrics["sessions"] == 3
        assert metrics["feature_usage"]["qa"] == 1
        ops_list = client.get("/api/v1/ops/conversations", params={"keyword": "比赛规则"}).json()
        assert len(ops_list["items"]) == 1


def test_suggestions_rotate_across_four_features(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), EmptyExtractor())
    with TestClient(app) as client:
        first = client.post("/api/v1/suggestions", json={"user_id": "alice"}).json()
        second = client.post("/api/v1/suggestions", json={
            "user_id": "alice", "previous_batch_id": first["batch_id"]
        }).json()
    assert len(first["suggestions"]) == 3
    assert len({item["intent"] for item in first["suggestions"]}) == 3
    assert "qa" not in {item["intent"] for item in first["suggestions"]}
    assert "qa" in {item["intent"] for item in second["suggestions"]}
    assert not ({item["text"] for item in first["suggestions"]} & {item["text"] for item in second["suggestions"]})


def test_finish_without_tags_uses_completeness_ranking(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), EmptyExtractor())
    with TestClient(app) as client:
        first = client.post("/api/v1/chat", json={"user_id": "alice", "message": "给我推荐几个优秀报告"}).json()
        assert first["status"] == "recommendations"
        finished = client.post("/api/v1/chat", json={
            "session_id": first["session_id"], "message": "按现有信息生成"
        }).json()
    assert finished["status"] == "recommendations"
    assert finished["recommendations"][0]["score"] > 0
    assert "完整度" in finished["recommendations"][0]["recommendation_reason"]


def test_model_profile_key_is_encrypted_and_never_returned(data_dir, tmp_path):
    settings = replace(
        settings_for(data_dir, tmp_path),
        model_config_master_key=Fernet.generate_key().decode("ascii"),
    )
    app = create_app(settings, EmptyExtractor())
    secret = "sk-sensitive-test-value"
    with TestClient(app) as client:
        response = client.post("/api/v1/ops/model-profiles", json={
            "name": "测试配置",
            "provider": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": secret,
            "timeout_seconds": 20,
            "json_mode": True,
            "disable_thinking": False,
        })
        assert response.status_code == 201
        profile = response.json()
        profile_id = profile["profile_id"]
        assert "api_key" not in profile
        assert "encrypted_api_key" not in profile
        assert profile["api_key_masked"].startswith("sk-")

        with sqlite3.connect(settings.database_path) as conn:
            stored = conn.execute(
                "SELECT encrypted_api_key FROM model_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()[0]
        assert stored != secret
        assert secret not in stored

        premature = client.post(f"/api/v1/ops/model-profiles/{profile_id}/activate")
        assert premature.status_code == 400
        app.state.database.record_model_test(profile_id, True, 12.5, None)
        activated = client.post(f"/api/v1/ops/model-profiles/{profile_id}/activate")
        assert activated.status_code == 200
        assert activated.json()["source"] == "database"
        assert client.delete(f"/api/v1/ops/model-profiles/{profile_id}").status_code == 400

        listing_text = client.get("/api/v1/ops/model-profiles").text
        assert secret not in listing_text
        assert stored not in listing_text


def test_spa_assets_are_served(data_dir, tmp_path):
    app = create_app(settings_for(data_dir, tmp_path), EmptyExtractor())
    with TestClient(app) as client:
        mobile = client.get("/")
        ops = client.get("/ops")
    assert mobile.status_code == 200 and '<div id="app"></div>' in mobile.text
    assert ops.status_code == 200 and '<div id="app"></div>' in ops.text
