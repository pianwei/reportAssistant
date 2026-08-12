from app.llm import SYSTEM_PROMPT, _json_object, _weighted_history_context


def test_system_prompt_can_render_taxonomy():
    rendered = SYSTEM_PROMPT.format(taxonomy="- 行业分类（客户维度）")
    assert '"intent"' in rendered
    assert "行业分类" in rendered


def test_json_object_accepts_code_fence():
    result = _json_object(
        '```json\n{"intent":"unsupported","tags":[]}\n```'
    )
    assert result["intent"] == "unsupported"


def test_weighted_history_keeps_five_rounds_and_favors_recent_questions():
    history = []
    for index in range(1, 7):
        history.extend([
            {"role": "user", "content": f"问题{index}"},
            {"role": "assistant", "content": f"回答{index}"},
        ])

    context = _weighted_history_context(history)

    assert "问题1" not in context
    assert "回答1" not in context
    assert "[权重1] 用户问题：问题2" in context
    assert "[权重5] 用户问题：问题6" in context
    assert "回答2" not in context
