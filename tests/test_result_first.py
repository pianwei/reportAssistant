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
            return ModelExtraction.model_validate({"intent":"report_filter","tags":tags})
        return ModelExtraction(intent="report_recommendation", tags=[])


def _tags(industry: str, size: str, product: str = "流动资金贷款") -> list[dict]:
    return [
        {"维度类别":"客户维度","标签名称":"行业分类","提取结果":industry,"原文出处":"测试","是否提供完整数据":"是","备注":""},
        {"维度类别":"客户维度","标签名称":"企业规模","提取结果":size,"原文出处":"测试","是否提供完整数据":"是","备注":""},
        {"维度类别":"业务维度","标签名称":"授信品种","提取结果":product,"原文出处":"测试","是否提供完整数据":"是","备注":""},
    ]


def _app_with_reports(data_dir, tmp_path):
    reports=[
        make_report("r1","制造小微一",_tags("制造业","小微企业")),
        make_report("r2","制造小微二",_tags("制造业","小微企业","固定资产贷款")),
        make_report("r3","制造中型",_tags("制造业","中型企业")),
        make_report("r4","服务小微",_tags("科学研究和技术服务业","小微企业")),
        make_report("r5","零售小微",_tags("批发和零售业","小微企业")),
    ]
    (data_dir/"report.json").write_text(json.dumps(reports,ensure_ascii=False),encoding="utf-8")
    return create_app(settings_for(data_dir,tmp_path),ResultExtractor())


def test_no_condition_recommendation_returns_top3_and_distinguishing_options(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        payload=client.post("/api/v1/chat",json={"user_id":"u1","message":"推荐报告"}).json()
    assert payload["status"] == "recommendations"
    assert len(payload["recommendations"]) == 3
    assert payload["follow_up"]["kind"] == "preference"
    values=[option["value"] for group in payload["follow_up"]["groups"] for option in group["options"]]
    assert len(values) == len(set(values))


def test_single_filter_returns_all_and_multiple_tags_are_strict_and(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        one=client.post("/api/v1/chat",json={"user_id":"u1","message":"筛选制造业报告"}).json()
        two=client.post("/api/v1/chat",json={"user_id":"u2","message":"筛选制造业小微企业报告"}).json()
    assert one["status"] == "filter_results"
    assert len(one["recommendations"]) == 3
    assert {x["report_id"] for x in two["recommendations"]} == {"r1","r2"}, two


def test_apply_multi_refinement_skip_and_three_round_limit(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        first=client.post("/api/v1/chat",json={"user_id":"u1","message":"推荐报告"}).json()
        session=first["session_id"]
        action={"type":"apply_refinement","selections":[{"tag_name":"行业分类","value":"制造业"},{"tag_name":"企业规模","value":"小微企业"}]}
        current=client.post("/api/v1/chat",json={"session_id":session,"action":action}).json()
        assert {x["name"] for x in current["collected_tags"]} >= {"行业分类","企业规模"}
        for value in ("流动资金贷款","固定资产贷款"):
            current=client.post("/api/v1/chat",json={"session_id":session,"action":{"type":"apply_refinement","selections":[{"tag_name":"授信品种","value":value}]}}).json()
        assert current["follow_up"] is None
        skipped=client.post("/api/v1/chat",json={"session_id":session,"action":{"type":"skip_refinement"}}).json()
    assert skipped["follow_up"] is None


def test_zero_filter_result_can_remove_latest_condition(data_dir,tmp_path):
    app=_app_with_reports(data_dir,tmp_path)
    with TestClient(app) as client:
        first=client.post("/api/v1/chat",json={"user_id":"u1","message":"筛选制造业报告"}).json()
        zero=client.post("/api/v1/chat",json={"session_id":first["session_id"],"action":{"type":"apply_refinement","selections":[{"tag_name":"企业规模","value":"大型企业"}]}}).json()
        restored=client.post("/api/v1/chat",json={"session_id":first["session_id"],"action":{"type":"remove_tag","tag_name":"企业规模"}}).json()
    assert zero["recommendations"] == []
    assert zero["follow_up"]["kind"] == "no_results"
    assert len(restored["recommendations"]) == 3
