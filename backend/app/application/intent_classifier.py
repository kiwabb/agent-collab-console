"""Keyword-based intent classifier: chat vs refine.

This is used by the /send endpoint to auto-route user follow-up messages
without requiring the user to manually pick a mode. Refine takes precedence
ONLY when an action verb is present AND no question marker is present —
otherwise we default to chat, which is the safer fallback (chat does not
mutate task.result or persist artifacts).
"""

from __future__ import annotations

from typing import Literal

# Action verbs that imply the user wants to modify the artifact.
REFINE_TOKENS_CN: tuple[str, ...] = (
    "改",
    "修改",
    "修正",
    "改进",
    "调整",
    "加",
    "添加",
    "增加",
    "新增",
    "删",
    "删除",
    "移除",
    "更新",
    "替换",
    "重写",
    "重做",
    "重构",
    "优化",
)

REFINE_TOKENS_EN: tuple[str, ...] = (
    "change",
    "update",
    "modify",
    "add",
    "remove",
    "delete",
    "rewrite",
    "refactor",
    "improve",
)

# Question / discussion / courtesy markers that imply a chat turn.
CHAT_TOKENS_CN: tuple[str, ...] = (
    "问",
    "请问",
    "是否",
    "能否",
    "怎么",
    "如何",
    "为什么",
    "什么",
    "哪",
    "解释",
    "说明",
    "讲",
    "麻烦",
)

CHAT_TOKENS_EN: tuple[str, ...] = (
    "what",
    "why",
    "how",
    "explain",
    "?",
)


def classify_intent(content: str | None) -> Literal["chat", "refine"]:
    """Classify a user follow-up message into chat vs refine.

    Returns:
        "refine" when an action verb is present AND no question marker is present.
        "chat" otherwise (including empty / falsy input and mixed signals).
    """
    if not content:
        return "chat"
    lowered = content.lower().strip()
    if not lowered:
        return "chat"

    has_refine = any(tok in lowered for tok in REFINE_TOKENS_CN) or any(
        tok in lowered for tok in REFINE_TOKENS_EN
    )
    has_chat = any(tok in lowered for tok in CHAT_TOKENS_CN) or any(
        tok in lowered for tok in CHAT_TOKENS_EN
    )

    if has_refine and not has_chat:
        return "refine"
    return "chat"
