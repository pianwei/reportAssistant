from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest


def mysql_test_url(key: object) -> str:
    admin_url = os.getenv("MYSQL_TEST_ADMIN_URL", "").strip()
    if not admin_url:
        pytest.skip("MYSQL_TEST_ADMIN_URL 未配置，跳过 MySQL 集成测试")

    import pymysql

    parsed = urlparse(admin_url.replace("mysql+pymysql://", "mysql://", 1))
    database_name = "dda_test_" + hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]
    connection = pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()
    return parsed._replace(path=f"/{database_name}").geturl()


def make_report(
    report_id: str | None = "report-1",
    name: str = "测试尽调报告",
    tags: list[dict] | None = None,
) -> dict:
    tags = tags or [
        {
            "维度类别": "客户维度",
            "标签名称": "行业分类",
            "提取结果": "科学研究和技术服务业",
            "原文出处": "测试原文",
            "是否提供完整数据": "是",
            "备注": "",
        },
        {
            "维度类别": "业务维度",
            "标签名称": "授信金额",
            "提取结果": "100万-500万元",
            "原文出处": "测试原文",
            "是否提供完整数据": "是",
            "备注": "",
        },
    ]
    result = {
        "尽调报告综述": {
            "报告名称": name,
            "报告类型": "测试类型",
            "客户概况": "客户概况",
            "主营业务与经营": "主营业务",
            "财务概况": "财务概况",
            "授信方案": "授信方案",
            "担保与还款": "担保与还款",
            "主要风险": ["风险一"],
            "综合评价": "综合评价",
        },
        "尽调报告标签": {"标签数量": len(tags), "提取结果": tags},
    }
    if report_id is not None:
        result["报告ID"] = report_id
    return result


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "report.json").write_text(
        json.dumps(make_report(), ensure_ascii=False), encoding="utf-8"
    )
    return directory
