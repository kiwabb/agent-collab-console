from __future__ import annotations

from enum import StrEnum


class SessionState(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    PLANNED = "planned"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
