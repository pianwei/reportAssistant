from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="未提供真实模型 API Key"),
]


def _live_settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    return replace(
        Settings.from_env(),
        data_dir=root / "data",
        database_path=tmp_path / "live.db",
    )


def test_live_single_turn_recommendation(tmp_path):
    app = create_app(_live_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "请推荐一份适合科学研究和技术服务业小微企业的尽调报告，申请300万元流动资金贷款"
            },
        )
        body = response.json()
        # DeepSeek 偶尔漏提规则已识别的标签；新策略要求先向用户确认，而非静默采用规则。
        for _ in range(5):
            if body["status"] != "needs_clarification":
                break
            question = body["question"]
            assert question["examples"]
            response = client.post(
                "/api/v1/chat",
                json={
                    "session_id": body["session_id"],
                    "message": question["examples"][0],
                },
            )
            body = response.json()
    tags = {item["name"]: item["value"] for item in body["collected_tags"]}
    assert response.status_code == 200
    assert body["status"] == "recommendations"
    assert tags["行业分类"] == "科学研究和技术服务业"
    assert tags["授信金额"] == "300万元"


def test_live_multiturn_expected_tag(tmp_path):
    app = create_app(_live_settings(tmp_path))
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/chat", json={"message": "帮我推荐一份流动资金贷款相关报告"}
        ).json()
        assert first["status"] == "needs_clarification"
        assert first["question"]["tag_name"] == "行业分类"
        second = client.post(
            "/api/v1/chat",
            json={"session_id": first["session_id"], "message": "科学研究和技术服务业"},
        ).json()
    assert second["status"] == "recommendations"
    assert {tag["name"] for tag in second["collected_tags"]} == {"行业分类", "授信品种"}


def test_live_amount_disagreement_requires_confirmation(tmp_path):
    app = create_app(_live_settings(tmp_path))
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/chat",
            json={
                "message": "公司最新一期财报总资产300万元。本次计划申请100万元流动资金贷款"
            },
        ).json()
        assert first["status"] == "needs_clarification"
        assert first["question"]["tag_name"] == "授信金额"
        second = client.post(
            "/api/v1/chat",
            json={"session_id": first["session_id"], "message": "授信金额是100万元"},
        ).json()
    tags = {item["name"]: item["value"] for item in second["collected_tags"]}
    assert tags["最新一期财报总资产"] == "300万元"
    assert tags["授信金额"] == "100万元"
    assert second["status"] == "recommendations"
