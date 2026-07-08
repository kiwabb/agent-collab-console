from __future__ import annotations

from pydantic import BaseModel


class SpecialistCallRequest(BaseModel):
    """Structured Engineer/QA request for a direct specialist child run."""

    role_key: str
    prompt: str
    why: str = ""
