from app.extraction import reconcile_extractions, rule_extract
from app.schemas import ExtractedTag


def test_wrong_rule_amount_is_turned_into_confirmation_conflict():
    message = "公司最新一期财报总资产300万元。本次计划申请100万元流动资金贷款"
    rule_tags = rule_extract(message)
    model_tags = [
        ExtractedTag(
            name="授信金额",
            value="100万元",
            evidence="本次计划申请100万元流动资金贷款",
            confidence=0.99,
        )
    ]
    accepted, conflicts = reconcile_extractions(rule_tags, model_tags)
    assert "授信金额" not in {tag.name for tag in accepted}
    amount_conflict = next(item for item in conflicts if item.name == "授信金额")
    assert amount_conflict.model_tag.value == "100万元"
    assert amount_conflict.rule_tag.value == "300万元"
