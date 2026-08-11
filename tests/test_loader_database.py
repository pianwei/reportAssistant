from __future__ import annotations

import json

import pytest

from app.database import Database
from app.loader import DataLoadError, load_reports
from conftest import make_report


def test_load_single_report_and_rebuild_database(data_dir, tmp_path):
    loaded = load_reports(data_dir)
    assert len(loaded) == 1
    assert len(loaded[0].report.tag_collection.tags) == 2

    database = Database(tmp_path / "runtime" / "app.db")
    assert database.rebuild(loaded) == (1, 2)
    assert database.counts() == (1, 2)


def test_supports_array_and_generated_id(data_dir):
    reports = [
        make_report(report_id=None, name="报告甲"),
        make_report(report_id=None, name="报告乙"),
    ]
    (data_dir / "report.json").write_text(
        json.dumps(reports, ensure_ascii=False), encoding="utf-8"
    )
    loaded = load_reports(data_dir)
    assert len(loaded) == 2
    assert loaded[0].report_id.startswith("rpt_")
    assert loaded[0].report_id != loaded[1].report_id


def test_duplicate_report_id_rejected(data_dir):
    reports = [make_report("duplicate", "报告甲"), make_report("duplicate", "报告乙")]
    (data_dir / "report.json").write_text(
        json.dumps(reports, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(DataLoadError, match="报告ID冲突"):
        load_reports(data_dir)


def test_invalid_declared_tag_count_rejected(data_dir):
    report = make_report()
    report["尽调报告标签"]["标签数量"] = 99
    (data_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(DataLoadError, match="数据校验失败"):
        load_reports(data_dir)


def test_rebuild_replaces_previous_startup_state(data_dir, tmp_path):
    database = Database(tmp_path / "app.db")
    first = [make_report("first", "报告甲"), make_report("second", "报告乙")]
    (data_dir / "report.json").write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
    database.rebuild(load_reports(data_dir))
    assert database.counts() == (2, 4)

    second = make_report("second", "报告乙-新版本")
    (data_dir / "report.json").write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
    database.rebuild(load_reports(data_dir))
    assert database.counts() == (1, 2)
    assert database.get_report("first") is None
    assert database.get_report("second")["report_name"] == "报告乙-新版本"

