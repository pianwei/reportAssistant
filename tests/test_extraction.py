from app.extraction import reconcile_extractions, rule_extract, validated_model_tags
from app.schemas import ExtractedTag


def test_rules_extract_high_confidence_structured_tags():
    tags = rule_extract(
        "科学研究和技术服务业小微企业申请300万元流动资金贷款，采用保证担保并续贷"
    )
    by_name = {tag.name: tag for tag in tags}
    assert by_name["行业分类"].value == "科学研究和技术服务业"
    assert by_name["企业规模"].value == "小微企业"
    assert by_name["授信金额"].value == "300万元"
    assert by_name["授信品种"].value == "流动资金贷款"
    assert by_name["担保方式"].value == "保证担保"
    assert by_name["申请性质"].value == "续贷"


def test_amount_requires_credit_context_unless_expected():
    assert rule_extract("公司总资产300万元") == []
    expected = rule_extract("300万元", expected_tag="授信金额")
    assert expected[0].name == "授信金额"


def test_model_evidence_and_semantic_anchors_are_enforced():
    message = "本次申请300万元流动资金贷款"
    wrong = ExtractedTag(
        name="最新一期财报总资产",
        value="300万元",
        evidence="申请300万元",
        confidence=0.99,
    )
    invented = ExtractedTag(
        name="行业分类",
        value="制造业",
        evidence="制造业",
        confidence=0.99,
    )
    correct = ExtractedTag(
        name="授信金额",
        value="300万元",
        evidence="申请300万元",
        confidence=0.99,
    )
    assert validated_model_tags([wrong, invented, correct], message) == [correct]


def test_expected_tag_filters_other_valid_tags():
    message = "小微企业，300万元"
    tags = [
        ExtractedTag(name="企业规模", value="小微企业", evidence="小微企业", confidence=1),
        ExtractedTag(name="授信金额", value="300万元", evidence="300万元", confidence=1),
    ]
    result = validated_model_tags(tags, message, expected_tag="企业规模")
    assert [tag.name for tag in result] == ["企业规模"]


def test_model_is_authoritative_when_rule_agrees_or_is_absent():
    model_only = ExtractedTag(
        name="主营业务", value="环境治理", evidence="主营环境治理", confidence=0.9
    )
    agreed_model = ExtractedTag(
        name="授信金额", value="300万元", evidence="申请300万元", confidence=0.9
    )
    agreed_rule = ExtractedTag(
        name="授信金额", value="300万", evidence="申请300万", confidence=1
    )
    accepted, conflicts = reconcile_extractions(
        [agreed_rule], [model_only, agreed_model]
    )
    assert {tag.name: tag.value for tag in accepted} == {
        "主营业务": "环境治理",
        "授信金额": "300万元",
    }
    assert conflicts == []


def test_rule_only_or_disagreement_becomes_conflict():
    model = ExtractedTag(
        name="授信金额", value="100万元", evidence="申请100万元", confidence=0.99
    )
    rule = ExtractedTag(
        name="授信金额", value="300万元", evidence="总资产300万元", confidence=1
    )
    rule_only = ExtractedTag(
        name="企业规模", value="小微企业", evidence="小微企业", confidence=1
    )
    accepted, conflicts = reconcile_extractions([rule, rule_only], [model])
    assert accepted == []
    assert {item.name for item in conflicts} == {"授信金额", "企业规模"}
