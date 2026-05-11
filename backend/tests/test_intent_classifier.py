"""Tests for keyword-based chat/refine intent classifier (P3)."""
import pytest

from app.application.intent_classifier import classify_intent


@pytest.mark.parametrize("content", [
    # Chinese refine action verbs
    "改进第3条",
    "修改 product_goals",
    "把第2点改成 X",
    "加一条目标",
    "添加 user_story",
    "增加 acceptance criteria",
    "新增 risk",
    "删除第4个 constraint",
    "移除 open question",
    "更新 requirement_analysis",
    "替换为新方案",
    "重写概述",
    "重做架构",
    "重构 implementation_plan",
    "优化措辞",
    "调整 priority",
    # English
    "change the second goal",
    "update product_goals",
    "modify the second user story",
    "add a new risk",
    "remove the third constraint",
    "rewrite the analysis",
    "refactor the design",
    "improve the wording",
])
def test_classify_refine_inputs(content):
    assert classify_intent(content) == "refine", f"Expected refine for: {content!r}"


@pytest.mark.parametrize("content", [
    # Chinese chat / questions / greetings
    "你好",
    "你好啊",
    "请问这个 issue 怎么处理",
    "是否需要考虑 A 方案",
    "能否解释一下第3点",
    "怎么实现这个功能",
    "如何理解这一段",
    "为什么选这个方案",
    "什么时候完成",
    "请解释这一段",
    "麻烦讲一下设计思路",
    # English question/discussion
    "what is the second goal?",
    "why this approach?",
    "how does it work",
    "explain the architecture",
    # Empty / whitespace
    "",
    "   ",
    "\n\n",
    # Punctuation-only / emoji
    "?",
    "?",
    "👍",
])
def test_classify_chat_inputs(content):
    assert classify_intent(content) == "chat", f"Expected chat for: {content!r}"


def test_mixed_input_with_question_marker_is_chat():
    """If both refine and chat tokens hit, default to chat (safer fallback)."""
    assert classify_intent("怎么改第3条") == "chat"
    assert classify_intent("为什么要修改这一段") == "chat"


def test_pure_refine_action_with_punctuation():
    assert classify_intent(" 改 ， 一下 ， 第3条 。 ") == "refine"
    assert classify_intent("把第2条改成 X！") == "refine"


def test_none_or_falsy_input_returns_chat():
    assert classify_intent(None) == "chat"  # type: ignore[arg-type]
    assert classify_intent("") == "chat"
