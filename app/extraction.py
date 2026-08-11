from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import ExtractedTag


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class ExtractionConflict:
    name: str
    model_tag: ExtractedTag | None
    rule_tag: ExtractedTag | None


def _pattern(values: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(sorted((re.escape(v) for v in values), key=len, reverse=True)))


RULES = [
    Rule("行业分类", _pattern([
        "科学研究和技术服务业", "信息传输、软件和信息技术服务业", "租赁和商务服务业",
        "农、林、牧、渔业", "批发和零售业", "住宿和餐饮业", "建筑业", "制造业",
        "采矿业", "房地产业", "金融业", "教育业", "卫生和社会工作", "交通运输业",
    ])),
    Rule("企业规模", _pattern(["微型企业", "小微企业", "小型企业", "中型企业", "大型企业"])),
    Rule("授信品种", _pattern([
        "流动资金贷款", "固定资产贷款", "订单融资", "银行承兑汇票", "保理融资",
        "供应链融资", "贸易融资", "信用证", "经营贷",
    ])),
    Rule("申请性质", _pattern(["存量续授信", "新增授信", "续授信", "续贷", "新增", "调整授信"])),
    Rule("担保方式", _pattern(["抵押担保", "质押担保", "保证担保", "信用担保", "信用方式"])),
]

AMOUNT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万|亿)\s*(?:元)?(?:\s*[-至到~～]\s*\d+(?:\.\d+)?\s*(?:万|亿)\s*(?:元)?)?")
TERM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:年|个月|月|天)")
AMOUNT_CONTEXT = ("申请", "授信", "贷款", "额度", "融资")
TERM_CONTEXT = ("期限", "授信", "贷款")


def _context(message: str, start: int, end: int, radius: int = 12) -> str:
    return message[max(0, start - radius) : min(len(message), end + radius)]


def rule_extract(message: str, expected_tag: str | None = None) -> list[ExtractedTag]:
    found: dict[str, ExtractedTag] = {}
    for rule in RULES:
        if expected_tag and rule.name != expected_tag:
            continue
        match = rule.pattern.search(message)
        if match:
            found[rule.name] = ExtractedTag(
                name=rule.name,
                value=match.group(0),
                evidence=_context(message, match.start(), match.end()),
                confidence=1.0,
            )

    if not expected_tag or expected_tag == "授信金额":
        for match in AMOUNT_RE.finditer(message):
            evidence = _context(message, match.start(), match.end())
            if expected_tag == "授信金额" or any(word in evidence for word in AMOUNT_CONTEXT):
                found["授信金额"] = ExtractedTag(
                    name="授信金额", value=match.group(0), evidence=evidence, confidence=1.0
                )
                break

    if not expected_tag or expected_tag == "授信期限":
        for match in TERM_RE.finditer(message):
            evidence = _context(message, match.start(), match.end())
            if expected_tag == "授信期限" or any(word in evidence for word in TERM_CONTEXT):
                found["授信期限"] = ExtractedTag(
                    name="授信期限", value=match.group(0), evidence=evidence, confidence=1.0
                )
                break
    return list(found.values())


REQUIRED_ANCHORS: dict[str, tuple[str, ...]] = {
    "最新一期财报总资产": ("总资产",),
    "最新一期财报总负债": ("总负债",),
    "最新一期财报净利润": ("净利润",),
    "最新一期经营性净现金流": ("经营性净现金流", "经营现金流"),
}


def validated_model_tags(
    tags: list[ExtractedTag], message: str, expected_tag: str | None = None
) -> list[ExtractedTag]:
    valid: list[ExtractedTag] = []
    for tag in tags:
        if expected_tag and tag.name != expected_tag:
            continue
        if tag.evidence not in message or tag.value not in tag.evidence:
            continue
        anchors = REQUIRED_ANCHORS.get(tag.name)
        if anchors and not any(anchor in tag.evidence for anchor in anchors):
            continue
        if tag.name == "授信金额" and expected_tag != "授信金额":
            if not any(word in tag.evidence for word in AMOUNT_CONTEXT):
                continue
        valid.append(tag)
    return valid


def _equivalent(left: str, right: str) -> bool:
    def normalized(value: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]", "", value.lower()).replace("元", "")

    a, b = normalized(left), normalized(right)
    return bool(a and b and (a == b or a in b or b in a))


def reconcile_extractions(
    rule_tags: list[ExtractedTag], model_tags: list[ExtractedTag]
) -> tuple[list[ExtractedTag], list[ExtractionConflict]]:
    """以模型为主判；规则与模型不一致或规则独有时进入人工确认。"""
    rules = {tag.name: tag for tag in rule_tags}
    models = {tag.name: tag for tag in model_tags}
    accepted: list[ExtractedTag] = []
    conflicts: list[ExtractionConflict] = []

    for name in sorted(set(rules) | set(models)):
        model_tag = models.get(name)
        rule_tag = rules.get(name)
        if model_tag is None:
            conflicts.append(ExtractionConflict(name, None, rule_tag))
        elif rule_tag is not None and not _equivalent(model_tag.value, rule_tag.value):
            conflicts.append(ExtractionConflict(name, model_tag, rule_tag))
        else:
            accepted.append(model_tag)
    return accepted, conflicts
