from app.matcher import rank_reports, tag_similarity


def test_amount_point_matches_range():
    assert tag_similarity("授信金额", "300万元", "100万-500万元") == 1.0
    assert tag_similarity("授信金额", "800万元", "100万-500万元") == 0.0


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

