from __future__ import annotations

import json
import re
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.schemas import ModelExtraction
from app.taxonomy import TAG_DIMENSIONS


class LLMError(RuntimeError):
    pass


class Extractor(Protocol):
    async def extract(
        self, history: list[dict[str, str]], message: str, expected_tag: str | None = None
    ) -> ModelExtraction: ...


SYSTEM_PROMPT = """你是银行尽调报告推荐助手中的信息抽取模块。
只输出一个 JSON 对象，不得输出 Markdown 或解释。格式：
{{"intent":"report_recommendation|report_filter|report_statistics|competition_qa|provide_information|unsupported","tags":[{{"name":"标准标签名","value":"用户原文中的值","evidence":"包含该值的用户原文片段","confidence":0.0}}],"statistic_query":"可选的统计指标"}}

规则：
1. 用户消息中只要表达寻找、推荐、匹配或参考尽调报告，intent 必须为 report_recommendation，即使同一条消息也提供了客户或授信信息。
2. 用户要求按条件查找、筛选、过滤报告时，intent=report_filter。
3. 用户询问报告数、标签数、最多行业、类型或标签分布时，intent=report_statistics，并概括 statistic_query。
4. 用户询问比赛要求、规则、时间、评分或参赛方式时，intent=competition_qa。
5. 用户在回答助手问题或补充客户/授信信息时，intent=provide_information。
6. 与尽调报告、报告统计和比赛均无关时，intent=unsupported。
7. 只能使用下面列出的标准标签名；没有明确依据时不要提取。
8. 结合对话历史理解省略表达，但 tags 只返回本轮新增、补充或纠正的信息。
9. value 必须直接来自本轮用户原文；evidence 必须逐字复制本轮原文中包含 value 的连续片段。不得臆测、改写或使用对话历史作为 evidence。
10. “申请、授信、贷款、额度”附近的金额只能标为“授信金额”；只有用户明确说“总资产”时才能标为“最新一期财报总资产”，总负债、净利润、现金流同理。
11. 企业所属行业标为“行业分类”。用户说“科学研究和技术服务业”时必须原样保留，不得替换成制造业或其他行业。
12. “流动资金贷款、订单融资”等产品名称标为“授信品种”；“小微企业、小型企业”等规模描述标为“企业规模”。

示例输入：我想找一份可参考的尽调报告
示例 JSON 输出：{{"intent":"report_recommendation","tags":[]}}

示例输入：今天天气如何
示例 JSON 输出：{{"intent":"unsupported","tags":[]}}

标准标签：
{taxonomy}
"""


def _json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return value


class OpenAICompatibleExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def endpoint(self) -> str:
        base = self.settings.llm_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def extract(
        self, history: list[dict[str, str]], message: str, expected_tag: str | None = None
    ) -> ModelExtraction:
        if not self.settings.llm_configured:
            raise LLMError("内网大模型尚未配置")

        taxonomy = "\n".join(f"- {name}（{dimension}）" for name, dimension in TAG_DIMENSIONS.items())
        system_prompt = SYSTEM_PROMPT.format(taxonomy=taxonomy)
        if expected_tag:
            system_prompt += (
                f"\n当前用户正在回答对“{expected_tag}”的追问。"
                f"如果 intent=provide_information，tags 中只允许返回 name={expected_tag}；"
                "如果用户明确发起新的推荐、筛选、统计或比赛问题，则按新意图正常提取。"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message},
        ]
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1000,
        }
        if self.settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.settings.llm_disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        last_error: Exception | None = None
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                    response = await client.post(self.endpoint, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                return ModelExtraction.model_validate(_json_object(content))
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
                last_error = exc
        error_type = type(last_error).__name__ if last_error else "UnknownError"
        raise LLMError(f"模型调用或结构化输出解析失败（{error_type}）") from last_error
