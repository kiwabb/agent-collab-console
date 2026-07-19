from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.application.local_service_probe import LocalServiceUrlError, canonicalize_local_service_url
from app.application.project_command import (
    ProjectCommandError,
    parse_project_command,
    parse_project_setup_commands,
)
from app.domain.models import (
    Project,
    ProjectReadinessProbe,
    ProjectStartupEvidence,
    ProjectStartupService,
)


class StartupConfigError(ValueError):
    pass


class ReadinessJsonSubsetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["json_subset"]
    expected: dict[str, JsonValue] = Field(min_length=1, max_length=50)


class ReadinessTextContainsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["text_contains"]
    text: str = Field(min_length=1, max_length=1_000)


ReadinessIdentityInput = Annotated[
    ReadinessJsonSubsetInput | ReadinessTextContainsInput,
    Field(discriminator="kind"),
]


class HttpReadinessProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["http"]
    url: str = Field(min_length=1, max_length=2_000)
    expected_status: int = Field(ge=100, le=599)
    identity: ReadinessIdentityInput


class StartupServiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    service_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    working_directory: str = Field(min_length=1, max_length=2_000)
    setup_command: str = Field(default="", max_length=8_000)
    run_command: str = Field(min_length=1, max_length=8_000)
    access_url: str | None = Field(default=None, max_length=2_000)
    readiness_probe: HttpReadinessProbeInput
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    evidence: list[StartupEvidenceInput] = Field(default_factory=list, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_identity(self) -> StartupServiceInput:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.service_id) is None:
            raise ValueError("service_id must use lowercase letters, digits, hyphens, or underscores")
        if self.service_id in self.depends_on:
            raise ValueError("service cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on contains duplicates")
        evidence_paths = [item.path for item in self.evidence]
        if len(set(evidence_paths)) != len(evidence_paths):
            raise ValueError("evidence contains duplicates")
        return self


class StartupEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=2_000)
    detail: str = Field(default="", max_length=4_000)


class StartupEnvVarInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=200)
    value: str | None = Field(default=None, max_length=20_000)
    secret: bool = False
    source: str = Field(default="", max_length=2_000)


class StartupConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    services: list[StartupServiceInput] = Field(min_length=1, max_length=50)
    env_vars: list[StartupEnvVarInput] = Field(default_factory=list, max_length=200)
    notes: list[str] = Field(default_factory=list, max_length=100)


class StartupConfigStore(Protocol):
    async def replace_project_startup_services(
        self,
        project_id: str,
        task_id: str,
        services: list[ProjectStartupService],
        notes: list[str],
    ) -> None: ...

    async def list_project_startup_services(
        self, project_id: str
    ) -> list[ProjectStartupService]: ...

    async def load_project_startup_config_meta(
        self, project_id: str
    ) -> dict[str, object] | None: ...

    async def load_project_env_var(self, project_id: str, name: str) -> object | None: ...

    async def save_project_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        *,
        secret: bool = False,
        source: str = "user",
    ) -> None: ...


class ProjectStartupConfigService:
    def __init__(self, store: StartupConfigStore) -> None:
        self.store = store

    async def save_analysis(
        self,
        *,
        project: Project,
        task_id: str,
        payload: StartupConfigInput,
    ) -> list[ProjectStartupService]:
        services = self._validate_services(project, payload.services)
        await self.store.replace_project_startup_services(
            project.id,
            task_id,
            services,
            payload.notes,
        )
        for env_var in payload.env_vars:
            existing = await self.store.load_project_env_var(project.id, env_var.name)
            if existing is not None:
                continue
            await self.store.save_project_env_var(
                project.id,
                env_var.name,
                "" if env_var.secret else (env_var.value or ""),
                secret=env_var.secret,
                source=env_var.source or "agent",
            )
        return services

    async def get_config(self, project: Project) -> dict[str, object]:
        services = await self.store.list_project_startup_services(project.id)
        meta = await self.store.load_project_startup_config_meta(project.id)
        return {
            "project_id": project.id,
            "task_id": meta["task_id"] if meta else None,
            "notes": meta["notes"] if meta else [],
            "updated_at": meta["updated_at"] if meta else project.updated_at,
            "services": [service.model_dump(mode="json") for service in services],
        }

    @staticmethod
    def _validate_services(
        project: Project, inputs: list[StartupServiceInput]
    ) -> list[ProjectStartupService]:
        service_ids = [item.service_id for item in inputs]
        if len(set(service_ids)) != len(service_ids):
            raise StartupConfigError("service_id values must be unique")
        known = set(service_ids)
        for item in inputs:
            missing = set(item.depends_on) - known
            if missing:
                raise StartupConfigError(
                    f"service {item.service_id} depends on unknown services: {', '.join(sorted(missing))}"
                )
        ProjectStartupConfigService._assert_acyclic(inputs)

        root = Path(project.repo_path).resolve()
        now = datetime.now()
        services: list[ProjectStartupService] = []
        for item in inputs:
            cwd = (root / item.working_directory).resolve()
            if not cwd.is_relative_to(root) or not cwd.is_dir():
                raise StartupConfigError(
                    f"service {item.service_id} working_directory is outside the project or missing"
                )
            try:
                parse_project_command(item.run_command, str(cwd))
                if item.setup_command:
                    parse_project_setup_commands(item.setup_command, str(cwd))
            except ProjectCommandError as exc:
                raise StartupConfigError(
                    f"service {item.service_id} command was refused: {exc.reason}"
                ) from exc
            try:
                readiness_url = canonicalize_local_service_url(item.readiness_probe.url)
            except LocalServiceUrlError as exc:
                raise StartupConfigError(
                    f"service {item.service_id} readiness URL was refused: {exc.reason}"
                ) from exc
            normalized_evidence: list[ProjectStartupEvidence] = []
            for evidence in item.evidence:
                evidence_path = (root / evidence.path).resolve()
                if not evidence_path.is_relative_to(root) or not evidence_path.is_file():
                    raise StartupConfigError(
                        f"service {item.service_id} evidence is outside the project or missing"
                    )
                normalized_evidence.append(
                    ProjectStartupEvidence(
                        path=evidence_path.relative_to(root).as_posix(),
                        detail=evidence.detail.strip(),
                    )
                )
            services.append(
                ProjectStartupService(
                    project_id=project.id,
                    service_id=item.service_id,
                    name=item.name,
                    working_directory=cwd.relative_to(root).as_posix() or ".",
                    setup_command=item.setup_command.strip(),
                    run_command=item.run_command.strip(),
                    access_url=item.access_url,
                    readiness_probe=ProjectReadinessProbe.model_validate(
                        {
                            **item.readiness_probe.model_dump(mode="json"),
                            "url": readiness_url,
                        }
                    ),
                    depends_on=item.depends_on,
                    evidence=normalized_evidence,
                    created_at=now,
                    updated_at=now,
                )
            )
        return services

    @staticmethod
    def _assert_acyclic(inputs: list[StartupServiceInput]) -> None:
        dependencies = {item.service_id: item.depends_on for item in inputs}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(service_id: str) -> None:
            if service_id in visited:
                return
            if service_id in visiting:
                raise StartupConfigError("service dependency graph contains a cycle")
            visiting.add(service_id)
            for dependency in dependencies[service_id]:
                visit(dependency)
            visiting.remove(service_id)
            visited.add(service_id)

        for service_id in dependencies:
            visit(service_id)
