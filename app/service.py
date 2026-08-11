from __future__ import annotations

import re
import uuid
from typing import Any

from app.database import Database
from app.extraction import ExtractionConflict, reconcile_extractions, rule_extract, validated_model_tags
from app.features import FeatureService
from app.llm import Extractor, LLMError
from app.matcher import filter_reports, rank_reports, related_reports
from app.model_manager import ModelManager
from app.schemas import (
    AnswerResult, ChatResponse, ClarificationQuestion, CollectedTag,
    ModelExtraction, StatisticResult,
)
from app.taxonomy import BUSINESS, CUSTOMER, QUESTION_PRIORITY, QUESTION_TEMPLATES, TAG_DIMENSIONS


MAX_CLARIFICATIONS = 5
MIN_CONFIDENCE = 0.5
FLOW_INTENTS = {"recommendation", "filter"}
MODEL_INTENTS = {
    "report_recommendation": "recommendation",
    "report_filter": "filter",
    "report_statistics": "statistics",
    "competition_qa": "qa",
    "unsupported": "unsupported",
}
SKIP_REPLIES = {"跳过", "不知道", "不清楚", "暂不提供", "下一个"}
FINISH_REPLIES = {"按现有信息生成", "直接推荐", "直接筛选", "开始推荐", "开始筛选", "就这些", "生成结果"}
DISCLAIMER = "当前未接入官方比赛资料，回答由大模型生成，仅供参考，请以主办方官方通知为准。"


class UnknownSessionError(ValueError):
    pass


class SessionUserError(ValueError):
    pass


class ReportActionError(ValueError):
    pass


class ChatService:
    def __init__(self, database: Database, extractor: Extractor,
                 model_manager: ModelManager, features: FeatureService,
                 use_model_copy: bool = True):
        self.database = database
        self.extractor = extractor
        self.model_manager = model_manager
        self.features = features
        self.use_model_copy = use_model_copy

    def _session(self, requested: str | None, user_id: str | None) -> str:
        if requested:
            session = self.database.get_session(requested)
            if not session:
                raise UnknownSessionError("session_id 不存在")
            if user_id and session["user_id"] != user_id:
                raise SessionUserError("当前会话不属于该用户")
            return requested
        if not user_id:
            raise SessionUserError("新会话必须提供 user_id")
        session_id = f"ses_{uuid.uuid4().hex}"
        self.database.create_session(session_id, user_id)
        return session_id

    @staticmethod
    def _collected(tags: list[dict[str, Any]]) -> list[CollectedTag]:
        return [CollectedTag.model_validate(tag) for tag in tags]

    def _finish(self, response: ChatResponse) -> ChatResponse:
        message_type = {
            "recommendations": "recommendations", "filter_results": "filter_results",
            "statistics": "statistics", "answer": "answer",
            "needs_clarification": "clarification",
        }.get(response.status, "text")
        self.database.add_message(
            response.session_id, "assistant", response.assistant_message,
            message_type=message_type, request_id=response.request_id,
            payload=response.model_dump(mode="json"), intent=response.intent,
        )
        return response

    @staticmethod
    def _keyword_intent(message: str) -> str | None:
        if re.search(r"多少(篇|份|个)|最多|统计|分布|报告数|标签数", message):
            return "statistics"
        if re.search(r"比赛|参赛|评分|报名|赛程|主办方", message):
            return "qa"
        if re.search(r"筛选|过滤|查找|符合.*条件|有哪些.*报告", message):
            return "filter"
        if re.search(r"推荐|案例|报告", message):
            return "recommendation"
        return None

    @staticmethod
    def _normalize_reply(message: str) -> str:
        return re.sub(r"[\s，。！？,.!?]", "", message)

    async def _extract(self, history: list[dict[str, str]], message: str,
                       expected_tag: str | None, active_intent: str) -> tuple[ModelExtraction, bool]:
        try:
            return await self.extractor.extract(history, message, expected_tag), False
        except LLMError:
            fallback = self._keyword_intent(message)
            if fallback is None and expected_tag and active_intent in FLOW_INTENTS:
                model_intent = "provide_information"
            else:
                reverse = {
                    "recommendation": "report_recommendation", "filter": "report_filter",
                    "statistics": "report_statistics", "qa": "competition_qa",
                }
                model_intent = reverse.get(fallback or "", "unsupported")
            return ModelExtraction(
                intent=model_intent, tags=rule_extract(message, expected_tag)
            ), True

    async def _question_text(self, tag_name: str, fallback: str, examples: list[str]) -> str:
        if not self.use_model_copy:
            return fallback
        return await self.model_manager.generate_question(tag_name, examples, fallback)

    async def _ask_next(self, request_id: str, session_id: str, intent: str) -> ChatResponse:
        tags = self.database.get_session_tags(session_id)
        known = {tag["name"] for tag in tags}
        skipped = self.database.skipped_tags(session_id)
        target = next(
            (name for name in QUESTION_PRIORITY if name not in known and name not in skipped),
            None,
        )
        count = self.database.clarification_count(session_id)
        if target and count < MAX_CLARIFICATIONS:
            fallback, examples = QUESTION_TEMPLATES[target]
            question = await self._question_text(target, fallback, examples)
            self.database.set_clarification(session_id, target)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="needs_clarification", assistant_message=question,
                collected_tags=self._collected(tags),
                question=ClarificationQuestion(
                    tag_name=target, text=question, examples=examples,
                    skippable=True, allow_finish=True,
                ),
            ))
        return self._report_results(request_id, session_id, intent)

    def _report_results(self, request_id: str, session_id: str, intent: str) -> ChatResponse:
        tags = self.database.get_session_tags(session_id)
        reports = self.database.all_reports_with_tags()
        if intent == "filter":
            recommendations = filter_reports(reports, tags)
            status = "filter_results"
            if tags:
                assistant = f"已按全部 {len(tags)} 个确认条件筛选到 {len(recommendations)} 份报告。"
            else:
                assistant = "未应用筛选条件，已按数据完整度返回报告。"
        else:
            recommendations = rank_reports(reports, tags)
            status = "recommendations"
            assistant = (
                "已根据当前信息推荐最匹配的尽调报告。"
                if tags else "未限定条件，已按报告数据完整度推荐优秀案例。"
            )
        dimensions = {tag["dimension"] for tag in tags}
        incomplete = not ({CUSTOMER, BUSINESS} <= dimensions)
        return self._finish(ChatResponse(
            request_id=request_id, session_id=session_id, intent=intent,
            status=status, assistant_message=assistant,
            collected_tags=self._collected(tags), information_incomplete=incomplete,
            recommendations=recommendations,
        ))

    def _related(self, request_id: str, session_id: str, report_id: str) -> ChatResponse:
        if self.database.get_report(report_id) is None:
            raise ReportActionError("关联案例的报告不存在")
        intent = "recommendation"
        self.database.set_session_intent(session_id, intent)
        self.database.add_message(
            session_id, "user", f"查看关联案例：{report_id}",
            message_type="action", request_id=request_id, intent=intent,
        )
        items = related_reports(self.database.all_reports_with_tags(), report_id)
        return self._finish(ChatResponse(
            request_id=request_id, session_id=session_id, intent=intent,
            status="recommendations", assistant_message="已根据该报告的核心标签推荐关联案例。",
            collected_tags=self._collected(self.database.get_session_tags(session_id)),
            recommendations=items,
        ))

    async def chat(self, request_id: str, requested_session: str | None,
                   message: str | None, user_id: str | None = None,
                   action: dict[str, Any] | None = None) -> ChatResponse:
        session_id = self._session(requested_session, user_id)
        if action:
            return self._related(request_id, session_id, action["report_id"])
        assert message is not None
        session = self.database.get_session(session_id) or {}
        active = session.get("active_intent") or "unknown"
        expected_tag = session.get("expected_tag")
        pending_value = session.get("pending_tag_value")
        history = self.database.get_messages(session_id)
        normalized = self._normalize_reply(message)

        is_skip = normalized in SKIP_REPLIES
        is_finish = normalized in FINISH_REPLIES
        if is_skip or is_finish:
            intent = active if active in FLOW_INTENTS else "recommendation"
            extraction = ModelExtraction(intent="provide_information", tags=[])
        else:
            extraction, _fallback_used = await self._extract(history, message, expected_tag, active)
            if extraction.intent == "provide_information":
                intent = active if active in FLOW_INTENTS else (self._keyword_intent(message) or "recommendation")
            else:
                intent = MODEL_INTENTS[extraction.intent]
            keyword = self._keyword_intent(message)
            if intent == "unsupported" and expected_tag and keyword is None and active in FLOW_INTENTS:
                intent = active

        explicit_switch = extraction.intent != "provide_information" and intent != "unsupported"
        if explicit_switch and intent != active:
            self.database.set_session_intent(session_id, intent)
            expected_tag = None
            pending_value = None
        elif intent in FLOW_INTENTS and active in {"unknown", "recommendation"}:
            self.database.set_session_intent(session_id, intent)

        self.database.add_message(
            session_id, "user", message, request_id=request_id,
            message_type="text", intent=intent,
        )

        if intent == "statistics":
            self.database.set_session_intent(session_id, intent)
            assistant, statistic = self.features.statistics_for_question(message)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="statistics", assistant_message=assistant,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
                statistic=StatisticResult.model_validate(statistic),
            ))
        if intent == "qa":
            self.database.set_session_intent(session_id, intent)
            answer = await self.model_manager.answer_competition(history, message)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="answer", assistant_message=answer,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
                answer=AnswerResult(content=answer, disclaimer=DISCLAIMER),
            ))
        if intent == "unsupported":
            assistant = "这个问题暂不属于尽调报告或比赛服务范围。你可以让我推荐、筛选报告，查询数据统计或咨询比赛信息。"
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent="unsupported",
                status="unsupported", assistant_message=assistant,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
            ))

        self.database.set_session_intent(session_id, intent)
        if is_skip and expected_tag:
            self.database.skip_tag(session_id, expected_tag)
            return await self._ask_next(request_id, session_id, intent)
        if is_finish:
            self.database.clear_expected_tag(session_id)
            return self._report_results(request_id, session_id, intent)

        self.database.clear_expected_tag(session_id)
        affirmative = normalized in {"是", "对", "正确", "准确", "确认", "没错", "是的"}
        negative = normalized in {"不是", "不对", "错误", "不准确", "否"}
        confirmed: list[dict[str, Any]] = []
        if expected_tag and pending_value and affirmative:
            confirmed.append({
                "name": expected_tag, "value": pending_value,
                "dimension": TAG_DIMENSIONS[expected_tag], "confidence": 1.0,
            })
        elif expected_tag and pending_value and negative:
            question = f"请直接提供准确的“{expected_tag}”值。"
            self.database.set_clarification(session_id, expected_tag)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="needs_clarification", assistant_message=question,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
                question=ClarificationQuestion(tag_name=expected_tag, text=question, examples=[]),
            ))

        rule_tags = rule_extract(message, expected_tag)
        model_tags = validated_model_tags(extraction.tags, message, expected_tag)
        model_tags = [tag for tag in model_tags if tag.name in TAG_DIMENSIONS and tag.confidence >= MIN_CONFIDENCE]
        extracted, conflicts = reconcile_extractions(rule_tags, model_tags)
        valid = [
            {"name": tag.name, "value": tag.value, "dimension": TAG_DIMENSIONS[tag.name], "confidence": tag.confidence}
            for tag in extracted if tag.name in TAG_DIMENSIONS
        ]
        self.database.upsert_session_tags(session_id, [*valid, *confirmed])
        count = self.database.clarification_count(session_id)
        if conflicts and count < MAX_CLARIFICATIONS:
            conflict: ExtractionConflict = conflicts[0]
            model_value = conflict.model_tag.value if conflict.model_tag else None
            rule_value = conflict.rule_tag.value if conflict.rule_tag else None
            if model_value and rule_value:
                fallback = f"关于“{conflict.name}”，模型判断为“{model_value}”，规则识别为“{rule_value}”。请确认准确值。"
                examples = list(dict.fromkeys([model_value, rule_value]))
            else:
                fallback = f"关于“{conflict.name}”，规则识别为“{rule_value}”。请确认是否准确。"
                examples = [rule_value] if rule_value else []
            question = await self._question_text(conflict.name, fallback, examples)
            pending = examples[0] if len(examples) == 1 else None
            self.database.set_clarification(session_id, conflict.name, pending)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="needs_clarification", assistant_message=question,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
                question=ClarificationQuestion(tag_name=conflict.name, text=question, examples=examples),
            ))
        if conflicts:
            fallback_tags = [item.model_tag for item in conflicts if item.model_tag]
            self.database.upsert_session_tags(session_id, [
                {"name": tag.name, "value": tag.value, "dimension": TAG_DIMENSIONS[tag.name], "confidence": tag.confidence}
                for tag in fallback_tags
            ])

        tags = self.database.get_session_tags(session_id)
        dimensions = {tag["dimension"] for tag in tags}
        ready = {CUSTOMER, BUSINESS} <= dimensions
        if not ready and count < MAX_CLARIFICATIONS:
            return await self._ask_next(request_id, session_id, intent)
        return self._report_results(request_id, session_id, intent)
