from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import ModelExtraction
from app.service import ChatService
from conftest import make_report
from test_api import settings_for


class StatisticsExtractor:
    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction(intent="report_statistics", tags=[], statistic_query=message)


class WrongIntentExtractor:
    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction(intent="report_recommendation", tags=[])


def _tags(industry: str, amount: str) -> list[dict]:
    return [
        {"维度类别":"客户维度","标签名称":"行业分类","提取结果":industry,"原文出处":"行业原文","是否提供完整数据":"是","备注":""},
        {"维度类别":"业务维度","标签名称":"授信金额","提取结果":amount,"原文出处":"金额原文","是否提供完整数据":"是","备注":""},
    ]


def _app(data_dir, tmp_path, extractor=None):
    reports = [
        make_report("r-tech", "科技研发企业报告", _tags("软件和信息技术服务业", "300万元")),
        make_report("r-retail", "零售企业报告", _tags("批发和零售业", "150万元")),
        make_report("r-chip", "半导体设备报告", _tags("高端装备制造", "500万元")),
    ]
    (data_dir / "report.json").write_text(json.dumps(reports, ensure_ascii=False), encoding="utf-8")
    return create_app(settings_for(data_dir, tmp_path), extractor or StatisticsExtractor())


@pytest.mark.parametrize("message", [
    "科技行业有几篇报告", "小微企业报告占比多少", "各行业报告数量分布",
    "授信金额最高的报告", "报告类型排名", "平均授信额度是多少",
])
def test_quantitative_questions_are_routed_to_statistics(message):
    assert ChatService._keyword_intent(message) == "statistics"


@pytest.mark.parametrize(("message", "intent"), [
    ("筛选科技行业报告", "filter"),
    ("查找授信金额超过200万元的报告", "filter"),
    ("推荐几个适合小微企业的案例", "recommendation"),
])
def test_non_statistical_report_goals_keep_their_intent(message, intent):
    assert ChatService._keyword_intent(message) == intent


def test_semantic_statistics_sends_complete_tag_snapshot_and_validates_ids(data_dir, tmp_path):
    app = _app(data_dir, tmp_path)
    captured = {}

    async def fake_match(question, snapshot):
        captured["question"] = question
        captured["snapshot"] = snapshot
        return {
            "matched_report_ids": ["r-tech", "r-chip", "invented-id"],
            "criteria_summary": "行业或主营方向具有科技属性",
        }

    app.state.model_manager.match_reports_from_tags = fake_match
    with TestClient(app) as client:
        payload = client.post("/api/v1/chat", json={
            "user_id": "stats-user", "message": "科技企业的报告有哪些？",
        }).json()

    assert payload["status"] == "statistics"
    assert "source" not in payload["statistic"]
    assert {item["report_id"] for item in payload["statistic"]["reports"]} == {"r-tech", "r-chip"}
    assert len(captured["snapshot"]) == 3
    assert all(len(report["tags"]) == 2 for report in captured["snapshot"])
    assert "invented-id" not in payload["assistant_message"]
    assert "判断口径" not in payload["assistant_message"]


def test_amount_statistics_is_enforced_by_backend_after_model_analysis(data_dir, tmp_path):
    app = _app(data_dir, tmp_path)

    async def fake_match(_question, _snapshot):
        return {"matched_report_ids": ["r-retail"], "criteria_summary": "授信额度超过200万元"}

    app.state.model_manager.match_reports_from_tags = fake_match
    with TestClient(app) as client:
        payload = client.post("/api/v1/chat", json={
            "user_id": "stats-user", "message": "授信额度大于200万的报告有哪些？",
        }).json()

    assert payload["status"] == "statistics"
    assert payload["statistic"]["value"] == 2
    assert {item["report_id"] for item in payload["statistic"]["reports"]} == {"r-tech", "r-chip"}
    assert "零售企业报告" not in payload["assistant_message"]


def test_conditional_count_overrides_wrong_model_intent_and_returns_count_only(data_dir, tmp_path):
    app = _app(data_dir, tmp_path, WrongIntentExtractor())

    async def fake_match(_question, _snapshot):
        return {
            "matched_report_ids": ["r-tech", "r-chip"],
            "criteria_summary": "标签体现科技属性",
        }

    app.state.model_manager.match_reports_from_tags = fake_match
    with TestClient(app) as client:
        payload = client.post("/api/v1/chat", json={
            "user_id": "intent-user", "message": "科技行业有几篇报告",
        }).json()

    assert payload["intent"] == "statistics"
    assert payload["status"] == "statistics"
    assert payload["recommendations"] is None
    assert payload["statistic"]["value"] == 2
    assert payload["assistant_message"] == "共找到 2 份符合条件的报告。"
