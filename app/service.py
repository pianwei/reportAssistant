from __future__ import annotations

import re
import uuid
from collections import Counter
from typing import Any

from app.database import Database
from app.extraction import ExtractionConflict, reconcile_extractions, rule_extract, validated_model_tags
from app.features import FeatureService
from app.llm import Extractor, LLMError
from app.matcher import filter_reports, rank_reports, related_reports
from app.model_manager import ModelManager
from app.schemas import (
    AnswerResult, ChatResponse, ClarificationQuestion, CollectedTag,
    FollowUpCard, FollowUpGroup, FollowUpOption, ModelExtraction, StatisticResult,
)
from app.taxonomy import (
    BUSINESS, CUSTOMER, QUESTION_PRIORITY, QUESTION_TEMPLATES,
    TAG_DIMENSIONS, TAG_WEIGHTS,
)


MAX_REFINEMENTS = 3
MIN_CONFIDENCE = 0.5
FLOW_INTENTS = {"recommendation", "filter"}
MODEL_INTENTS = {
    "report_recommendation": "recommendation",
    "report_filter": "filter",
    "report_statistics": "statistics",
    "competition_qa": "qa",
    "unsupported": "unsupported",
}
SKIP_REPLIES = {"跳过", "不知道", "不清楚", "暂不提供", "暂不补充", "下一个", "不用了"}
FINISH_REPLIES = {"按现有信息生成", "直接推荐", "直接筛选", "开始推荐", "开始筛选", "就这些", "生成结果"}
DISCLAIMER = "当前未接入官方比赛资料，回答由大模型生成，仅供参考，请以主办方官方通知为准。"
UNAVAILABLE_MARKERS = ("不可提取", "未提供", "未知", "不适用", "无相关")


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

    @staticmethod
    def _candidate_groups(reports: list[dict[str, Any]], result_ids: list[str],
                          known_tags: set[str]) -> list[FollowUpGroup]:
        by_id = {report["report_id"]: report for report in reports}
        candidates = [by_id[report_id] for report_id in result_ids if report_id in by_id]
        ranked_groups: list[tuple[float, int, FollowUpGroup]] = []
        for priority, name in enumerate(QUESTION_PRIORITY):
            if name in known_tags:
                continue
            counts: Counter[str] = Counter()
            for report in candidates:
                value = next(
                    (tag["value"].strip() for tag in report.get("tags", []) if tag["name"] == name),
                    "",
                )
                if value and not any(marker in value for marker in UNAVAILABLE_MARKERS):
                    counts[value] += 1
            if len(counts) < 2:
                continue
            total = sum(counts.values())
            dominance = max(counts.values()) / total
            utility = TAG_WEIGHTS.get(name, 1.0) * len(counts) * (1.0 - dominance)
            options = [
                FollowUpOption(label=value, value=value, count=count)
                for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
            ]
            ranked_groups.append((utility, priority, FollowUpGroup(
                tag_name=name, label=name, options=options,
            )))
        ranked_groups.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked_groups[:4]]

    def _follow_up(self, session_id: str, intent: str, reports: list[dict[str, Any]],
                   full_results: list[Any]) -> FollowUpCard | None:
        count = self.database.refinement_count(session_id)
        if count >= MAX_REFINEMENTS:
            self.database.set_expected_tag(session_id, None)
            return None
        tags = self.database.get_session_tags(session_id)
        groups = self._candidate_groups(
            reports, [item.report_id for item in full_results], {tag["name"] for tag in tags},
        )
        if not groups:
            self.database.set_expected_tag(session_id, None)
            return None
        self.database.set_expected_tag(session_id, groups[0].tag_name)
        is_filter = intent == "filter"
        return FollowUpCard(
            kind="filter_more" if is_filter else "preference",
            title="继续缩小筛选范围" if is_filter else "让推荐更贴合你的偏好",
            prompt=(f"还需要考虑“{groups[0].label}”吗？" if is_filter
                    else f"在“{groups[0].label}”方面，你更倾向于哪一种？"),
            groups=groups, allow_more=len(groups) > 1,
            remaining_rounds=MAX_REFINEMENTS - count,
        )

    def _first_filter_prompt(self, session_id: str, reports: list[dict[str, Any]]) -> FollowUpCard:
        ranked = rank_reports(reports, [], None)
        groups = self._candidate_groups(reports, [item.report_id for item in ranked], set())
        if not groups:
            name = QUESTION_PRIORITY[0]
            fallback, examples = QUESTION_TEMPLATES[name]
            groups = [FollowUpGroup(
                tag_name=name, label=name,
                options=[FollowUpOption(label=value, value=value) for value in examples],
            )]
            prompt = fallback
        else:
            prompt = f"先选择一个“{groups[0].label}”条件，我会立即返回筛选结果。"
        self.database.set_expected_tag(session_id, groups[0].tag_name)
        return FollowUpCard(
            kind="filter_more", title="选择首个筛选条件", prompt=prompt,
            groups=groups, allow_more=len(groups) > 1,
            remaining_rounds=MAX_REFINEMENTS,
        )

    def _confirmation_follow_up(self, session_id: str, conflict: ExtractionConflict) -> FollowUpCard:
        values = []
        for tag in (conflict.model_tag, conflict.rule_tag):
            if tag and tag.value not in values:
                values.append(tag.value)
        self.database.set_expected_tag(session_id, conflict.name)
        return FollowUpCard(
            kind="confirmation", title="请确认识别结果",
            prompt=f"关于“{conflict.name}”存在不同判断，请选择准确值。",
            groups=[FollowUpGroup(
                tag_name=conflict.name, label=conflict.name,
                options=[FollowUpOption(label=value, value=value) for value in values],
            )],
            allow_custom=True, allow_skip=True,
            remaining_rounds=max(0, MAX_REFINEMENTS - self.database.refinement_count(session_id)),
        )

    def _report_results(self, request_id: str, session_id: str, intent: str,
                        include_follow_up: bool = True,
                        override_follow_up: FollowUpCard | None = None) -> ChatResponse:
        tags = self.database.get_session_tags(session_id)
        reports = self.database.all_reports_with_tags()
        if intent == "filter" and not tags:
            follow_up = self._first_filter_prompt(session_id, reports) if include_follow_up else None
            question = None
            if follow_up and follow_up.groups:
                group = follow_up.groups[0]
                question = ClarificationQuestion(
                    tag_name=group.tag_name, text=follow_up.prompt,
                    examples=[item.value for item in group.options],
                )
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="needs_clarification", assistant_message="请先提供至少一个筛选条件。",
                collected_tags=[], question=question, follow_up=follow_up,
            ))

        full_results = (
            filter_reports(reports, tags, None)
            if intent == "filter" else rank_reports(reports, tags, None)
        )
        if intent == "filter":
            recommendations = full_results
            status = "filter_results"
            assistant = f"已按全部 {len(tags)} 个确认条件筛选到 {len(full_results)} 份报告。"
        else:
            recommendations = full_results[:3]
            status = "recommendations"
            assistant = (
                "已根据当前信息推荐最匹配的3份尽调报告。"
                if tags else "未限定条件，已按报告数据完整度推荐3份优秀案例。"
            )

        follow_up = override_follow_up
        if not follow_up and include_follow_up:
            if intent == "filter" and not full_results:
                latest = tags[-1]["name"] if tags else None
                follow_up = FollowUpCard(
                    kind="no_results", title="暂未找到匹配报告",
                    prompt="可以移除最近条件，或输入新的条件重新筛选。",
                    removable_tag=latest, groups=[], allow_more=False,
                    remaining_rounds=max(0, MAX_REFINEMENTS - self.database.refinement_count(session_id)),
                )
                self.database.set_expected_tag(session_id, latest)
            else:
                follow_up = self._follow_up(session_id, intent, reports, full_results)

        dimensions = {tag["dimension"] for tag in tags}
        incomplete = not ({CUSTOMER, BUSINESS} <= dimensions)
        return self._finish(ChatResponse(
            request_id=request_id, session_id=session_id, intent=intent,
            status=status, assistant_message=assistant,
            collected_tags=self._collected(tags), information_incomplete=incomplete,
            recommendations=recommendations, follow_up=follow_up,
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
        session = self.database.get_session(session_id) or {}
        intent = session.get("active_intent")
        if intent not in FLOW_INTENTS:
            raise ReportActionError("当前会话不在推荐或筛选流程中")
        if action_type == "skip_refinement":
            self.database.set_expected_tag(session_id, None)
            self.database.add_message(
                session_id, "user", "暂不补充，保留当前结果",
                message_type="action", request_id=request_id, intent=intent,
            )
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="recommendations" if intent == "recommendation" else "filter_results",
                assistant_message="好的，已保留当前结果，你之后仍可继续输入条件。",
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
            ))
        if action_type == "remove_tag":
            tag_name = action["tag_name"]
            if not self.database.remove_session_tag(session_id, tag_name):
                raise ReportActionError("要移除的筛选条件不存在")
            self.database.add_message(
                session_id, "user", f"移除筛选条件：{tag_name}",
                message_type="action", request_id=request_id, intent=intent,
            )
            return self._report_results(request_id, session_id, intent)
        selections = action.get("selections") or []
        invalid = [item["tag_name"] for item in selections if item["tag_name"] not in TAG_DIMENSIONS]
        if invalid:
            raise ReportActionError(f"不支持的标签：{invalid[0]}")
        self.database.upsert_session_tags(session_id, [
            {
                "name": item["tag_name"], "value": item["value"],
                "dimension": TAG_DIMENSIONS[item["tag_name"]], "confidence": 1.0,
            }
            for item in selections
        ])
        self.database.increment_refinement(session_id)
        self.database.set_expected_tag(session_id, None)
        readable = "、".join(f"{item['tag_name']}={item['value']}" for item in selections)
        self.database.add_message(
            session_id, "user", f"补充条件：{readable}",
            message_type="action", request_id=request_id, intent=intent,
        )
        return self._report_results(request_id, session_id, intent)

    async def chat(self, request_id: str, requested_session: str | None,
                   message: str | None, user_id: str | None = None,
                   action: dict[str, Any] | None = None) -> ChatResponse:
        session_id = self._session(requested_session, user_id)
        if action:
            return self._handle_action(request_id, session_id, action)
        assert message is not None
        session = self.database.get_session(session_id) or {}
        active = session.get("active_intent") or "unknown"
        expected_tag = session.get("expected_tag")
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
        if is_skip:
            self.database.set_expected_tag(session_id, None)
            return self._finish(ChatResponse(
                request_id=request_id, session_id=session_id, intent=intent,
                status="recommendations" if intent == "recommendation" else "filter_results",
                assistant_message="好的，已保留当前结果，你之后仍可继续输入条件。",
                collected_tags=self._collected(self.database.get_session_tags(session_id)),
            ))
        if is_finish:
            self.database.set_expected_tag(session_id, None)
            return self._report_results(request_id, session_id, intent, include_follow_up=False)

        self.database.clear_expected_tag(session_id)
        rule_tags = rule_extract(message, expected_tag)
        model_tags = validated_model_tags(extraction.tags, message, expected_tag)
        model_tags = [
            tag for tag in model_tags
            if tag.name in TAG_DIMENSIONS and tag.confidence >= MIN_CONFIDENCE
        ]
        extracted, conflicts = reconcile_extractions(rule_tags, model_tags)
        valid = [
            {
                "name": tag.name, "value": tag.value,
                "dimension": TAG_DIMENSIONS[tag.name], "confidence": tag.confidence,
            }
            for tag in extracted if tag.name in TAG_DIMENSIONS
        ]
        self.database.upsert_session_tags(session_id, valid)
        if expected_tag and valid:
            self.database.increment_refinement(session_id)

        override = self._confirmation_follow_up(session_id, conflicts[0]) if conflicts else None
        return self._report_results(
            request_id, session_id, intent,
            include_follow_up=True, override_follow_up=override,
        )
