from __future__ import annotations

import re
import uuid
from typing import Any

from app.database import Database
from app.extraction import reconcile_extractions, rule_extract, validated_model_tags
from app.features import FeatureService
from app.llm import Extractor, LLMError
from app.matcher import filter_reports, rank_reports, related_reports
from app.model_manager import ModelManager
from app.schemas import (
    AnswerResult, ChatResponse, CollectedTag, ModelExtraction, StatisticResult,
)
from app.taxonomy import BUSINESS, CUSTOMER, TAG_DIMENSIONS


MIN_CONFIDENCE = 0.5
FLOW_INTENTS = {"recommendation", "filter"}
MODEL_INTENTS = {
    "report_recommendation": "recommendation",
    "report_filter": "filter",
    "report_statistics": "statistics",
    "competition_qa": "qa",
    "unsupported": "unsupported",
}
DISCLAIMER = "当前未接入官方比赛资料，回答由大模型生成，仅供参考，请以主办方官方通知为准。"
GREETING = "您好，我是尽调报告助手。您可以让我推荐或筛选尽调报告、查询报告数据统计，或咨询比赛相关问题。"
OUT_OF_SCOPE = "抱歉，这个问题超出了我目前的回答范围。我可以帮助您推荐或筛选尽调报告、查询报告数据统计，以及解答比赛相关问题。"


class UnknownSessionError(ValueError):
    pass


class SessionUserError(ValueError):
    pass


class ReportActionError(ValueError):
    pass


class ChatService:
    def __init__(self, database: Database, extractor: Extractor,
                 model_manager: ModelManager, features: FeatureService):
        self.database = database
        self.extractor = extractor
        self.model_manager = model_manager
        self.features = features

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
        if re.search(
            r"多少(?:篇|份|个|家|条|类|种)|"
            r"(?:有|共|共有|一共|总共)几(?:篇|份|个|家|条|类|种)|"
            r"几(?:篇|份|家|条|类|种)|几个(?:行业|类型|标签)|"
            r"统计|汇总|合计|数量|总数|分布|占比|比例|平均|均值|中位数|"
            r"最多|最少|最高|最低|最大|最小|排名|排行|前\s*\d+|"
            r"哪(?:个|类|种).{0,8}最|报告数|标签数",
            message,
        ):
            return "statistics"
        if not re.search(r"筛选|过滤|查找|找出|检索|列出", message) and re.search(
            r"哪些.*报告|哪几(?:篇|份).*报告|有(?:哪些|哪几).*报告|"
            r"报告.*(?:哪些|有哪些|哪几)|报告有哪些|"
            r"(?:大于|超过|高于|不少于|至少|小于|低于|少于|不超过|至多).*报告",
            message,
        ):
            return "statistics"
        if re.search(r"比赛|参赛|评分|报名|赛程|主办方", message):
            return "qa"
        if re.search(r"筛选|过滤|查找|找出|检索|列出|符合.*条件|展示.*报告", message):
            return "filter"
        if re.search(r"推荐|适合|参考|相似案例|匹配.*报告|报告", message):
            return "recommendation"
        return None

    @staticmethod
    def _is_greeting(message: str) -> bool:
        normalized = re.sub(r"[\s，。！？,.!?~～]", "", message).lower()
        return normalized in {
            "你好", "您好", "嗨", "哈喽", "hello", "hi", "早上好", "上午好",
            "中午好", "下午好", "晚上好", "在吗", "你是谁", "你能做什么",
        }

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

    async def _report_results(
        self, request_id: str, session_id: str, intent: str
    ) -> ChatResponse:
        tags = self.database.get_session_tags(session_id)
        reports = self.database.all_reports_with_tags()
        fallback_results = (
            filter_reports(reports, tags, None)
            if intent == "filter" else rank_reports(reports, tags, None)
        )
        full_results = fallback_results
        if intent == "filter":
            recommendations = full_results
            status = "filter_results"
            assistant = (
                f"已按全部 {len(tags)} 个条件筛选到 {len(full_results)} 份报告。"
                if tags else f"当前未限定筛选条件，共返回 {len(full_results)} 份报告。"
            )
        else:
            recommendations = full_results[:3]
            status = "recommendations"
            assistant = (
                "已根据当前信息推荐最匹配的3份尽调报告。"
                if tags else "未限定条件，已按报告数据完整度推荐3份优秀案例。"
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

    def _handle_action(self, request_id: str, session_id: str,
                       action: dict[str, Any]) -> ChatResponse:
        action_type = action["type"]
        if action_type == "related_reports":
            return self._related(request_id, session_id, action["report_id"])
        raise ReportActionError("追问细化操作已下线，请直接输入新的问题或条件")

    async def chat(self, request_id: str, requested_session: str | None,
                   message: str | None, user_id: str | None = None,
                   action: dict[str, Any] | None = None) -> ChatResponse:
        session_id = self._session(requested_session, user_id)
        if action:
            return self._handle_action(request_id, session_id, action)
        assert message is not None
        session = self.database.get_session(session_id) or {}
        active = session.get("active_intent") or "unknown"
        history = self.database.get_messages(session_id)

        if self._is_greeting(message):
            self.database.add_message(
                session_id, "user", message, request_id=request_id,
                message_type="text", intent="greeting",
            )
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent="greeting",
                status="greeting", assistant_message=GREETING,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
            ))

        extraction, _fallback_used = await self._extract(history, message, None, active)
        if extraction.intent == "provide_information":
            intent = active if active in FLOW_INTENTS else (self._keyword_intent(message) or "recommendation")
        else:
            intent = MODEL_INTENTS[extraction.intent]
        keyword = self._keyword_intent(message)
        # Explicit feature words are deterministic routing signals and override
        # an occasional model misclassification (for example “推荐…报告”被判为 unsupported).
        if keyword is not None:
            intent = keyword
        elif intent == "unsupported" and active in FLOW_INTENTS:
            intent = active
        # 比赛问答必须有明确比赛上下文；防止模型把一般知识问题误判为比赛问答。
        if intent == "qa" and keyword != "qa" and active != "qa":
            intent = "unsupported"

        explicit_switch = extraction.intent != "provide_information" and intent != "unsupported"
        if explicit_switch and intent != active:
            self.database.set_session_intent(session_id, intent)
        elif intent in FLOW_INTENTS and active in {"unknown", "recommendation"}:
            self.database.set_session_intent(session_id, intent)

        self.database.add_message(
            session_id, "user", message, request_id=request_id,
            message_type="text", intent=intent,
        )

        if intent == "statistics":
            self.database.set_session_intent(session_id, intent)
            assistant, statistic = await self.features.statistics_for_question(message)
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
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent="unsupported",
                status="unsupported", assistant_message=OUT_OF_SCOPE,
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
            ))

        self.database.set_session_intent(session_id, intent)
        self.database.clear_expected_tag(session_id)
        rule_tags = rule_extract(message, None)
        model_tags = validated_model_tags(extraction.tags, message, None)
        model_tags = [
            tag for tag in model_tags
            if tag.name in TAG_DIMENSIONS and tag.confidence >= MIN_CONFIDENCE
        ]
        extracted, conflicts = reconcile_extractions(rule_tags, model_tags)
        # 取消歧义追问后，冲突时采用模型值；模型漏提但精确规则明确
        # 命中的标签用于补漏，避免“小微企业”等显式条件变成无条件推荐。
        extracted_names = {tag.name for tag in extracted}
        for conflict in conflicts:
            chosen = conflict.model_tag or conflict.rule_tag
            if chosen is not None and chosen.name not in extracted_names:
                extracted.append(chosen)
                extracted_names.add(chosen.name)
        valid = [
            {
                "name": tag.name, "value": tag.value,
                "dimension": TAG_DIMENSIONS[tag.name], "confidence": tag.confidence,
            }
            for tag in extracted if tag.name in TAG_DIMENSIONS
        ]
        self.database.upsert_session_tags(session_id, valid)
        return await self._report_results(request_id, session_id, intent)
