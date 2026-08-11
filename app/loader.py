from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.schemas import SourceReport


class DataLoadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LoadedReport:
    report_id: str
    source_file: str
    report: SourceReport


def _generated_id(report: SourceReport) -> str:
    name = re.sub(r"\s+", "", report.summary.report_name).lower()
    kind = re.sub(r"\s+", "", report.summary.report_type).lower()
    digest = hashlib.sha256(f"{name}|{kind}".encode("utf-8")).hexdigest()[:24]
    return f"rpt_{digest}"


def load_reports(data_dir: Path) -> list[LoadedReport]:
    if not data_dir.is_dir():
        raise DataLoadError(f"数据目录不存在：{data_dir}")

    paths = sorted(data_dir.rglob("*.json"))
    if not paths:
        raise DataLoadError(f"数据目录中没有 JSON 文件：{data_dir}")

    loaded: list[LoadedReport] = []
    seen_ids: dict[str, str] = {}
    for path in paths:
        relative = path.relative_to(data_dir).as_posix()
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataLoadError(f"无法读取 {relative}：{exc}") from exc

        items = raw if isinstance(raw, list) else [raw]
        if not items:
            raise DataLoadError(f"{relative} 不包含报告")
        for index, item in enumerate(items):
            try:
                report = SourceReport.model_validate(item)
            except ValidationError as exc:
                raise DataLoadError(f"{relative}[{index}] 数据校验失败：{exc}") from exc
            report_id = report.report_id or _generated_id(report)
            location = f"{relative}[{index}]"
            if report_id in seen_ids:
                raise DataLoadError(
                    f"报告ID冲突：{report_id} 同时出现在 {seen_ids[report_id]} 和 {location}"
                )
            seen_ids[report_id] = location
            loaded.append(LoadedReport(report_id, relative, report))
    return loaded

