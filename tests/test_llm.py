from app.llm import SYSTEM_PROMPT, _json_object


def test_system_prompt_can_render_taxonomy():
    rendered = SYSTEM_PROMPT.format(taxonomy="- 行业分类（客户维度）")
    assert '"intent"' in rendered
    assert "行业分类" in rendered


def test_json_object_accepts_code_fence():
    result = _json_object(
        '```json\n{"intent":"unsupported","tags":[]}\n```'
    )
    assert result["intent"] == "unsupported"
