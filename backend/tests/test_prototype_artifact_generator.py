from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import pytest

import app.application.prototype_artifact_generator as artifact_generator_module
from app.application.prototype_artifact_generator import (
    PROTOTYPE_ARTIFACT_MANIFEST_MAX_BYTES,
    PrototypeArtifactActivity,
    PrototypeArtifactError,
    PrototypeArtifactGenerator,
    PrototypeArtifactRequest,
    prototype_staging_relative_path,
    validate_prototype_artifact,
)
from app.domain.models import (
    CodexSession,
    CodexTask,
    ExecutionProcess,
    LogEvent,
    Project,
    RuntimeCatalog,
    RuntimeExecutorConfig,
)
from app.domain.project_evidence import ProjectSurfaceManifest, PrototypeCandidate

HTML = "<!DOCTYPE html><html><head></head><body><h1>VideoNote</h1></body></html>"


def _write_artifact(
    worktree: Path,
    run_item_id: str,
    raw: bytes,
    *,
    artifact_path: str | None = None,
    checksum: str | None = None,
    byte_size: int | None = None,
    extra: dict[str, object] | None = None,
) -> tuple[Path, str]:
    relative = artifact_path or prototype_staging_relative_path(run_item_id)
    path = worktree / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    manifest: dict[str, object] = {
        "schema_version": "prototype-artifact/v1",
        "artifact_path": relative,
        "sha256": checksum or "sha256:" + hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw) if byte_size is None else byte_size,
    }
    if extra:
        manifest.update(extra)
    return path, json.dumps(manifest)


def test_validate_prototype_artifact_accepts_strict_manifest(tmp_path: Path) -> None:
    _, manifest = _write_artifact(
        tmp_path,
        "item-1",
        (
            b'<!DOCTYPE html><html><head><script src="https://cdn.tailwindcss.com">'
            b'</script></head><body><svg xmlns="http://www.w3.org/2000/svg">'
            b"</svg></body></html>"
        ),
    )

    artifact = validate_prototype_artifact(
        worktree_path=tmp_path,
        expected_artifact_path=prototype_staging_relative_path("item-1"),
        manifest_text=manifest,
        max_bytes=10_000,
    )

    assert artifact.html.endswith("</html>")
    assert artifact.manifest.schema_version == "prototype-artifact/v1"


def test_validate_prototype_artifact_accepts_allowed_font_origins(tmp_path: Path) -> None:
    _, manifest = _write_artifact(
        tmp_path,
        "item-fonts",
        (
            b'<!DOCTYPE html><html><head><link rel="preconnect" '
            b'href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2" '
            b'rel="stylesheet"><link rel="preconnect" href="https://fonts.gstatic.com">'
            b"</head><body></body></html>"
        ),
    )

    artifact = validate_prototype_artifact(
        worktree_path=tmp_path,
        expected_artifact_path=prototype_staging_relative_path("item-fonts"),
        manifest_text=manifest,
        max_bytes=10_000,
    )

    assert "fonts.googleapis.com" in artifact.html


def test_validate_prototype_artifact_rejects_oversized_manifest(tmp_path: Path) -> None:
    _, manifest = _write_artifact(tmp_path, "item-manifest-size", HTML.encode())
    oversized = manifest + (" " * PROTOTYPE_ARTIFACT_MANIFEST_MAX_BYTES)

    with pytest.raises(PrototypeArtifactError, match="manifest exceeds the size limit"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-manifest-size"),
            manifest_text=oversized,
            max_bytes=10_000,
        )


def test_validate_prototype_artifact_rejects_path_traversal(tmp_path: Path) -> None:
    manifest = json.dumps(
        {
            "schema_version": "prototype-artifact/v1",
            "artifact_path": "../outside.html",
            "sha256": "sha256:" + "0" * 64,
            "byte_size": 1,
        }
    )

    with pytest.raises(PrototypeArtifactError, match="path is unsafe"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path="../outside.html",
            manifest_text=manifest,
            max_bytes=10_000,
        )


def test_validate_prototype_artifact_rejects_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-prototype.html"
    outside.write_text(HTML, encoding="utf-8")
    relative = prototype_staging_relative_path("item-link")
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True)
    artifact.symlink_to(outside)
    raw = outside.read_bytes()
    manifest = json.dumps(
        {
            "schema_version": "prototype-artifact/v1",
            "artifact_path": relative,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw),
        }
    )

    with pytest.raises(PrototypeArtifactError, match="symlink"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=relative,
            manifest_text=manifest,
            max_bytes=10_000,
        )


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (b"\xff\xfe", "valid UTF-8"),
        (b"<!DOCTYPE html><html><body>truncated", "complete HTML"),
    ],
)
def test_validate_prototype_artifact_rejects_invalid_content(
    tmp_path: Path,
    raw: bytes,
    match: str,
) -> None:
    _, manifest = _write_artifact(tmp_path, "item-content", raw)

    with pytest.raises(PrototypeArtifactError, match=match):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-content"),
            manifest_text=manifest,
            max_bytes=10_000,
        )


def test_validate_prototype_artifact_rejects_checksum_and_extra_fields(
    tmp_path: Path,
) -> None:
    _, wrong_checksum = _write_artifact(
        tmp_path,
        "item-checksum",
        HTML.encode(),
        checksum="sha256:" + "0" * 64,
    )
    with pytest.raises(PrototypeArtifactError, match="checksum"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-checksum"),
            manifest_text=wrong_checksum,
            max_bytes=10_000,
        )

    _, extra_field = _write_artifact(
        tmp_path,
        "item-extra",
        HTML.encode(),
        extra={"html": HTML},
    )
    with pytest.raises(PrototypeArtifactError, match="invalid manifest"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-extra"),
            manifest_text=extra_field,
            max_bytes=10_000,
        )


def test_validate_prototype_artifact_rejects_size_and_external_origin(
    tmp_path: Path,
) -> None:
    _, oversized = _write_artifact(tmp_path, "item-size", HTML.encode())
    with pytest.raises(PrototypeArtifactError, match="size limit"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-size"),
            manifest_text=oversized,
            max_bytes=10,
        )

    external_html = (
        '<!DOCTYPE html><html><body><img src="https://evil.example/leak.png"></body></html>'
    )
    _, external = _write_artifact(
        tmp_path,
        "item-external",
        external_html.encode(),
    )
    with pytest.raises(PrototypeArtifactError, match="non-whitelisted"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-external"),
            manifest_text=external,
            max_bytes=10_000,
        )


def test_validate_prototype_artifact_allows_inert_external_url_copy(tmp_path: Path) -> None:
    inert_html = (
        '<!DOCTYPE html><html><body><a href="https://github.com/example">Docs</a>'
        '<input value="https://xxx.feishu.cn/webhook/example">'
        "<p>Webhook: https://example.com/hook</p></body></html>"
    )
    _, manifest = _write_artifact(tmp_path, "item-inert-url", inert_html.encode())

    artifact = validate_prototype_artifact(
        worktree_path=tmp_path,
        expected_artifact_path=prototype_staging_relative_path("item-inert-url"),
        manifest_text=manifest,
        max_bytes=10_000,
    )

    assert artifact.html == inert_html


@pytest.mark.parametrize(
    "external_html",
    [
        "<!DOCTYPE html><html><style>body{background:url(https://evil.example/a.png)}</style></html>",
        "<!DOCTYPE html><html><script>fetch('https://evil.example/data')</script></html>",
    ],
)
def test_validate_prototype_artifact_rejects_css_and_script_network_urls(
    tmp_path: Path,
    external_html: str,
) -> None:
    _, manifest = _write_artifact(tmp_path, "item-network-url", external_html.encode())

    with pytest.raises(PrototypeArtifactError, match="non-whitelisted"):
        validate_prototype_artifact(
            worktree_path=tmp_path,
            expected_artifact_path=prototype_staging_relative_path("item-network-url"),
            manifest_text=manifest,
            max_bytes=10_000,
        )


@pytest.mark.asyncio
async def test_ui_engineer_availability_fails_when_runtime_launch_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "false")
    generator = PrototypeArtifactGenerator(
        store=_Store(),
        task_runner=_TaskRunner(_Store()),
        worktree_manager=_WorktreeManager(tmp_path),
        claude_availability_probe=lambda: pytest.fail(
            "CLI probe must not run when launch is disabled"
        ),
        evidence_scanner=_EvidenceScanner(),
    )

    with pytest.raises(PrototypeArtifactError, match="runtime launch is disabled"):
        await generator.ensure_available()


@pytest.mark.asyncio
async def test_ui_engineer_availability_requires_claude_cli_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    store = _Store()
    probe_calls = 0

    def unavailable() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return False

    generator = PrototypeArtifactGenerator(
        store=store,
        task_runner=_TaskRunner(store),
        worktree_manager=_WorktreeManager(tmp_path),
        claude_availability_probe=unavailable,
        evidence_scanner=_EvidenceScanner(),
    )

    with pytest.raises(PrototypeArtifactError, match="available Claude CLI command"):
        await generator.ensure_available()

    assert probe_calls == 1
    assert store.tasks == {}
    assert store.workspaces == {}


class _Store:
    def __init__(self) -> None:
        self.tasks: dict[str, CodexTask] = {}
        self.workspaces: dict[str, CodexSession] = {}
        self.logs: list[LogEvent] = []
        self.catalog = RuntimeCatalog(
            executors=[
                RuntimeExecutorConfig(
                    id="claude",
                    label="Claude Code + MiniMax",
                    enabled=True,
                    executor_type="claude",
                    api_endpoint="https://api.minimax.example/anthropic",
                    api_key="test-key",
                    default_model="MiniMax-M3",
                )
            ]
        )

    async def load_runtime_catalog(self) -> RuntimeCatalog | None:
        return self.catalog

    async def save_runtime_catalog(self, catalog: RuntimeCatalog) -> None:
        self.catalog = catalog

    async def load_codex_workspace(self, workspace_id: str) -> CodexSession | None:
        return self.workspaces.get(workspace_id)

    async def save_codex_workspace(self, workspace: CodexSession) -> None:
        self.workspaces[workspace.id] = workspace

    async def list_codex_workspaces(
        self,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {"id": workspace.id, "project_id": workspace.project_id}
            for workspace in self.workspaces.values()
            if project_id is None or workspace.project_id == project_id
        ]

    async def save_codex_task(self, task: CodexTask) -> None:
        self.tasks[task.id] = task

    async def load_codex_task(self, task_id: str) -> CodexTask | None:
        return self.tasks.get(task_id)

    async def load_log_events(
        self,
        session_id: str,
        task_id: str | None = None,
        execution_process_id: str | None = None,
        limit: int = 1000,
        reverse: bool = False,
    ) -> list[LogEvent]:
        del session_id, limit
        events = [
            event
            for event in self.logs
            if (task_id is None or event.task_id == task_id)
            and (execution_process_id is None or event.execution_process_id == execution_process_id)
        ]
        return list(reversed(events)) if reverse else events


class _GitInspector:
    async def status_porcelain(self, worktree_path: str | Path) -> str:
        del worktree_path
        return ""

    async def worktree_diff(self, worktree_path: str | Path, base_branch: str) -> str:
        del worktree_path, base_branch
        return ""

    async def head_commit(self, worktree_path: str | Path) -> str:
        del worktree_path
        return "head-1"


class _WorktreeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git = _GitInspector()
        self.cleaned = False

    async def prepare_prototype_worktree(
        self,
        project: Project,
        run_item_id: str,
        *,
        source_paths: tuple[str, ...] = (),
    ) -> tuple[str, str, str]:
        del project, run_item_id, source_paths
        return "prototype/test", str(self.root), "base-1"

    async def cleanup_prototype_worktree(
        self,
        project: Project,
        run_item_id: str,
    ) -> None:
        del project, run_item_id
        self.cleaned = True


class _EvidenceScanner:
    def scan_project(self, project: Project) -> ProjectSurfaceManifest:
        return ProjectSurfaceManifest(
            repository_root=project.repo_path,
            packages=(),
            candidates=(
                PrototypeCandidate(
                    candidate_id="candidate-1",
                    title="VideoNote",
                    route_patterns=("/",),
                    surface_kind="web",
                    package_root="",
                    framework_hint="react-router",
                    primary_source_path="src/page.tsx",
                    source_paths=("src/page.tsx",),
                    layout_paths=(),
                    evidence=(),
                    confidence="high",
                    source_hash="sha256:source",
                ),
            ),
        )


class _TaskRunner:
    def __init__(
        self,
        store: _Store,
        *,
        modify_source: bool = False,
        artifact_html: str = HTML,
        planning_result: str = '{"project_context":{},"items":[]}',
        write_chunks: list[str] | None = None,
        bash_commands: list[str] | None = None,
        failure_result: str | None = None,
        success_result_override: str | None = None,
    ) -> None:
        self.store = store
        self.modify_source = modify_source
        self.artifact_html = artifact_html
        self.planning_result = planning_result
        self.write_chunks = write_chunks or [artifact_html]
        self.bash_commands = bash_commands or []
        self.failure_result = failure_result
        self.success_result_override = success_result_override

    async def start_task_run(
        self,
        task: CodexTask,
        *,
        wait_for_completion: bool = False,
        execution_started_callback: Callable[[CodexTask, ExecutionProcess], Awaitable[None]]
        | None = None,
        command_args_override: list[str] | None = None,
    ) -> ExecutionProcess:
        del command_args_override
        assert wait_for_completion is True
        assert task.executor == "claude"
        assert task.provider is None
        assert task.model is None
        process = ExecutionProcess(
            id="process-1",
            task_id=task.id,
            session_id=task.session_id,
            status="Running",
            executor="claude",
            model="MiniMax-M3",
            started_at=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        task.last_execution_process_id = process.id
        task.status = "running"
        await self.store.save_codex_task(task)
        assert execution_started_callback is not None
        await execution_started_callback(task, process)
        await asyncio.sleep(0.05)
        self.store.logs.append(
            LogEvent(
                id="log-1",
                session_id=task.session_id,
                task_id=task.id,
                execution_process_id=process.id,
                stream="stdout",
                content="streaming tool activity",
                created_at=datetime.now(),
            )
        )
        await asyncio.sleep(1.05)
        if self.modify_source:
            (Path(task.workspace_path or "") / "src/page.tsx").write_text(
                "export const changed = true;\n",
                encoding="utf-8",
            )
        if task.task_kind == "prototype_planning":
            task.result = self.planning_result
            task.status = "done"
            await self.store.save_codex_task(task)
            process.status = "Completed"
            process.exit_code = 0
            process.completed_at = datetime.now()
            return process
        if self.failure_result is not None:
            task.result = self.failure_result
            task.status = "failed"
            await self.store.save_codex_task(task)
            process.status = "Failed"
            process.exit_code = 1
            process.completed_at = datetime.now()
            return process
        artifact_path = prototype_staging_relative_path("item-generate")
        for index, command in enumerate(self.bash_commands):
            self.store.logs.append(
                LogEvent(
                    id=f"bash-tool-log-{index}",
                    session_id=task.session_id,
                    task_id=task.id,
                    execution_process_id=process.id,
                    stream="tool_use",
                    content=json.dumps(
                        {
                            "kind": "tool_use",
                            "tool_use_id": f"bash-tool-{index}",
                            "tool_name": "Bash",
                            "input": {"command": command},
                        }
                    ),
                    created_at=datetime.now(),
                )
            )
            self.store.logs.append(
                LogEvent(
                    id=f"bash-result-log-{index}",
                    session_id=task.session_id,
                    task_id=task.id,
                    execution_process_id=process.id,
                    stream="tool_result",
                    content=json.dumps(
                        {
                            "kind": "tool_result",
                            "tool_use_id": f"bash-tool-{index}",
                            "output": "ok",
                            "is_error": False,
                        }
                    ),
                    created_at=datetime.now(),
                )
            )
        for index, chunk in enumerate(self.write_chunks):
            tool_input: dict[str, object]
            if index == 0:
                tool_name = "Write"
                tool_input = {"file_path": artifact_path, "content": chunk}
            else:
                tool_name = "Edit"
                tool_input = {
                    "file_path": artifact_path,
                    "old_string": f"<!-- prototype-chunk-{index} -->",
                    "new_string": chunk,
                }
            self.store.logs.append(
                LogEvent(
                    id=f"tool-log-{index}",
                    session_id=task.session_id,
                    task_id=task.id,
                    execution_process_id=process.id,
                    stream="tool_use",
                    content=json.dumps(
                        {
                            "kind": "tool_use",
                            "tool_use_id": f"tool-{index}",
                            "tool_name": tool_name,
                            "input": tool_input,
                        }
                    ),
                    created_at=datetime.now(),
                )
            )
            self.store.logs.append(
                LogEvent(
                    id=f"tool-result-log-{index}",
                    session_id=task.session_id,
                    task_id=task.id,
                    execution_process_id=process.id,
                    stream="tool_result",
                    content=json.dumps(
                        {
                            "kind": "tool_result",
                            "tool_use_id": f"tool-{index}",
                            "output": "ok",
                            "is_error": False,
                        }
                    ),
                    created_at=datetime.now(),
                )
            )
        _, manifest = _write_artifact(
            Path(task.workspace_path or ""),
            "item-generate",
            self.artifact_html.encode(),
        )
        task.result = self.success_result_override or manifest
        task.status = "done"
        await self.store.save_codex_task(task)
        process.status = "Completed"
        process.exit_code = 0
        process.completed_at = datetime.now()
        return process


def _generator_fixture(
    tmp_path: Path,
    *,
    modify_source: bool = False,
    artifact_html: str = HTML,
    planning_result: str = '{"project_context":{},"items":[]}',
    write_chunks: list[str] | None = None,
    bash_commands: list[str] | None = None,
    failure_result: str | None = None,
    success_result_override: str | None = None,
    max_artifact_bytes: int = 10_000,
) -> tuple[PrototypeArtifactGenerator, _Store, _WorktreeManager, PrototypeArtifactRequest]:
    worktree = tmp_path / "worktree"
    (worktree / "src").mkdir(parents=True)
    (worktree / "src/page.tsx").write_text("export const Page = 1;\n", encoding="utf-8")
    store = _Store()
    manager = _WorktreeManager(worktree)
    project = Project(
        id="project-1",
        name="VideoNote",
        repo_path=str(tmp_path / "primary"),
        default_branch="main",
    )
    generator = PrototypeArtifactGenerator(
        store=store,
        task_runner=_TaskRunner(
            store,
            modify_source=modify_source,
            artifact_html=artifact_html,
            planning_result=planning_result,
            write_chunks=write_chunks,
            bash_commands=bash_commands,
            failure_result=failure_result,
            success_result_override=success_result_override,
        ),
        worktree_manager=manager,
        claude_availability_probe=lambda: True,
        evidence_scanner=_EvidenceScanner(),
        max_artifact_bytes=max_artifact_bytes,
    )
    request = PrototypeArtifactRequest(
        project=project,
        run_item_id="item-generate",
        candidate_id="candidate-1",
        source_hash="sha256:source",
        title="VideoNote",
        output_locale="zh-CN",
        source_paths=("src/page.tsx",),
        target_routes=("/settings/feishu",),
    )
    return generator, store, manager, request


@pytest.mark.asyncio
async def test_planner_uses_claude_ui_engineer_in_isolated_read_only_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    planning_result = '{"project_context":{"product_summary":"视频工作区"},"items":[]}'
    generator, store, manager, request = _generator_fixture(
        tmp_path,
        planning_result=planning_result,
    )

    result = await generator.plan(
        project=request.project,
        plan_id="prototype-plan-123",
        prompt="You are the prototype UI engineer. Return JSON only.",
        source_paths=request.source_paths,
    )

    assert result == planning_result
    assert manager.cleaned is True
    planning_tasks = [
        task for task in store.tasks.values() if task.task_kind == "prototype_planning"
    ]
    assert len(planning_tasks) == 1
    task = planning_tasks[0]
    assert task.role == "prototype_ui_engineer"
    assert task.executor == "claude"
    assert task.workspace_path == str(manager.root)
    assert task.prompt == "You are the prototype UI engineer. Return JSON only."


@pytest.mark.asyncio
async def test_scoped_conversation_task_uses_fresh_claude_task_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    generator, store, manager, request = _generator_fixture(
        tmp_path,
        success_result_override="submitted",
    )

    result = await generator.execute_scoped_task(
        project=request.project,
        scope_id="edit-run-1",
        prompt="Submit one structured prototype outcome through MCP.",
        source_paths=(),
        phase="prototype_ai_edit",
        task_kind="conversation_edit",
        task_title="Edit structured prototype",
        task_id="prototype-ai-task-fixed",
        mcp_config='{"mcpServers":{}}',
    )

    assert result.task_id == "prototype-ai-task-fixed"
    assert result.execution_process_id == "process-1"
    assert result.assistant_result == "submitted"
    task = store.tasks[result.task_id]
    assert task.role == "prototype_ui_engineer"
    assert task.executor == "claude"
    assert task.task_kind == "conversation_edit"
    assert task.phase == "prototype_ai_edit"
    assert task.workspace_path == str(manager.root)
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_generator_uses_claude_manifest_and_streams_runtime_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    generator, store, manager, request = _generator_fixture(tmp_path)
    activities: list[PrototypeArtifactActivity] = []

    async def record(activity: PrototypeArtifactActivity) -> None:
        activities.append(activity)

    result = await generator.generate(request, activity_callback=record)

    assert result.task_id.startswith("prototype-ui-task-")
    assert result.execution_process_id == "process-1"
    assert result.html == HTML
    assert manager.cleaned is True
    assert len(store.workspaces) == 1
    workspace = next(iter(store.workspaces.values()))
    assert workspace.id.startswith("prototype-workspace-")
    assert workspace.project_id == request.project.id
    assert workspace.cwd == request.project.repo_path
    generated_task = store.tasks[result.task_id]
    assert "Preserve the source page's existing visible copy and language exactly" in (
        generated_task.prompt
    )
    assert "Use any available tools you judge appropriate" in generated_task.prompt
    assert "backend validates the final artifact rather than your tool sequence" in (
        generated_task.prompt
    )
    assert "Mandatory bounded-write protocol" not in generated_task.prompt
    assert "one Write call for a compact HTML skeleton" not in generated_task.prompt
    assert "Write.content" not in generated_task.prompt
    assert "final assistant response" in generated_task.prompt
    assert 'Target routes: ["/settings/feishu"]' in generated_task.prompt
    assert "Locate the router entries" in generated_task.prompt
    assert "follow their imports" in generated_task.prompt
    assert "shared layout, navigation, styles, design tokens, and assets" in generated_task.prompt
    assert "Search and read any project files you need" in generated_task.prompt
    assert "no precomputed source-file list is provided" in generated_task.prompt
    assert "data-prototype-route" in generated_task.prompt
    assert 'external http/https destinations with href="#"' in generated_task.prompt
    assert "representative sample rows" in generated_task.prompt
    assert "candidate-1" not in generated_task.prompt
    assert "sha256:source" not in generated_task.prompt
    assert "src/page.tsx" not in generated_task.prompt
    assert "Restore brief" not in generated_task.prompt
    assert "at most 12 combined Read/Bash inspection calls" not in generated_task.prompt
    assert "do not search the whole repository" not in generated_task.prompt
    assert [activity.phase for activity in activities[:3]] == [
        "preparing",
        "worktree_ready",
        "running",
    ]
    assert any(
        activity.phase == "running"
        and activity.execution_process_id == "process-1"
        and (activity.output_chars or 0) >= len("streaming tool activity")
        for activity in activities
    )
    assert activities[-2].phase == "validating"
    assert activities[-1].phase == "complete"
    assert activities[-1].output_chars == len(HTML)


@pytest.mark.asyncio
async def test_generator_audits_only_validated_artifact_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    html_sentinel = "AUDIT_HTML_SENTINEL_DO_NOT_RECORD"
    command_sentinel = "AUDIT_COMMAND_SENTINEL_DO_NOT_RECORD"
    artifact_html = f"<!DOCTYPE html><html><head></head><body><p>{html_sentinel}</p></body></html>"
    events: list[dict[str, object]] = []
    monkeypatch.setattr(artifact_generator_module, "record_event", events.append)
    generator, store, _, request = _generator_fixture(
        tmp_path,
        artifact_html=artifact_html,
        bash_commands=[command_sentinel],
    )

    result = await generator.generate(request)

    assert events == [
        {
            "type": "prototype_artifact_validation",
            "payload": {
                "task_id": result.task_id,
                "execution_process_id": result.execution_process_id,
                "artifact_path": prototype_staging_relative_path(request.run_item_id),
                "sha256": "sha256:" + hashlib.sha256(artifact_html.encode()).hexdigest(),
                "byte_size": len(artifact_html.encode()),
                "status": "passed",
                "validation_result": "passed",
                "error": None,
            },
        }
    ]
    audit_text = json.dumps(events)
    generated_task = store.tasks[result.task_id]
    assert html_sentinel not in audit_text
    assert command_sentinel not in audit_text
    assert "streaming tool activity" not in audit_text
    assert "schema_version" not in audit_text
    assert generated_task.prompt not in audit_text
    assert "src/page.tsx" not in audit_text


@pytest.mark.asyncio
async def test_generator_audits_generation_failure_without_runtime_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    runtime_sentinel = "<!DOCTYPE html><html>AUDIT_FAILURE_SENTINEL</html>"
    events: list[dict[str, object]] = []
    monkeypatch.setattr(artifact_generator_module, "record_event", events.append)
    generator, _, _, request = _generator_fixture(
        tmp_path,
        failure_result=f"runtime failed after tool output: {runtime_sentinel}",
    )

    with pytest.raises(PrototypeArtifactError, match="prototype UI engineer failed"):
        await generator.generate(request)

    assert len(events) == 1
    payload = events[0]["payload"]
    assert isinstance(payload, dict)
    assert payload == {
        "task_id": payload["task_id"],
        "execution_process_id": "process-1",
        "artifact_path": prototype_staging_relative_path(request.run_item_id),
        "sha256": None,
        "byte_size": None,
        "status": "failed",
        "validation_result": "failed",
        "error": "generation_failed",
    }
    audit_text = json.dumps(events)
    assert runtime_sentinel not in audit_text
    assert "tool output" not in audit_text
    assert "src/page.tsx" not in audit_text


@pytest.mark.asyncio
async def test_generator_surfaces_api_error_instead_of_manifest_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    generator, _, _, request = _generator_fixture(
        tmp_path,
        success_result_override="API Error: Request rejected (429) · token plan exhausted",
    )

    with pytest.raises(PrototypeArtifactError, match=r"prototype UI engineer failed: API Error"):
        await generator.generate(request)


@pytest.mark.asyncio
async def test_generator_audits_artifact_validation_failure_without_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    html_sentinel = "AUDIT_INVALID_HTML_SENTINEL"
    artifact_html = (
        "<!DOCTYPE html><html><body>"
        f'<img alt="{html_sentinel}" src="https://blocked.example/image.png">'
        "</body></html>"
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(artifact_generator_module, "record_event", events.append)
    generator, _, _, request = _generator_fixture(tmp_path, artifact_html=artifact_html)

    with pytest.raises(PrototypeArtifactError, match="non-whitelisted external origin"):
        await generator.generate(request)

    assert len(events) == 1
    payload = events[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["execution_process_id"] == "process-1"
    assert payload["sha256"] is None
    assert payload["byte_size"] is None
    assert payload["validation_result"] == "failed"
    assert payload["error"] == "artifact_validation_failed"
    assert html_sentinel not in json.dumps(events)
    assert "blocked.example" not in json.dumps(events)


@pytest.mark.asyncio
async def test_generator_accepts_large_html_without_inspecting_tool_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    first_section = "<section>" + ("a" * 20_000) + "</section>"
    second_section = "<section>" + ("b" * 20_000) + "</section>"
    large_html = (
        "<!DOCTYPE html><html><head></head><body>"
        + first_section
        + second_section
        + "</body></html>"
    )
    generator, _, manager, request = _generator_fixture(
        tmp_path,
        artifact_html=large_html,
        write_chunks=[large_html],
        max_artifact_bytes=50_000,
    )

    result = await generator.generate(request)

    assert result.html == large_html
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_generator_ignores_how_claude_created_the_valid_final_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    artifact_path = prototype_staging_relative_path("item-generate")
    generator, _, manager, request = _generator_fixture(
        tmp_path,
        write_chunks=["this deliberately does not match the final artifact"],
        bash_commands=[
            f'python3 -c \'open("{artifact_path}", "w").write("HTML")\'',
            f"shasum -a 256 {artifact_path} | cat",
        ],
    )

    result = await generator.generate(request)

    assert result.html == HTML
    assert manager.cleaned is True


@pytest.mark.asyncio
async def test_generator_public_preflight_rejects_non_claude_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    generator, store, _, _ = _generator_fixture(tmp_path)
    store.catalog.executors[0].executor_type = "codex"

    with pytest.raises(PrototypeArtifactError, match="enabled Claude executor"):
        await generator.ensure_available()


@pytest.mark.asyncio
async def test_generator_rejects_project_source_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LAUNCH_ENABLED", "true")
    events: list[dict[str, object]] = []
    monkeypatch.setattr(artifact_generator_module, "record_event", events.append)
    generator, _, manager, request = _generator_fixture(tmp_path, modify_source=True)

    with pytest.raises(PrototypeArtifactError, match="modified project source"):
        await generator.generate(request)

    assert manager.cleaned is True
    assert len(events) == 1
    payload = events[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["execution_process_id"] == "process-1"
    assert payload["sha256"] == "sha256:" + hashlib.sha256(HTML.encode()).hexdigest()
    assert payload["byte_size"] == len(HTML.encode())
    assert payload["validation_result"] == "failed"
    assert payload["error"] == "source_integrity_failed"
    assert "src/page.tsx" not in json.dumps(events)
