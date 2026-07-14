from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

GenerationRunStatus = Literal["queued", "running", "completed", "partial", "failed", "interrupted"]
GenerationItemStatus = Literal["pending", "generating", "done", "failed", "interrupted", "skipped"]
GenerationItemPhase = Literal[
    "queued",
    "starting",
    "streaming",
    "persisting",
    "completed",
    "failed",
    "interrupted",
    "skipped",
]


@dataclass
class PrototypeGenerationRunItem:
    id: str
    run_id: str
    plan_item_id: str
    prototype_id: str | None
    status: GenerationItemStatus
    title: str = ""
    seed_brief: str = ""
    attempt: int = 0
    phase: GenerationItemPhase = "queued"
    output_chars: int = 0
    last_event_at: datetime | None = None
    status_message: str = ""
    task_id: str | None = None
    execution_process_id: str | None = None
    error_message: str | None = None
    version_no: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "plan_item_id": self.plan_item_id,
            "prototype_id": self.prototype_id,
            "status": self.status,
            "title": self.title,
            "attempt": self.attempt,
            "phase": self.phase,
            "output_chars": self.output_chars,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "status_message": self.status_message,
            "task_id": self.task_id,
            "execution_process_id": self.execution_process_id,
            "error_message": self.error_message,
            "version_no": self.version_no,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class PrototypeGenerationRun:
    id: str
    plan_id: str
    project_id: str
    status: GenerationRunStatus
    repository_fingerprint: str
    total: int
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    running: int = 0
    pending: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def completed(self) -> int:
        """Legacy success-count alias retained for existing API consumers."""
        return self.succeeded

    def to_dict(self, items: list[PrototypeGenerationRunItem] | None = None) -> dict[str, object]:
        return {
            "contract_version": 1,
            "id": self.id,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "status": self.status,
            "repository_fingerprint": self.repository_fingerprint,
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "completed": self.completed,
            "failed": self.failed,
            "running": self.running,
            "pending": self.pending,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "items": [item.to_dict() for item in items] if items is not None else [],
        }


@dataclass(frozen=True)
class PrototypeGenerationRunFreezeResult:
    run: PrototypeGenerationRun
    created: bool
