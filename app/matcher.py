from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas import MatchDetail, Recommendation
from app.taxonomy import TAG_WEIGHTS


AMOUNT_TAG = "授信金额"
TEXT_TAGS = {"主营业务", "贷款用途", "还款来源", "担保人", "担保物"}
UNAVAILABLE_MARKERS = ("不可提取", "未披露", "未知", "不清楚")

SYNONYMS = {
    "小微企业": "小型企业",
    "小微": "小型企业",
    "科技企业": "科技型企业",
    "续作": "续贷",
    "流贷": "流动资金贷款",
    "保证": "保证担保",
    "抵押": "抵押担保",
}


def normalize(value: str) -> str:
    value = value.lower().strip()
    for source, target in SYNONYMS.items():
        value = value.replace(source, target)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", value)


def _ngrams(value: str, size: int = 2) -> set[str]:
    if len(value) < size:
        return {value} if value else set()
    return {value[i : i + size] for i in range(len(value) - size + 1)}


def _text_similarity(left: str, right: str) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # A short, explicit phrase is a strong match when it occurs verbatim in a
    # longer report tag (for example "设备采购" in a detailed loan-purpose tag).
    containment = 0.9 if a in b or b in a else 0.0
    grams_a, grams_b = _ngrams(a), _ngrams(b)
    union = grams_a | grams_b
    jaccard = len(grams_a & grams_b) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    return min(1.0, max(containment, jaccard * 0.7 + sequence * 0.3))


def _amounts_in_ten_thousands(value: str) -> tuple[float, float] | None:
    if any(marker in value for marker in UNAVAILABLE_MARKERS):
        return None
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(亿|万)?", value.replace(",", ""))
    if not matches:
        return None
    numbers = [float(number) * (10000 if unit == "亿" else 1) for number, unit in matches]
    if "以下" in value or "以内" in value:
        return 0.0, numbers[0]
    if "以上" in value:
        return numbers[0], float("inf")
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[:2]), max(numbers[:2])


def _amount_similarity(left: str, right: str) -> float:
    a, b = _amounts_in_ten_thousands(left), _amounts_in_ten_thousands(right)
    if a is None or b is None:
        return 0.0
    a_low, a_high = a
    b_low, b_high = b
    if a_high == a_low:
        return 1.0 if b_low <= a_low <= b_high else 0.0
    if b_high == b_low:
        return 1.0 if a_low <= b_low <= a_high else 0.0
    if a_high == float("inf") and b_high == float("inf"):
        return 1.0
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    finite_high = max(x for x in (a_high, b_high) if x != float("inf"))
    union = max(finite_high, a_low, b_low) - min(a_low, b_low)
    return min(1.0, overlap / union) if union > 0 else 1.0


def tag_similarity(name: str, query: str, report: str) -> float:
    if any(marker in report for marker in UNAVAILABLE_MARKERS):
        return 0.0
    if name == AMOUNT_TAG:
        return _amount_similarity(query, report)
    similarity = _text_similarity(query, report)
    if name not in TEXT_TAGS:
        a, b = normalize(query), normalize(report)
        if a and (a in b or b in a):
            return max(similarity, 0.85)
    return similarity


def rank_reports(
    reports: list[dict[str, Any]], query_tags: list[dict[str, Any]], limit: int = 3
) -> list[Recommendation]:
    results: list[Recommendation] = []
    if not query_tags:
        for report in reports:
            tags = report.get("tags", [])
            valid_tags = sum(
                tag.get("completeness") == "是"
                and not any(marker in tag.get("value", "") for marker in UNAVAILABLE_MARKERS)
                for tag in tags
            )
            tag_score = valid_tags / len(tags) if tags else 0.0
            summary_values = list(report.get("summary", {}).values())
            valid_summary = sum(bool(value) for value in summary_values)
            summary_score = valid_summary / len(summary_values) if summary_values else 0.0
            score = round((tag_score * 0.7 + summary_score * 0.3) * 100, 2)
            results.append(Recommendation(
                report_id=report["report_id"], report_name=report["report_name"],
                report_type=report["report_type"], score=score,
                recommendation_reason="未限定条件，按报告标签与综述数据完整度推荐。",
                matched_tags=[], unmatched_tags=[], missing_tags=[], summary=report["summary"],
            ))
        results.sort(key=lambda item: (-item.score, item.report_name, item.report_id))
        return results[:limit]
    total_weight = sum(TAG_WEIGHTS.get(tag["name"], 1.0) for tag in query_tags) or 1.0
    for report in reports:
        report_tags = {tag["name"]: tag["value"] for tag in report["tags"]}
        matched: list[MatchDetail] = []
        unmatched: list[MatchDetail] = []
        missing: list[str] = []
        weighted_score = 0.0
        for query in query_tags:
            name, value = query["name"], query["value"]
            report_value = report_tags.get(name)
            if report_value is None:
                missing.append(name)
                continue
            similarity = tag_similarity(name, value, report_value)
            detail = MatchDetail(
                name=name,
                query_value=value,
                report_value=report_value,
                similarity=round(similarity, 4),
            )
            if similarity >= 0.55:
                matched.append(detail)
            else:
                unmatched.append(detail)
            weighted_score += TAG_WEIGHTS.get(name, 1.0) * similarity
        results.append(
            Recommendation(
                report_id=report["report_id"],
                report_name=report["report_name"],
                report_type=report["report_type"],
                score=round(weighted_score / total_weight * 100, 2),
                recommendation_reason=(
                    "与您的" + "、".join(item.name for item in matched[:3]) + "等条件匹配。"
                    if matched else "根据当前已提供信息返回的相近案例，建议结合详情人工复核。"
                ),
                matched_tags=matched,
                unmatched_tags=unmatched,
                missing_tags=missing,
                summary=report["summary"],
            )
        )
    results.sort(key=lambda item: (-item.score, -len(item.matched_tags), item.report_name, item.report_id))
    return results[:limit]


def filter_reports(
    reports: list[dict[str, Any]], query_tags: list[dict[str, Any]], limit: int = 3
) -> list[Recommendation]:
    if not query_tags:
        return rank_reports(reports, [], limit)
    ranked = rank_reports(reports, query_tags, max(len(reports), limit))
    matched = [
        item for item in ranked
        if not item.unmatched_tags and not item.missing_tags
        and len(item.matched_tags) == len(query_tags)
    ]
    for item in matched:
        item.recommendation_reason = "满足全部已确认筛选条件：" + "、".join(
            detail.name for detail in item.matched_tags
        ) + "。"
    return matched[:limit]


def related_reports(
    reports: list[dict[str, Any]], source_report_id: str, limit: int = 3
) -> list[Recommendation]:
    source = next((report for report in reports if report["report_id"] == source_report_id), None)
    if source is None:
        return []
    queries = [
        {"name": tag["name"], "value": tag["value"]}
        for tag in source.get("tags", [])
        if tag["name"] in TAG_WEIGHTS
        and not any(marker in tag["value"] for marker in UNAVAILABLE_MARKERS)
    ]
    candidates = [report for report in reports if report["report_id"] != source_report_id]
    return rank_reports(candidates, queries, limit)
