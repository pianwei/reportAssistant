from __future__ import annotations

CUSTOMER = "客户维度"
BUSINESS = "业务维度"

TAG_DIMENSIONS: dict[str, str] = {
    "行业分类": CUSTOMER,
    "企业规模": CUSTOMER,
    "主营业务": CUSTOMER,
    "最新一期财报总资产": CUSTOMER,
    "最新一期财报总负债": CUSTOMER,
    "最新一期财报净利润": CUSTOMER,
    "最新一期经营性净现金流": CUSTOMER,
    "是否集团客户": CUSTOMER,
    "是否科技型企业": CUSTOMER,
    "所有制性质": CUSTOMER,
    "授信金额": BUSINESS,
    "授信期限": BUSINESS,
    "授信品种": BUSINESS,
    "担保方式": BUSINESS,
    "担保人": BUSINESS,
    "担保物": BUSINESS,
    "贷款用途": BUSINESS,
    "还款来源": BUSINESS,
    "申请性质": BUSINESS,
    "是否我行关联企业": BUSINESS,
}

QUESTION_TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "行业分类": ("客户所属什么行业？", ["科学研究和技术服务业", "制造业"]),
    "主营业务": ("客户的主营业务是什么？", ["室内空气治理", "汽车零部件生产"]),
    "企业规模": ("客户的企业规模如何？", ["小微企业", "中型企业"]),
    "授信品种": ("本次希望申请什么授信品种？", ["流动资金贷款", "订单融资"]),
    "授信金额": ("本次计划申请多少授信金额？", ["300万元", "100万至500万元"]),
    "担保方式": ("计划采用什么担保方式？", ["保证担保", "抵押担保"]),
    "贷款用途": ("贷款资金主要用于什么用途？", ["采购设备", "日常经营周转"]),
    "申请性质": ("本次申请是新增、续贷还是调整授信？", ["续贷", "新增授信"]),
}

QUESTION_PRIORITY = tuple(QUESTION_TEMPLATES)

TAG_WEIGHTS: dict[str, float] = {
    "行业分类": 2.0,
    "主营业务": 2.0,
    "授信品种": 2.0,
    "授信金额": 2.0,
    "企业规模": 1.2,
    "担保方式": 1.2,
    "贷款用途": 1.2,
    "申请性质": 1.2,
}

