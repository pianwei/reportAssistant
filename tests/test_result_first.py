from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import ModelExtraction
from conftest import make_report
from test_api import settings_for


class ResultExtractor:
    async def extract(self, history, message, expected_tag=None):
        if "筛选" in message:
            tags=[]
            if "制造" in message:
                tags.append({"name":"行业分类","value":"制造业","evidence":"制造业","confidence":1})
            if "小微" in message:
                tags.append({"name":"企业规模","value":"小微企业","evidence":"小微企业","confidence":1})
            if "大型" in message:
                tags.append({"name":"企业规模","value":"大型企业","evidence":"大型企业","confidence":1})
            return ModelExtraction.model_validate({"intent":"report_filter","tags":tags})
        return ModelExtraction(intent="report_recommendation", tags=[])


class UnsupportedExtractor:
    async def extract(self, history, message, expected_tag=None):
        return ModelExtraction(intent="unsupported", tags=[])


def _tags(industry: str, size: str, product: str = "流动资金贷款") -> list[dict]:
    return [
        {"维度类别":"客户维度","标签名称":"行业分类","提取结果":industry,"原文出处":"测试","是否提供完整数据":"是","备注":""},
        {"维度类别":"客户维度","标签名称":"企业规模","提取结果":size,"原文出处":"测试","是否提供完整数据":"是","备注":""},
        {"维度类别":"业务维度","标签名称":"授信品种","提取结果":product,"原文出处":"测试","是否提供完整数据":"是","备注":""},
    ]


def _app_with_reports(data_dir, tmp_path, extractor=None):
    reports=[
        make_report("r1","制造小微一",_tags("制造业","小微企业")),
        make_report("r2","制造小微二",_tags("制造业","小微企业","固定资产贷款")),
        make_report("r3","制造中型",_tags("制造业","中型企业")),
        make_report("r4","服务小微",_tags("科学研究和技术服务业","小微企业")),
        make_report("r5","零售小微",_tags("批发和零售业","小微企业")),
    ]
    (data_dir/"report.json").write_text(json.dumps(reports,ensure_ascii=False),encoding="utf-8")
    return create_app(settings_for(data_dir,tmp_path),extractor or ResultExtractor())


def test_no_condition_recommendation_returns_top3(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        payload=client.post("/api/v1/chat",json={"user_id":"u1","session_id":"","message":"推荐报告"}).json()
    assert payload["status"] == "recommendations"
    assert len(payload["recommendations"]) == 3


def test_rule_extraction_fills_explicit_tag_omitted_by_model(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        payload=client.post(
            "/api/v1/chat",
            json={"user_id":"rule-fill","session_id":"","message":"给我推荐几个小微企业的报告"},
        ).json()
    assert payload["collected_tags"][0]["name"] == "企业规模"
    assert payload["collected_tags"][0]["value"] == "小微企业"
    assert all(item["score"] == 100 for item in payload["recommendations"])
    assert all(item["matched_tags"][0]["name"] == "企业规模" for item in payload["recommendations"])


def test_explicit_recommendation_keywords_override_model_unsupported(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path,UnsupportedExtractor())
    with TestClient(app) as client:
        payload=client.post(
            "/api/v1/chat",
            json={"user_id":"route-fallback","session_id":"","message":"给我推荐几个小微企业的报告"},
        ).json()
    assert payload["status"] == "recommendations"
    assert payload["collected_tags"][0]["value"] == "小微企业"


def test_single_filter_returns_all_and_multiple_tags_are_strict_and(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        one=client.post("/api/v1/chat",json={"user_id":"u1","session_id":"","message":"筛选制造业报告"}).json()
        two=client.post("/api/v1/chat",json={"user_id":"u2","session_id":"","message":"筛选制造业小微企业报告"}).json()
    assert one["status"] == "filter_results"
    assert len(one["recommendations"]) == 3
    assert {x["report_id"] for x in two["recommendations"]} == {"r1","r2"}, two


def test_user_can_replace_filter_conditions_by_sending_a_new_question(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        first=client.post("/api/v1/chat",json={"user_id":"u1","session_id":"","message":"筛选制造业大型企业报告"}).json()
        session=first["session_id"]
        assert first["recommendations"] == []
        current=client.post("/api/v1/chat",json={"session_id":session,"message":"筛选制造业小微企业报告"}).json()
    assert {x["report_id"] for x in current["recommendations"]} == {"r1","r2"}


def test_same_session_accumulates_fields_and_new_filter_clears_without_results(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        first=client.post("/api/v1/chat",json={
            "user_id":"accumulate", "session_id":"", "message":"筛选制造业报告",
        }).json()
        second=client.post("/api/v1/chat",json={
            "session_id":first["session_id"], "message":"再加上小微企业",
        }).json()
        reset=client.post("/api/v1/chat",json={
            "session_id":first["session_id"], "message":"新筛选",
        }).json()

    assert {tag["name"] for tag in second["collected_tags"]} == {"行业分类", "企业规模"}
    assert second["intent"] == "filter"
    assert second["status"] == "filter_results"
    assert {x["report_id"] for x in second["recommendations"]} == {"r1", "r2"}
    assert reset["intent"] == "filter"
    assert reset["status"] == "needs_clarification"
    assert reset["assistant_message"] == "你有什么其他想要了解的尽调报告吗？"
    assert reset["collected_tags"] == []
    assert reset["recommendations"] == []


def test_removed_refinement_action_is_rejected(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        first=client.post("/api/v1/chat",json={"user_id":"u1","session_id":"","message":"筛选制造业报告"}).json()
        response=client.post("/api/v1/chat",json={"session_id":first["session_id"],"action":{"type":"skip_refinement"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
