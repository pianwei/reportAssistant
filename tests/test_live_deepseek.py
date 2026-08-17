from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import mysql_test_url


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("LLM_API_KEY"), reason="未提供真实模型 API Key"),
]


def _live_settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    return replace(
        Settings.from_env(),
        data_dir=root / "data",
        database_url=mysql_test_url(tmp_path / "live.db"),
    )


def test_live_single_turn_recommendation(tmp_path):
    app = create_app(_live_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "user_id": "live-single",
                "session_id": "",
                "message": "请推荐一份适合科学研究和技术服务业小微企业的尽调报告，申请300万元流动资金贷款"
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
            "/api/v1/chat", json={
                "user_id": "live-multiturn", "session_id": "", "message": "帮我推荐一份流动资金贷款相关报告",
            }
        ).json()
        assert first["status"] == "recommendations"
        second = client.post(
            "/api/v1/chat",
            json={"session_id": first["session_id"], "message": "科学研究和技术服务业"},
        ).json()
    assert second["status"] == "recommendations"
    assert {tag["name"] for tag in second["collected_tags"]} == {"行业分类", "授信品种"}


def test_live_amount_disagreement_uses_model_value_without_confirmation(tmp_path):
    app = create_app(_live_settings(tmp_path))
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/chat",
            json={
                "user_id": "live-amount",
                "session_id": "",
                "message": "请推荐报告：公司最新一期财报总资产300万元，本次计划申请100万元流动资金贷款"
            },
        ).json()
    tags = {item["name"]: item["value"] for item in first["collected_tags"]}
    assert tags["最新一期财报总资产"] == "300万元"
    assert tags["授信金额"] == "100万元"
    assert first["status"] == "recommendations"
