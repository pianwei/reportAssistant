from app.extraction import reconcile_extractions, rule_extract
from app.schemas import ExtractedTag


def test_rule_amount_uses_nearest_credit_context():
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
    assert {tag.name: tag.value for tag in accepted}["授信金额"] == "100万元"
    assert "最新一期财报总资产" in {item.name for item in conflicts}
