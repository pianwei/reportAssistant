from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from app.database import Database
from app.model_manager import ModelManager
from app.taxonomy import TAG_DIMENSIONS


INTENTS = ("recommendation", "filter", "statistics", "qa")
SUGGESTION_TEMPLATES: dict[str, list[str]] = {
    "recommendation": ["给我推荐几个优秀的尽调报告", "推荐适合科技型小微企业的尽调案例"],
    "filter": ["筛选科学研究和技术服务业的报告", "查找流动资金贷款相关报告"],
    "statistics": ["现在有多少篇尽调报告？", "哪个行业的报告最多？"],
    "qa": ["比赛要求是什么？", "比赛评分标准有哪些？"],
}

FEATURE_CARDS = [
    {
        "id": "recommendation", "title": "智能案例推荐", "icon": "spark",
        "description": "多轮理解需求，推荐相似尽调案例",
        "input_examples": ["给我推荐几个优秀的报告", "推荐适合小微科技企业的案例"],
        "assistant_example": "可以。你更关注客户行业、企业规模，还是授信方案？也可以跳过并直接推荐。",
    },
    {
        "id": "filter", "title": "多维筛选", "icon": "filter",
        "description": "对话收集条件，精准筛选报告",
        "input_examples": ["筛选制造业小微企业报告", "查找300万元流动资金贷款案例"],
        "assistant_example": "请告诉我筛选条件，我会逐项确认并按全部条件查找报告。",
    },
    {
        "id": "statistics", "title": "数据统计", "icon": "chart",
        "description": "通过问答查询报告与标签统计",
        "input_examples": ["现在有多少篇报告？", "哪个行业的报告最多？"],
        "assistant_example": "我会基于数据库中的全量报告标签计算并回答，不会让模型猜测数字。",
    },
    {
        "id": "qa", "title": "比赛问答", "icon": "chat",
        "description": "使用大模型回答比赛相关问题",
        "input_examples": ["比赛要求是什么？", "如何参加比赛？"],
        "assistant_example": "可以为你解答比赛问题；当前未接入官方资料，回答仅供参考。",
    },
]


class FeatureService:
    def __init__(self, database: Database, model_manager: ModelManager):
        self.database = database
        self.model_manager = model_manager

    def bootstrap(self, user_id: str) -> dict[str, Any]:
        defaults = [
            {"text": SUGGESTION_TEMPLATES[intent][0], "intent": intent}
            for intent in INTENTS[:3]
        ]
        return {
            "user_id": user_id,
            "assistant": {
                "name": "尽调报告助手",
                "intro": "你好，我是尽调报告助手。推荐、筛选、统计和比赛问答都可以直接在这里对话。",
            },
            "feature_cards": FEATURE_CARDS,
            "default_suggestions": defaults,
            "capabilities": {"rag_ready": False, "qa_source": "model"},
        }

    def _target_intents(self, usage: dict[str, int], previous: list[dict[str, str]]) -> list[str]:
        targets: list[str] = []
        previous_intents = {item.get("intent") for item in previous}
        if previous:
            targets.extend(intent for intent in INTENTS if intent not in previous_intents)
        if usage:
            ranked = sorted(INTENTS, key=lambda intent: (-usage.get(intent, 0), INTENTS.index(intent)))
            for intent in ranked:
                if intent not in targets:
                    targets.append(intent)
            exploration = min(INTENTS, key=lambda intent: (usage.get(intent, 0), INTENTS.index(intent)))
            if exploration not in targets[:3]:
                targets.insert(min(2, len(targets)), exploration)
        else:
            for intent in INTENTS:
                if intent not in targets:
                    targets.append(intent)
        return targets[:3]

    async def suggestions(self, user_id: str, session_id: str | None,
                          previous_batch_id: str | None = None) -> dict[str, Any]:
        previous = self.database.get_suggestion_batch(previous_batch_id, user_id)
        usage = self.database.user_intent_usage(user_id)
        targets = self._target_intents(usage, previous)
        history = self.database.recent_user_messages(user_id, 20)
        if session_id:
            current = self.database.get_messages(session_id, 10)
            history.extend({"content": item["content"], "intent": ""} for item in current if item["role"] == "user")
        generated = await self.model_manager.generate_suggestions(history[-20:], targets) if history else []
        by_intent = {item["intent"]: item for item in generated}
        prior_texts = {item.get("text") for item in previous}
        used_texts: set[str] = set()
        items: list[dict[str, str]] = []
        for intent in targets:
            item = by_intent.get(intent)
            if not item or item["text"] in prior_texts or item["text"] in used_texts:
                candidates = SUGGESTION_TEMPLATES[intent]
                text = next(
                    (value for value in candidates if value not in prior_texts and value not in used_texts),
                    f"了解更多{next(card['title'] for card in FEATURE_CARDS if card['id'] == intent)}信息",
                )
                item = {"text": text, "intent": intent}
            items.append(item)
            used_texts.add(item["text"])
        batch_id = f"sug_{uuid.uuid4().hex}"
        self.database.save_suggestion_batch(batch_id, user_id, items)
        return {
            "suggestions": items, "source": "model" if generated else "fallback",
            "batch_id": batch_id,
        }

    def statistics_for_question(self, question: str) -> tuple[str, dict[str, Any]]:
        reports = self.database.all_reports_with_tags()
        all_tags = [tag for report in reports for tag in report["tags"]]
        if any(word in question for word in ("多少篇", "多少份", "报告数", "报告总数")):
            value = len(reports)
            return f"当前数据库共有 {value} 篇尽调报告。", {
                "metric": "report_count", "title": "报告总数", "value": value, "breakdown": [],
            }
        if any(word in question for word in ("多少个标签", "标签数", "标签总数")):
            value = len(all_tags)
            return f"当前数据库共有 {value} 条报告标签。", {
                "metric": "tag_count", "title": "标签总数", "value": value, "breakdown": [],
            }
        if "行业" in question:
            values = [
                tag["value"].split("（", 1)[0] for tag in all_tags
                if tag["name"] == "行业分类" and "不可提取" not in tag["value"]
            ]
            counts = Counter(values)
            breakdown = [{"label": label, "count": count} for label, count in counts.most_common(10)]
            if breakdown:
                top = breakdown[0]
                distribution = "、".join(f"{item['label']} {item['count']}篇" for item in breakdown)
                answer = f"当前报告数量最多的行业是{top['label']}，共有 {top['count']} 篇。行业分布为：{distribution}。"
                value: int | str = top["label"]
            else:
                answer, value = "当前报告中没有可统计的行业标签。", "暂无数据"
            return answer, {"metric": "industry_distribution", "title": "行业分布", "value": value, "breakdown": breakdown}
        if "类型" in question:
            counts = Counter(report["report_type"] for report in reports)
            breakdown = [{"label": label, "count": count} for label, count in counts.most_common(10)]
            distribution = "、".join(f"{item['label']} {item['count']}篇" for item in breakdown) or "暂无数据"
            return f"报告类型共 {len(counts)} 类，分布为：{distribution}。", {
                "metric": "report_type_distribution", "title": "报告类型分布",
                "value": len(counts), "breakdown": breakdown,
            }
        tag_name = next((name for name in TAG_DIMENSIONS if name in question), None)
        if tag_name:
            counts = Counter(tag["value"] for tag in all_tags if tag["name"] == tag_name)
            breakdown = [{"label": label, "count": count} for label, count in counts.most_common(10)]
            distribution = "、".join(f"{item['label']} {item['count']}条" for item in breakdown) or "暂无数据"
            return f"“{tag_name}”共有 {len(counts)} 个不同取值，分布为：{distribution}。", {
                "metric": "tag_distribution", "title": f"{tag_name}分布",
                "value": len(counts), "breakdown": breakdown,
            }
        return (
            f"当前共有 {len(reports)} 篇报告、{len(all_tags)} 条标签。你还可以询问哪个行业最多或报告类型分布。",
            {
                "metric": "overview", "title": "数据概览", "value": len(reports),
                "breakdown": [
                    {"label": "报告", "count": len(reports)},
                    {"label": "标签", "count": len(all_tags)},
                ],
            },
        )
