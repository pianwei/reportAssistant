from __future__ import annotations

import json
from pathlib import Path

import pytest


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

