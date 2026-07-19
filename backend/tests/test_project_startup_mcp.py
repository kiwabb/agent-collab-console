from __future__ import annotations

from pathlib import Path

import pytest

from app.application.project_startup_mcp import ProjectStartupMcpService
from app.application.project_startup_service import ProjectStartupConfigService, StartupConfigInput
from app.domain.models import CodexSession, CodexTask, Project, ProjectStartupService


class StartupStore:
    def __init__(self) -> None:
        self.services: list[ProjectStartupService] = []
        self.task_id: str | None = None
        self.notes: list[str] = []
        self.env: dict[str, object] = {}

    async def replace_project_startup_services(
        self,
        project_id: str,
        task_id: str,
        services: list[ProjectStartupService],
        notes: list[str],
    ) -> None:
        self.services = services
        self.task_id = task_id
        self.notes = notes

    async def list_project_startup_services(
        self, project_id: str
    ) -> list[ProjectStartupService]:
        return self.services

    async def load_project_startup_config_meta(self, project_id: str) -> dict[str, object] | None:
        if self.task_id is None:
            return None
        return {
            "task_id": self.task_id,
            "notes": self.notes,
            "updated_at": None,
        }

    async def load_project_env_var(self, project_id: str, name: str) -> object | None:
        return self.env.get(name)

    async def save_project_env_var(
        self,
        project_id: str,
        name: str,
        value: str,
        *,
        secret: bool = False,
        source: str = "user",
    ) -> None:
        self.env[name] = {"value": value, "secret": secret, "source": source}


def _project(root: Path) -> Project:
    return Project(id="project-1", name="admin-demo", repo_path=str(root))


def _payload() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "save_startup_config",
            "arguments": {
                "services": [
                    {
                        "service_id": "backend",
                        "name": "Spring Boot Backend",
                        "working_directory": "backend",
                        "setup_command": "",
                        "run_command": "mvn spring-boot:run",
                        "access_url": "http://127.0.0.1:8080",
                        "readiness_probe": {
                            "kind": "http",
                            "url": "http://127.0.0.1:8080/api/health/ready",
                            "expected_status": 200,
                            "identity": {
                                "kind": "json_subset",
                                "expected": {
                                    "service": "admin-demo-backend",
                                    "status": "ready",
                                },
                            },
                        },
                        "depends_on": [],
                        "evidence": [
                            {"path": "backend/pom.xml", "detail": "Spring Boot Maven project"}
                        ],
                    },
                    {
                        "service_id": "frontend",
                        "name": "Vue Frontend",
                        "working_directory": "frontend",
                        "setup_command": "npm install",
                        "run_command": "npm run dev",
                        "access_url": "http://127.0.0.1:5173",
                        "readiness_probe": {
                            "kind": "http",
                            "url": "http://127.0.0.1:5173/",
                            "expected_status": 200,
                            "identity": {
                                "kind": "text_contains",
                                "text": "Northstar 管理后台",
                            },
                        },
                        "depends_on": ["backend"],
                        "evidence": [
                            {"path": "frontend/package.json", "detail": "Vite dev script"}
                        ],
                    },
                ],
                "env_vars": [],
                "notes": ["backend must start before frontend"],
            },
        },
    }


def _arguments(payload: dict[str, object]) -> dict[str, object]:
    params = payload["params"]
    assert isinstance(params, dict)
    arguments = params["arguments"]
    assert isinstance(arguments, dict)
    return arguments


def _result(body: dict[str, object] | None) -> dict[str, object]:
    assert body is not None
    result = body["result"]
    assert isinstance(result, dict)
    return result


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "pom.xml").write_text("<project />", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_mcp_saves_complete_multi_service_config(repository: Path) -> None:
    store = StartupStore()
    mcp = ProjectStartupMcpService(ProjectStartupConfigService(store))
    session = mcp.open_session(project=_project(repository), task_id="task-1")

    status, body = await mcp.handle(token=session.token, payload=_payload())

    assert status == 200
    assert _result(body)["isError"] is False
    assert [service.service_id for service in store.services] == ["backend", "frontend"]
    assert store.services[1].depends_on == ["backend"]
    assert store.services[0].readiness_probe is not None
    assert store.services[0].readiness_probe.url.endswith("/api/health/ready")
    assert store.services[1].readiness_probe is not None
    assert store.services[1].readiness_probe.identity.kind == "text_contains"
    result = mcp.finalized_result("task-1")
    assert result is not None
    services = result["services"]
    assert isinstance(services, list)
    assert len(services) == 2
    assert mcp.finalized_result("task-2") is None


@pytest.mark.asyncio
async def test_mcp_rejects_missing_evidence_without_overwriting_config(repository: Path) -> None:
    store = StartupStore()
    existing = ProjectStartupService(
        project_id="project-1",
        service_id="existing",
        name="Existing",
        working_directory=".",
        setup_command="",
        run_command="npm run dev",
    )
    store.services = [existing]
    mcp = ProjectStartupMcpService(ProjectStartupConfigService(store))
    session = mcp.open_session(project=_project(repository), task_id="task-1")
    payload = _payload()
    arguments = _arguments(payload)
    services = arguments["services"]
    assert isinstance(services, list)
    backend = services[0]
    assert isinstance(backend, dict)
    backend["evidence"] = [
        {"path": "backend/missing.xml", "detail": "missing"}
    ]

    status, body = await mcp.handle(token=session.token, payload=payload)

    assert status == 200
    assert _result(body)["isError"] is True
    assert store.services == [existing]
    assert mcp.finalized_result("task-1") is None


@pytest.mark.asyncio
async def test_mcp_rejects_missing_readiness_without_overwriting_config(repository: Path) -> None:
    store = StartupStore()
    mcp = ProjectStartupMcpService(ProjectStartupConfigService(store))
    session = mcp.open_session(project=_project(repository), task_id="task-1")
    payload = _payload()
    arguments = _arguments(payload)
    services = arguments["services"]
    assert isinstance(services, list)
    backend = services[0]
    assert isinstance(backend, dict)
    backend.pop("readiness_probe")

    _, body = await mcp.handle(token=session.token, payload=payload)

    assert _result(body)["isError"] is True
    assert store.services == []


@pytest.mark.asyncio
async def test_mcp_rejects_dependency_cycle(repository: Path) -> None:
    store = StartupStore()
    mcp = ProjectStartupMcpService(ProjectStartupConfigService(store))
    session = mcp.open_session(project=_project(repository), task_id="task-1")
    payload = _payload()
    arguments = _arguments(payload)
    services = arguments["services"]
    assert isinstance(services, list)
    backend = services[0]
    assert isinstance(backend, dict)
    backend["depends_on"] = ["frontend"]

    _, body = await mcp.handle(token=session.token, payload=payload)

    assert _result(body)["isError"] is True
    assert store.services == []


@pytest.mark.asyncio
async def test_mcp_rejects_unknown_token(repository: Path) -> None:
    mcp = ProjectStartupMcpService(ProjectStartupConfigService(StartupStore()))

    status, _ = await mcp.handle(token="wrong", payload=_payload())

    assert status == 401


@pytest.mark.asyncio
async def test_async_store_migrates_legacy_startup_service_as_invalid(repository: Path) -> None:
    import json
    import sqlite3

    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    db_path = repository / "legacy-console.db"
    store = AsyncSQLiteStore(str(db_path))
    migrated: AsyncSQLiteStore | None = None
    try:
        project = _project(repository)
        await store.save_project(project)
        await store._ensure_db()
        await store.close()
        with sqlite3.connect(db_path) as conn:
            conn.execute("ALTER TABLE project_startup_services RENAME TO old_startup_services")
            conn.execute(
                """
                CREATE TABLE project_startup_services (
                    project_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    working_directory TEXT NOT NULL,
                    setup_command TEXT NOT NULL DEFAULT '',
                    run_command TEXT NOT NULL,
                    access_url TEXT,
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (project_id, service_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO project_startup_services (
                    project_id, service_id, name, working_directory, setup_command,
                    run_command, access_url, depends_on_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    "backend",
                    "Backend",
                    "backend",
                    "",
                    "mvn spring-boot:run",
                    "http://127.0.0.1:8080",
                    json.dumps([]),
                    json.dumps(["backend/pom.xml"]),
                ),
            )
            conn.execute("DROP TABLE old_startup_services")
            conn.execute("UPDATE schema_version SET version = 12 WHERE id = 1")

        migrated = AsyncSQLiteStore(str(db_path))
        services = await migrated.list_project_startup_services(project.id)
        assert services[0].readiness_probe is None
        connection = await migrated._get_conn()
        version = await (
            await connection.execute("SELECT version FROM schema_version WHERE id = 1")
        ).fetchone()
        assert version is not None
        assert version[0] == 15
    finally:
        await store.close()
        if migrated is not None:
            await migrated.close()


@pytest.mark.asyncio
async def test_async_store_round_trips_startup_services(repository: Path) -> None:
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(str(repository / "console.db"))
    project = _project(repository)
    try:
        await store.save_project(project)
        workspace = CodexSession(
            id=project.id,
            title=project.name,
            cwd=project.repo_path,
            project_id=project.id,
            status="idle",
        )
        await store.save_codex_workspace(workspace)
        task = CodexTask(
            id="task-1",
            session_id=workspace.id,
            project_id=project.id,
            title="Analyze startup",
            prompt="Analyze",
            role="operations_engineer",
            task_kind="project_script_suggestion",
        )
        await store.save_codex_task(task)
        service = ProjectStartupConfigService(store)
        arguments = _arguments(_payload())

        await service.save_analysis(
            project=project,
            task_id=task.id,
            payload=service_payload(arguments),
        )
        loaded = await service.get_config(project)

        assert loaded["task_id"] == task.id
        loaded_services = loaded["services"]
        assert isinstance(loaded_services, list)
        assert all(isinstance(item, dict) for item in loaded_services)
        assert [item["service_id"] for item in loaded_services] == ["backend", "frontend"]
        assert loaded_services[1]["depends_on"] == ["backend"]
        assert loaded_services[0]["evidence"] == [
            {"path": "backend/pom.xml", "detail": "Spring Boot Maven project"}
        ]
        assert loaded_services[0]["readiness_probe"] == {
            "kind": "http",
            "url": "http://127.0.0.1:8080/api/health/ready",
            "expected_status": 200,
            "identity": {
                "kind": "json_subset",
                "expected": {"service": "admin-demo-backend", "status": "ready"},
            },
        }
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_async_store_treats_malformed_persisted_readiness_as_invalid(
    repository: Path,
) -> None:
    from app.adapters.async_sqlite_store import AsyncSQLiteStore

    store = AsyncSQLiteStore(str(repository / "malformed-readiness.db"))
    project = _project(repository)
    try:
        await store.save_project(project)
        connection = await store._get_conn()
        await connection.execute(
            """
            INSERT INTO project_startup_services (
                project_id, service_id, name, working_directory, setup_command,
                run_command, access_url, readiness_probe_json, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                "backend",
                "Backend",
                "backend",
                "",
                "mvn spring-boot:run",
                "http://127.0.0.1:8080",
                '{"kind":"http","url":"http://example.com","expected_status":200}',
                '[{"path":"backend/pom.xml","detail":"Spring project"}]',
            ),
        )
        await connection.commit()

        services = await store.list_project_startup_services(project.id)

        assert services[0].readiness_probe is None
        assert services[0].evidence[0].detail == "Spring project"
    finally:
        await store.close()


def service_payload(arguments: object) -> StartupConfigInput:
    return StartupConfigInput.model_validate(arguments)
