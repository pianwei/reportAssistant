from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas import MatchDetail, Recommendation
from app.taxonomy import TAG_WEIGHTS


AMOUNT_TAGS = {
    "授信金额", "最新一期财报总资产", "最新一期财报总负债",
    "最新一期财报净利润", "最新一期经营性净现金流",
}
TEXT_TAGS = {"行业分类", "主营业务", "贷款用途", "还款来源", "担保人", "担保物"}
BOOLEAN_TAGS = {"是否集团客户", "是否科技型企业", "是否我行关联企业"}
UNAVAILABLE_MARKERS = ("不可提取", "未披露", "未知", "不清楚")

SYNONYMS = {
    "小微企业": "小型企业",
    "小微": "小型企业",
    "科技企业": "科技型企业",
    "续作": "续贷",
    "流贷": "流动资金贷款",
    "保证": "保证担保",
    "抵押": "抵押担保",
    "科学研究和技术服务业": "科技服务业",
    "科学研究与技术服务业": "科技服务业",
    "科技服务": "科技服务业",
    "设备购置": "设备采购",
    "购置设备": "设备采购",
    "采购原料": "原材料采购",
    "流动资金周转": "日常经营周转",
    "补充流动资金": "日常经营周转",
    "补流": "日常经营周转",
}

CONCEPT_MARKERS: dict[str, dict[str, tuple[str, ...]]] = {
    "授信品种": {
        "流动资金贷款": ("流动资金贷款", "流贷", "经营贷"),
        "固定资产贷款": ("固定资产贷款", "固贷", "项目贷款"),
        "银行承兑汇票": ("银行承兑汇票", "银承", "承兑汇票"),
        "信用证": ("信用证",),
        "保函": ("保函",),
        "订单融资": ("订单融资", "订单贷"),
        "票据贴现": ("票据贴现", "贴现"),
    },
    "担保方式": {
        "信用": ("信用", "免担保", "无担保"),
        "保证": ("保证", "担保机构担保", "个人担保"),
        "抵押": ("抵押",),
        "质押": ("质押",),
    },
    "申请性质": {
        "新增": ("新增", "新授信", "首贷", "首次申请"),
        "续贷": ("续贷", "续作", "借新还旧"),
        "调整": ("调整", "变更", "额度调整"),
    },
    "所有制性质": {
        "民营": ("民营", "私营", "自然人控股", "自然人实际控制"),
        "国有": ("国有", "国企", "国资", "政府实际控制"),
        "外资": ("外资", "外商投资"),
        "集体": ("集体所有", "集体企业"),
    },
}

_SYNONYM_PATTERN = re.compile(
    "|".join(re.escape(source) for source in sorted(SYNONYMS, key=len, reverse=True))
)


def normalize(value: str) -> str:
    value = value.lower().strip()
    # Apply synonyms in one pass so a replacement cannot be rewritten again
    # (for example 科技服务 -> 科技服务业 -> 科技服务业业).
    value = _SYNONYM_PATTERN.sub(lambda match: SYNONYMS[match.group(0)], value)
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
    if any(marker in value for marker in ("以下", "以内", "小于", "低于", "不超过")):
        return 0.0, numbers[0]
    if any(marker in value for marker in ("以上", "大于", "高于", "超过", "不少于")):
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


def _enterprise_size_classes(value: str) -> set[str]:
    classes: set[str] = set()
    if any(marker in value for marker in ("小微", "微型", "小型")):
        classes.add("small")
    if "中型" in value:
        classes.add("medium")
    if "大型" in value:
        classes.add("large")
    return classes


def _boolean_value(name: str, value: str) -> bool | None:
    normalized = normalize(value)
    if not normalized:
        return None
    if normalized.startswith("否") or normalized.startswith("非"):
        return False
    if any(marker in normalized for marker in ("不属于", "未纳入", "无关联")):
        return False
    if normalized.startswith("是"):
        return True
    positive_markers = {
        "是否科技型企业": ("科技型企业", "高新技术企业", "专精特新", "科技企业"),
        "是否集团客户": ("集团客户", "集团统一授信", "隶属于集团", "纳入集团"),
        "是否我行关联企业": ("我行关联企业", "本行关联企业"),
    }
    if any(marker in normalized for marker in positive_markers.get(name, ())):
        return True
    return None


def _concepts(name: str, value: str) -> set[str]:
    normalized = normalize(value)
    return {
        concept
        for concept, markers in CONCEPT_MARKERS.get(name, {}).items()
        if any(normalize(marker) in normalized for marker in markers)
    }


def _enum_similarity(name: str, query: str, report: str) -> float:
    if name == "企业规模":
        query_classes = _enterprise_size_classes(query)
        report_classes = _enterprise_size_classes(report)
        if not query_classes or not report_classes or not (query_classes & report_classes):
            return 0.0
        # A report containing conflicting size labels remains usable but gets
        # a lower score than one with a single, unambiguous classification.
        return 1.0 if len(report_classes) == 1 else 0.7
    if name in BOOLEAN_TAGS:
        query_value = _boolean_value(name, query)
        report_value = _boolean_value(name, report)
        if query_value is not None and report_value is not None:
            return 1.0 if query_value == report_value else 0.0
    query_concepts = _concepts(name, query)
    report_concepts = _concepts(name, report)
    if query_concepts:
        if not report_concepts:
            return 0.0
        overlap = query_concepts & report_concepts
        return len(overlap) / len(query_concepts) if overlap else 0.0
    a, b = normalize(query), normalize(report)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Exact containment tolerates explanatory suffixes while still preventing
    # fuzzy mistakes such as 大型企业 matching 中型企业.
    return 0.9 if a in b or b in a else 0.0


def tag_similarity(name: str, query: str, report: str) -> float:
    if any(marker in report for marker in UNAVAILABLE_MARKERS):
        return 0.0
    if name in AMOUNT_TAGS:
        return _amount_similarity(query, report)
    if name not in TEXT_TAGS:
        return _enum_similarity(name, query, report)
    return _text_similarity(query, report)


def rank_reports(
    reports: list[dict[str, Any]], query_tags: list[dict[str, Any]], limit: int | None = 3
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
                report_tags=report.get("tags", []),
            ))
        results.sort(key=lambda item: (-item.score, item.report_name, item.report_id))
        return results if limit is None else results[:limit]
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
                report_tags=report.get("tags", []),
                summary=report["summary"],
            )
        )
    results.sort(key=lambda item: (-item.score, -len(item.matched_tags), item.report_name, item.report_id))
    return results if limit is None else results[:limit]


def filter_reports(
    reports: list[dict[str, Any]], query_tags: list[dict[str, Any]], limit: int | None = None
) -> list[Recommendation]:
    if not query_tags:
        return rank_reports(reports, [], limit)
    ranked = rank_reports(reports, query_tags, None)
    matched = [
        item for item in ranked
        if not item.unmatched_tags and not item.missing_tags
        and len(item.matched_tags) == len(query_tags)
    ]
    for item in matched:
        item.recommendation_reason = "满足全部已确认筛选条件：" + "、".join(
            detail.name for detail in item.matched_tags
        ) + "。"
    return matched if limit is None else matched[:limit]


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
