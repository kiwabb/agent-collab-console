"""Agent clarification flow.

Each role's JSON output schema carries an optional `clarification_question`
field. When the agent encounters a critical ambiguity it cannot reasonably
infer (e.g. PRD calls for "use the standard auth flow" but no auth flow is
documented), it sets that field instead of guessing.

Persist_result then:
  1. Writes the artifact normally — the partial output is preserved.
  2. Mutates the task: status="awaiting_review",
     review_comment=f"[CLARIFY] {question}".
  3. Returns the doc to the caller (api / runner) which then saves the task.

The scheduler treats `awaiting_review` as non-terminal, so downstream nodes
stay blocked until the user replies via /codex/tasks/{id}/answer.

The instruction injected into every role's prompt nudges them to use this
field whenever they would otherwise have to invent context.
"""
from __future__ import annotations

from typing import Protocol

CLARIFY_PREFIX = "[CLARIFY] "


CLARIFICATION_PROMPT_INSTRUCTION = (
    "AGENT QUESTION ESCAPE HATCH (mandatory):\n"
    "- If you encounter a CRITICAL ambiguity or missing piece of information that "
    "you cannot reasonably infer from the upstream artifacts and the user requirement, "
    "DO NOT guess. Populate the optional `clarification_question` field with a "
    "single, specific, single-sentence question the user must answer for you to "
    "proceed correctly.\n"
    "- Use this sparingly — only when guessing would meaningfully damage the "
    "outcome. Trivial defaults (lib version, code style, file location) you should "
    "pick a reasonable default and flag in risks/qa_notes instead.\n"
    "- When you set `clarification_question`, you may still fill the rest of the "
    "schema with your best partial answer; the framework will pause the pipeline "
    "and re-run you once the user replies.\n"
)


class ClarificationTask(Protocol):
    status: str
    review_comment: str | None


def question_text(task: ClarificationTask) -> str | None:
    """Extract the question text from a task whose review_comment is in
    [CLARIFY] format. Returns None when the task isn't currently asking."""
    rc = task.review_comment
    if not isinstance(rc, str) or not rc:
        return None
    if not rc.startswith(CLARIFY_PREFIX):
        return None
    return rc[len(CLARIFY_PREFIX) :].strip()


def mark_task_pending_clarification(task: ClarificationTask, question: str) -> None:
    """Mutate task in place to signal a clarification is needed."""
    question = (question or "").strip()
    if not question:
        return
    task.status = "awaiting_review"
    task.review_comment = f"{CLARIFY_PREFIX}{question}"


def apply_clarification_if_needed(task: ClarificationTask, doc: object) -> bool:
    """If the doc carries a populated `clarification_question`, transition the
    task into the clarification-pending state and return True. Otherwise
    return False so the caller can mark the task done normally.

    Works with any role's pydantic document — accesses the field by attribute,
    tolerates its absence.
    """
    question = getattr(doc, "clarification_question", None)
    if not question:
        return False
    mark_task_pending_clarification(task, str(question))
    return True
