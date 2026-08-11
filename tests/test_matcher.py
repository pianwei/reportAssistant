from app.matcher import rank_reports, tag_similarity


def test_amount_point_matches_range():
    assert tag_similarity("授信金额", "300万元", "100万-500万元") == 1.0
    assert tag_similarity("授信金额", "800万元", "100万-500万元") == 0.0


def test_enterprise_size_matches_non_normalized_labels_without_cross_matching():
    assert tag_similarity("企业规模", "小微企业", "小微（初创成长期，员工20余人）") == 1.0
    assert tag_similarity("企业规模", "小微企业", "小型企业（参保5-15人）") == 1.0
    assert tag_similarity("企业规模", "小微企业", "未明示，初步判断为中型企业") == 0.0
    assert tag_similarity("企业规模", "大型企业", "中型企业") == 0.0
    assert tag_similarity("企业规模", "小微企业", "中型企业/小型") == 0.7


def test_non_normalized_boolean_and_enum_labels():
    assert tag_similarity("是否科技型企业", "是", "国家高新技术企业、专精特新") == 1.0
    assert tag_similarity("是否科技型企业", "科技企业", "否（未取得相关资质）") == 0.0
    assert tag_similarity("是否集团客户", "是", "纳入母集团统一授信管理") == 1.0
    assert tag_similarity("授信品种", "流贷", "企业流动资金贷款（担保快贷）") == 1.0
    assert tag_similarity("担保方式", "保证担保", "担保机构担保+实际控制人个人保证") == 1.0
    assert tag_similarity("申请性质", "新增授信", "首贷") == 1.0
    assert tag_similarity("所有制性质", "民营企业", "自然人实际控制的私营企业") == 1.0


def test_non_normalized_text_and_open_amount_ranges():
    assert tag_similarity("行业分类", "科学研究和技术服务业", "科技服务（研发咨询）") >= 0.9
    assert tag_similarity("贷款用途", "设备购置", "用于生产线设备采购及安装") >= 0.9
    assert tag_similarity("授信金额", "大于200万元", "100万-500万元") >= 0.55
    assert tag_similarity("授信金额", "超过200万元", "100万元以内") == 0.0


def test_rank_is_stable_and_explainable():
    reports = [
        {
            "report_id": "b",
            "report_name": "乙报告",
            "report_type": "类型",
            "summary": {},
            "tags": [{"name": "行业分类", "value": "制造业"}],
        },
        {
            "report_id": "a",
            "report_name": "甲报告",
            "report_type": "类型",
            "summary": {},
            "tags": [{"name": "行业分类", "value": "科学研究和技术服务业"}],
        },
    ]
    result = rank_reports(
        reports,
        [{"name": "行业分类", "value": "科学研究和技术服务业"}],
    )
    assert result[0].report_id == "a"
    assert result[0].score == 100
    assert result[0].matched_tags[0].name == "行业分类"
