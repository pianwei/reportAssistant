from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceTag(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    dimension: str = Field(alias="维度类别", min_length=1)
    name: str = Field(alias="标签名称", min_length=1)
    value: str = Field(alias="提取结果", min_length=1)
    source_text: str = Field(default="", alias="原文出处")
    completeness: str = Field(default="", alias="是否提供完整数据")
    note: str = Field(default="", alias="备注")


class SourceTagCollection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    declared_count: int = Field(alias="标签数量", ge=0)
    tags: list[SourceTag] = Field(alias="提取结果")

    @model_validator(mode="after")
    def count_must_match(self) -> "SourceTagCollection":
        if self.declared_count != len(self.tags):
            raise ValueError(
                f"标签数量声明为 {self.declared_count}，实际为 {len(self.tags)}"
            )
        return self


class SourceSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    report_name: str = Field(alias="报告名称", min_length=1)
    report_type: str = Field(alias="报告类型", min_length=1)
    customer_overview: str = Field(alias="客户概况")
    business_overview: str = Field(alias="主营业务与经营")
    financial_overview: str = Field(alias="财务概况")
    credit_plan: str = Field(alias="授信方案")
    guarantee_and_repayment: str = Field(alias="担保与还款")
    main_risks: list[str] = Field(alias="主要风险")
    overall_assessment: str = Field(alias="综合评价")


class SourceReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    report_id: str | None = Field(default=None, alias="报告ID")
    summary: SourceSummary = Field(alias="尽调报告综述")
    tag_collection: SourceTagCollection = Field(alias="尽调报告标签")

    @field_validator("report_id")
    @classmethod
    def clean_report_id(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None


class ExtractedTag(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)


class ModelExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal[
        "report_recommendation", "report_filter", "report_statistics",
        "competition_qa", "provide_information", "unsupported",
    ]
    tags: list[ExtractedTag] = Field(default_factory=list)
    statistic_query: str | None = None


class ChatAction(BaseModel):
    type: Literal["related_reports"]
    report_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ChatAction":
        return self


class ChatRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1, max_length=64)
    # The field is part of every chat request. An empty value starts a new
    # session; a non-empty value continues an existing session.
    session_id: str | None = Field(max_length=64)
    message: str | None = Field(default=None, max_length=10000)
    action: ChatAction | None = None

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("message 不能为空")
        return value

    @model_validator(mode="after")
    def message_or_action_required(self) -> "ChatRequest":
        if self.message is None and self.action is None:
            raise ValueError("message 和 action 至少提供一项")
        return self


class CollectedTag(BaseModel):
    name: str
    value: str
    dimension: str
    confidence: float


class ClarificationQuestion(BaseModel):
    tag_name: str
    text: str
    examples: list[str]
    skippable: bool = True
    allow_finish: bool = True


class StatisticBreakdown(BaseModel):
    label: str
    count: int


class StatisticReport(BaseModel):
    report_id: str
    report_name: str
    report_type: str


class StatisticResult(BaseModel):
    metric: str
    title: str
    value: int | float | str
    breakdown: list[StatisticBreakdown] = Field(default_factory=list)
    reports: list[StatisticReport] = Field(default_factory=list)


class AnswerResult(BaseModel):
    content: str
    source: Literal["model"] = "model"
    official: bool = False
    disclaimer: str


class MatchDetail(BaseModel):
    name: str
    query_value: str
    report_value: str | None = None
    similarity: float = Field(ge=0, le=1)


class ReportTagInfo(BaseModel):
    name: str
    value: str

    @field_validator("value", mode="before")
    @classmethod
    def empty_value_as_dash(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        return normalized or "—"


class Recommendation(BaseModel):
    report_id: str
    report_name: str
    report_type: str
    score: float = Field(ge=0, le=100)
    recommendation_reason: str = ""
    matched_tags: list[MatchDetail]
    unmatched_tags: list[MatchDetail]
    missing_tags: list[str]
    report_tags: list[ReportTagInfo] = Field(default_factory=list)
    summary: dict[str, Any]


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    intent: Literal["recommendation", "filter", "statistics", "qa", "greeting", "unsupported"]
    status: Literal[
        "needs_clarification", "recommendations", "filter_results",
        "statistics", "answer", "greeting", "unsupported", "error",
    ]
    assistant_message: str
    collected_tags: list[CollectedTag]
    information_incomplete: bool = False
    question: ClarificationQuestion | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    statistic: StatisticResult | None = None
    answer: AnswerResult | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorBody


class SuggestionsRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    session_id: str | None = None
    previous_batch_id: str | None = None


class SuggestionItem(BaseModel):
    text: str
    intent: Literal["recommendation", "filter", "statistics", "qa"]


class ModelProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str = "OpenAI兼容"
    base_url: str = Field(min_length=8)
    model: str = Field(min_length=1)
    api_key: str = ""
    timeout_seconds: float = Field(default=30, ge=1, le=600)
    json_mode: bool = True
    disable_thinking: bool = False


class ModelProfileUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    timeout_seconds: float | None = Field(default=None, ge=1, le=600)
    json_mode: bool | None = None
    disable_thinking: bool | None = None
