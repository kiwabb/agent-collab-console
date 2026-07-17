from __future__ import annotations  # noqa: I001

import asyncio
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from app.application.git_service import GitService
from app.application.worktree_manager import AgentMergeSpec, WorktreeError, WorktreeManager
from app.domain.models import CodexIssue, CodexTask, Project
from app.domain.structured_prototype_generation import (
    PrototypeGenerationCommittedHeadCapture,
    PrototypeGenerationSourceSnapshot,
)


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not available")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _git_output(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_snapshot(
    capture: PrototypeGenerationCommittedHeadCapture,
) -> PrototypeGenerationSourceSnapshot:
    return PrototypeGenerationSourceSnapshot(
        source_policy="committed_head_v1",
        source_snapshot_object_hash="sha256:" + "1" * 64,
        source_fingerprint="sha256:" + "2" * 64,
        source_snapshot_ref=capture.snapshot_ref,
        repository_object_format=capture.repository_object_format,
        worktree_base_commit=capture.worktree_base_commit,
        repository_project_prefix=capture.repository_project_prefix,
        repository_tree_object_id=capture.repository_tree_object_id,
        source_file_exclusion_policy=capture.source_file_exclusion_policy,
        working_tree_dirty=capture.working_tree_dirty,
        excluded_tracked_change_count=capture.excluded_tracked_change_count,
        excluded_untracked_count=capture.excluded_untracked_count,
        excluded_sensitive_file_count=capture.excluded_sensitive_file_count,
        excluded_status_hash=capture.excluded_status_hash,
    )


@pytest.fixture
def project(tmp_path: Path) -> Project:
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", "-b", "main", cwd=r)
    _git("config", "user.email", "test@example.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("hello")
    _git("add", "README.md", cwd=r)
    _git("commit", "-m", "init", cwd=r)
    return Project(
        id="p1",
        name="demo",
        repo_path=str(r),
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def manager() -> WorktreeManager:
    return WorktreeManager(GitService())


@pytest.mark.asyncio
async def test_prepare_issue_worktree_creates_branch_and_path(
    project: Project, manager: WorktreeManager
):
    issue = CodexIssue(
        id="issue-deadbeef", session_id="s1", project_id=project.id, title="Add foo feature"
    )
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    assert branch.startswith(f"issue/{issue.id[:8]}-")
    assert "add-foo" in branch
    assert Path(path).exists()
    assert base == "main"


@pytest.mark.asyncio
async def test_prepare_issue_worktree_is_idempotent(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-aaaa1111", session_id="s1", project_id=project.id, title="t")
    b1, p1, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = b1
    issue.git_worktree_path = p1
    b2, p2, _ = await manager.prepare_issue_worktree(project, issue)
    assert (b1, p1) == (b2, p2)


@pytest.mark.asyncio
async def test_merge_issue_squashes_changes_back_to_base(
    project: Project, manager: WorktreeManager
):
    issue = CodexIssue(id="issue-bbbb2222", session_id="s1", project_id=project.id, title="feat")
    _, path, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = f"issue/{issue.id[:8]}-feat"
    issue.git_worktree_path = path
    issue.git_base_branch = "main"
    (Path(path) / "newfile.txt").write_text("data")
    _git("add", "newfile.txt", cwd=Path(path))
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", "work", cwd=Path(path))
    result = await manager.merge_issue(project, issue, message="merge feat")
    log = subprocess.run(
        ["git", "log", "--oneline", "main"],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "merge feat" in log
    assert issue.git_merge_status == "merged"
    assert issue.git_last_commit_sha == result["sha"]


@pytest.mark.asyncio
async def test_cleanup_issue_worktree_removes_directory(project: Project, manager: WorktreeManager):
    issue = CodexIssue(id="issue-cccc3333", session_id="s1", project_id=project.id, title="x")
    _, path, _ = await manager.prepare_issue_worktree(project, issue)
    issue.git_worktree_path = path
    await manager.cleanup_issue_worktree(project, issue)
    assert not Path(path).exists()


@pytest.mark.asyncio
async def test_prepare_chat_task_worktree(project: Project, manager: WorktreeManager):
    task = CodexTask(
        id="task-dddd4444", session_id="s1", project_id=project.id, title="quick fix", prompt="..."
    )
    branch, path, base = await manager.prepare_chat_task_worktree(project, task)
    assert branch.startswith("chat/task-ddd")
    assert Path(path).exists()
    assert base == "main"


@pytest.mark.asyncio
async def test_prototype_worktree_snapshots_dirty_source_and_cleans_branch(
    project: Project,
    manager: WorktreeManager,
) -> None:
    repo = Path(project.repo_path)
    (repo / "README.md").write_text("dirty tracked source\n", encoding="utf-8")
    (repo / "untracked-page.tsx").write_text("export const Page = 1;\n", encoding="utf-8")
    primary_status_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    branch, path, base_revision = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "prototype-generation-item-123",
        source_paths=("README.md", "untracked-page.tsx"),
    )

    worktree = Path(path)
    assert branch.startswith("prototype/")
    assert base_revision != project.default_branch
    assert (worktree / "README.md").read_text(encoding="utf-8") == "dirty tracked source\n"
    assert (worktree / "untracked-page.tsx").read_text(encoding="utf-8") == (
        "export const Page = 1;\n"
    )
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == primary_status_before
    )

    await manager.cleanup_prototype_ui_engineer_worktree(project, "prototype-generation-item-123")

    assert not worktree.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert branches.strip() == ""


@pytest.mark.asyncio
async def test_prototype_worktree_with_no_source_paths_ignores_dirty_and_untracked_state(
    project: Project,
    manager: WorktreeManager,
) -> None:
    repo = Path(project.repo_path)
    (repo / "README.md").write_text("dirty tracked source\n", encoding="utf-8")
    unrelated_worktree = repo / "examples" / "admin-demo-worktrees" / "prototype-existing"
    unrelated_worktree.mkdir(parents=True)
    _git("init", "-b", "main", cwd=unrelated_worktree)
    (unrelated_worktree / "artifact.txt").write_text("unrelated\n", encoding="utf-8")

    _, path, _ = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "requirements-only-generation",
        source_paths=(),
    )
    try:
        worktree = Path(path)
        assert (worktree / "README.md").read_text(encoding="utf-8") == "hello"
        assert not (worktree / "examples").exists()
    finally:
        await manager.cleanup_prototype_ui_engineer_worktree(project, "requirements-only-generation")


@pytest.mark.asyncio
async def test_prototype_worktree_does_not_merge_framework_hooks_into_project_settings(
    project: Project,
    manager: WorktreeManager,
) -> None:
    repo = Path(project.repo_path)
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    project_settings = '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[]}]}}\n'
    (claude_dir / "settings.json").write_text(project_settings, encoding="utf-8")
    (repo / "CLAUDE.md").write_text("Untrusted project instructions.\n", encoding="utf-8")
    (repo / ".mcp.json").write_text('{"mcpServers":{"untrusted":{}}}\n', encoding="utf-8")
    _git("add", ".claude/settings.json", "CLAUDE.md", ".mcp.json", cwd=repo)
    _git("commit", "-m", "add untrusted claude config fixture", cwd=repo)

    _, path, _ = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "prototype-untrusted-settings",
    )
    try:
        worktree = Path(path)
        assert (worktree / ".claude/settings.json").read_text(encoding="utf-8") == project_settings
        assert not (worktree / ".claude/hooks/limit_read.py").exists()
    finally:
        await manager.cleanup_prototype_ui_engineer_worktree(
            project,
            "prototype-untrusted-settings",
        )


@pytest.mark.asyncio
async def test_committed_generation_snapshot_excludes_dirty_files_and_survives_item_cleanup(
    project: Project,
    manager: WorktreeManager,
) -> None:
    repo = Path(project.repo_path)
    (repo / ".env").write_text("TRACKED_SECRET=must-not-copy\n", encoding="utf-8")
    _git("add", ".env", cwd=repo)
    _git("commit", "-m", "tracked dotenv fixture", cwd=repo)
    frozen_head = _git_output("rev-parse", "HEAD", cwd=repo)
    (repo / "README.md").write_text("dirty tracked source\n", encoding="utf-8")
    (repo / ".env.local").write_text("LOCAL_SECRET=must-not-copy\n", encoding="utf-8")
    (repo / "untracked.ts").write_text("export const dirty = true;\n", encoding="utf-8")
    capture = await manager.git.capture_committed_head_snapshot(
        project.repo_path,
        "11111111-1111-1111-1111-111111111111",
    )

    assert capture.worktree_base_commit == frozen_head
    assert capture.working_tree_dirty is True
    assert capture.excluded_tracked_change_count == 1
    assert capture.excluded_untracked_count == 2
    assert capture.source_file_exclusion_policy == "dotenv_checkout_filter_v1"
    assert capture.excluded_sensitive_file_count == 1

    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "advance head", cwd=repo)
    assert _git_output("rev-parse", "HEAD", cwd=repo) != frozen_head

    branch, path, base_revision = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "committed-generation-item",
        source_snapshot=_source_snapshot(capture),
    )
    worktree = Path(path)
    try:
        assert base_revision == frozen_head
        assert _git_output("rev-parse", "HEAD", cwd=worktree) == frozen_head
        assert (worktree / "README.md").read_text(encoding="utf-8") == "hello"
        assert not (worktree / ".env").exists()
        assert not (worktree / ".env.local").exists()
        assert not (worktree / "untracked.ts").exists()
    finally:
        await manager.cleanup_prototype_ui_engineer_worktree(
            project,
            "committed-generation-item",
        )

    assert _git_output("rev-parse", "--verify", capture.snapshot_ref, cwd=repo) == frozen_head
    assert _git_output("branch", "--list", branch, cwd=repo) == ""


@pytest.mark.asyncio
async def test_committed_generation_snapshot_uses_nested_project_tree(tmp_path: Path) -> None:
    repo = tmp_path / "monorepo"
    nested = repo / "examples" / "admin-demo"
    nested.mkdir(parents=True)
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "root.txt").write_text("root\n", encoding="utf-8")
    (repo / ".env").write_text("ROOT_SECRET=filtered\n", encoding="utf-8")
    (repo / ".env.example").write_text("ROOT_EXAMPLE=kept\n", encoding="utf-8")
    sibling = repo / "examples" / "sibling"
    sibling.mkdir(parents=True)
    (sibling / ".env.local").write_text("SIBLING_SECRET=filtered\n", encoding="utf-8")
    (sibling / "shared.txt").write_text("committed sibling\n", encoding="utf-8")
    (nested / "page.txt").write_text("committed page\n", encoding="utf-8")
    (nested / ".env.production").write_text("PROJECT_SECRET=filtered\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", "monorepo", cwd=repo)
    (repo / "root.txt").write_text("dirty root\n", encoding="utf-8")
    (sibling / "shared.txt").write_text("dirty sibling\n", encoding="utf-8")
    (repo / "root-untracked.txt").write_text("root untracked\n", encoding="utf-8")
    (sibling / "sibling-untracked.txt").write_text("sibling untracked\n", encoding="utf-8")
    (nested / "project-untracked.txt").write_text("project untracked\n", encoding="utf-8")
    project = Project(id="nested", name="admin-demo", repo_path=str(nested))
    manager = WorktreeManager(GitService())

    capture = await manager.git.capture_committed_head_snapshot(
        project.repo_path,
        "22222222-2222-2222-2222-222222222222",
    )
    root_capture = await manager.git.capture_committed_head_snapshot(
        repo,
        "33333333-3333-3333-3333-333333333333",
    )
    assert capture.repository_project_prefix == "examples/admin-demo"
    assert capture.working_tree_dirty is True
    assert capture.excluded_tracked_change_count == 2
    assert capture.excluded_untracked_count == 3
    assert capture.excluded_tracked_change_count == root_capture.excluded_tracked_change_count
    assert capture.excluded_untracked_count == root_capture.excluded_untracked_count
    assert capture.excluded_status_hash == root_capture.excluded_status_hash
    assert capture.excluded_sensitive_file_count == 3
    assert await manager.git.generation_excluded_checkout_paths(
        project.repo_path,
        commit=capture.worktree_base_commit,
        project_prefix=capture.repository_project_prefix,
        exclusion_policy=capture.source_file_exclusion_policy,
    ) == (
        ".env",
        "examples/admin-demo/.env.production",
        "examples/sibling/.env.local",
    )
    assert capture.repository_tree_object_id == _git_output(
        "rev-parse",
        "HEAD:examples/admin-demo",
        cwd=repo,
    )

    _, path, base_revision = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "nested-committed-generation-item",
        source_snapshot=_source_snapshot(capture),
    )
    try:
        isolated = Path(path)
        checkout_root = isolated.parents[1]
        assert isolated.name == "admin-demo"
        assert base_revision == capture.worktree_base_commit
        assert (isolated / "page.txt").read_text(encoding="utf-8") == "committed page\n"
        assert not (isolated / "root.txt").exists()
        assert not (isolated / ".env.production").exists()
        assert not (isolated / "project-untracked.txt").exists()
        assert not (checkout_root / ".env").exists()
        assert not (checkout_root / "examples/sibling/.env.local").exists()
        assert not (checkout_root / "root-untracked.txt").exists()
        assert not (checkout_root / "examples/sibling/sibling-untracked.txt").exists()
        assert (checkout_root / ".env.example").read_text(encoding="utf-8") == (
            "ROOT_EXAMPLE=kept\n"
        )
        assert (isolated / "../../root.txt").resolve().read_text(encoding="utf-8") == "root\n"
    finally:
        await manager.cleanup_prototype_ui_engineer_worktree(
            project,
            "nested-committed-generation-item",
        )


@pytest.mark.asyncio
async def test_committed_generation_snapshot_integrity_failures_block_worktree_creation(
    project: Project,
    manager: WorktreeManager,
) -> None:
    repo = Path(project.repo_path)
    capture = await manager.git.capture_committed_head_snapshot(
        project.repo_path,
        "33333333-3333-3333-3333-333333333333",
    )
    snapshot = _source_snapshot(capture)

    with pytest.raises(WorktreeError, match="project tree changed"):
        await manager.prepare_prototype_ui_engineer_worktree(
            project,
            "tree-mismatch-item",
            source_snapshot=replace(snapshot, repository_tree_object_id="0" * 40),
        )

    _git("update-ref", "-d", capture.snapshot_ref, cwd=repo)
    with pytest.raises(WorktreeError, match="snapshot ref is missing or changed"):
        await manager.prepare_prototype_ui_engineer_worktree(
            project,
            "missing-ref-item",
            source_snapshot=snapshot,
        )

    (repo / "second.txt").write_text("second\n", encoding="utf-8")
    _git("add", "second.txt", cwd=repo)
    _git("commit", "-m", "second", cwd=repo)
    _git("update-ref", capture.snapshot_ref, "HEAD", cwd=repo)
    with pytest.raises(WorktreeError, match="snapshot ref is missing or changed"):
        await manager.prepare_prototype_ui_engineer_worktree(
            project,
            "retargeted-ref-item",
            source_snapshot=snapshot,
        )


@pytest.mark.asyncio
async def test_startup_cleanup_removes_only_managed_prototype_resources(
    project: Project,
    manager: WorktreeManager,
    tmp_path: Path,
) -> None:
    repo = Path(project.repo_path)
    item_branch, item_path, _ = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "stale-generation-item",
    )
    (Path(item_path) / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    managed_parent = repo.parent / f"{project.name}-worktrees"
    filesystem_key = "a" * 20
    filesystem_only = managed_parent / f"prototype-{filesystem_key}"
    filesystem_only.mkdir(parents=True)
    (filesystem_only / "partial.txt").write_text("partial\n", encoding="utf-8")
    _git("branch", f"prototype/{filesystem_key}", cwd=repo)
    branch_only_key = "b" * 20
    _git("branch", f"prototype/{branch_only_key}", cwd=repo)

    unrelated_path = tmp_path / "unrelated-worktree"
    _git(
        "worktree",
        "add",
        "-b",
        "unrelated/keep",
        str(unrelated_path),
        "main",
        cwd=repo,
    )
    owned_job_id = "44444444-4444-4444-4444-444444444444"
    orphan_job_id = "55555555-5555-5555-5555-555555555555"
    owned_capture = await manager.git.capture_committed_head_snapshot(
        project.repo_path,
        owned_job_id,
    )
    orphan_capture = await manager.git.capture_committed_head_snapshot(
        project.repo_path,
        orphan_job_id,
    )
    primary_before = (
        _git_output("rev-parse", "HEAD", cwd=repo),
        _git_output("rev-parse", "HEAD^{tree}", cwd=repo),
        _git_output("status", "--porcelain", cwd=repo),
    )

    await manager.cleanup_stale_prototype_generation_resources(
        project,
        owned_snapshot_job_ids=frozenset({owned_job_id}),
    )

    assert not Path(item_path).exists()
    assert not filesystem_only.exists()
    assert _git_output("branch", "--list", item_branch, cwd=repo) == ""
    assert _git_output("branch", "--list", f"prototype/{filesystem_key}", cwd=repo) == ""
    assert _git_output("branch", "--list", f"prototype/{branch_only_key}", cwd=repo) == ""
    assert unrelated_path.is_dir()
    assert _git_output("branch", "--list", "unrelated/keep", cwd=repo) != ""
    assert _git_output("rev-parse", "--verify", owned_capture.snapshot_ref, cwd=repo) == (
        owned_capture.worktree_base_commit
    )
    assert subprocess.run(
        ["git", "rev-parse", "--verify", orphan_capture.snapshot_ref],
        cwd=repo,
        capture_output=True,
        text=True,
    ).returncode != 0
    assert (
        _git_output("rev-parse", "HEAD", cwd=repo),
        _git_output("rev-parse", "HEAD^{tree}", cwd=repo),
        _git_output("status", "--porcelain", cwd=repo),
    ) == primary_before


@pytest.mark.asyncio
async def test_prototype_worktree_isolates_nested_untracked_project_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    tracked_frontend = repo / "frontend/src"
    tracked_frontend.mkdir(parents=True)
    (tracked_frontend / "globals.css").write_text("parent styles\n", encoding="utf-8")
    _git("add", "frontend/src/globals.css", cwd=repo)
    _git("commit", "-m", "parent app", cwd=repo)

    nested = repo / "examples/admin-demo"
    source = nested / "frontend/src/Page.vue"
    source.parent.mkdir(parents=True)
    source.write_text("<template>nested</template>\n", encoding="utf-8")
    project = Project(id="nested", name="admin-demo", repo_path=str(nested))
    manager = WorktreeManager(GitService())
    item_ids = ("prototype-nested-a", "prototype-nested-b")

    prepared = await asyncio.gather(
        *(
            manager.prepare_prototype_ui_engineer_worktree(
                project,
                item_id,
                source_paths=("frontend/src/Page.vue",),
            )
            for item_id in item_ids
        )
    )
    try:
        for _, path, _ in prepared:
            isolated = Path(path)
            assert isolated.name == "admin-demo"
            assert (isolated / "frontend/src/Page.vue").read_text(encoding="utf-8") == (
                "<template>nested</template>\n"
            )
            assert not (isolated / "frontend/src/globals.css").exists()
            top_level = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=isolated,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert Path(top_level) == isolated
    finally:
        await asyncio.gather(
            *(manager.cleanup_prototype_ui_engineer_worktree(project, item_id) for item_id in item_ids)
        )


@pytest.mark.asyncio
async def test_prototype_worktree_never_runs_setup_or_links_frontend_dependencies(
    project: Project,
    manager: WorktreeManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_ignored_frontend_dependencies(project)
    project.setup_script = "touch prototype-setup-must-not-run"
    calls: list[str] = []

    async def unexpected_setup(script: str, cwd: Path) -> None:
        del script, cwd
        calls.append("setup")

    async def unexpected_dependency_link(target_project: Project, worktree: Path) -> None:
        del target_project, worktree
        calls.append("dependencies")

    monkeypatch.setattr(manager, "_run_setup", unexpected_setup)
    monkeypatch.setattr(
        manager,
        "_link_trusted_frontend_dependencies",
        unexpected_dependency_link,
    )

    _, path, _ = await manager.prepare_prototype_ui_engineer_worktree(
        project,
        "prototype-no-setup",
        source_paths=("frontend/package.json",),
    )
    try:
        worktree = Path(path)
        assert calls == []
        assert not (worktree / "prototype-setup-must-not-run").exists()
        assert not (worktree / "frontend" / "node_modules").exists()
    finally:
        await manager.cleanup_prototype_ui_engineer_worktree(project, "prototype-no-setup")


def _add_ignored_frontend_dependencies(project: Project) -> Path:
    repo = Path(project.repo_path)
    frontend = repo / "frontend"
    dependencies = frontend / "node_modules"
    dependencies.mkdir(parents=True)
    vite = dependencies / "vite"
    vite.mkdir()
    (vite / "package.json").write_text('{"name":"vite"}\n')
    (frontend / "package.json").write_text('{"scripts":{"test":"node --test"}}\n')
    (repo / ".gitignore").write_text("frontend/node_modules/\n")
    _git("add", ".gitignore", "frontend/package.json", cwd=repo)
    _git("commit", "-m", "add frontend", cwd=repo)
    return dependencies.resolve()


@pytest.mark.asyncio
async def test_frontend_dependencies_are_linked_into_issue_chat_and_swarm_worktrees(
    project: Project,
    manager: WorktreeManager,
) -> None:
    dependencies = _add_ignored_frontend_dependencies(project)
    issue = CodexIssue(
        id="issue-deps0001",
        session_id="s1",
        project_id=project.id,
        title="frontend work",
    )

    issue_branch, issue_path, issue_base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = issue_branch
    issue.git_worktree_path = issue_path
    issue.git_base_branch = issue_base
    _, swarm_path, _ = await manager.prepare_agent_worktree(project, issue, "frontend")

    task = CodexTask(
        id="task-deps0001",
        session_id="s1",
        project_id=project.id,
        title="frontend chat",
        prompt="test frontend",
    )
    _, chat_path, _ = await manager.prepare_chat_task_worktree(project, task)

    for path in (issue_path, swarm_path, chat_path):
        linked = Path(path) / "frontend" / "node_modules"
        assert linked.is_dir()
        assert linked.is_symlink() is False
        assert (linked / "vite").is_symlink()
        assert (linked / "vite").resolve() == dependencies / "vite"
        assert "frontend/node_modules" not in await manager.git.status_porcelain(path)


@pytest.mark.asyncio
async def test_frontend_dependency_link_rejects_unexpected_worktree_symlink(
    project: Project,
    manager: WorktreeManager,
    tmp_path: Path,
) -> None:
    _add_ignored_frontend_dependencies(project)
    issue = CodexIssue(
        id="issue-deps0002",
        session_id="s1",
        project_id=project.id,
        title="frontend work",
    )
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = branch
    issue.git_worktree_path = path
    issue.git_base_branch = base
    linked = Path(path) / "frontend" / "node_modules"
    shutil.rmtree(linked)
    outside = tmp_path / "unexpected-node-modules"
    outside.mkdir()
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorktreeError, match="unexpected frontend/node_modules symlink"):
        await manager.prepare_issue_worktree(project, issue)


@pytest.mark.asyncio
async def test_frontend_dependency_link_rejects_primary_symlink_outside_repo(
    project: Project,
    manager: WorktreeManager,
    tmp_path: Path,
) -> None:
    repo = Path(project.repo_path)
    frontend = repo / "frontend"
    frontend.mkdir()
    outside = tmp_path / "external-node-modules"
    outside.mkdir()
    (frontend / "node_modules").symlink_to(outside, target_is_directory=True)
    (frontend / "package.json").write_text("{}\n")
    (repo / ".gitignore").write_text("frontend/node_modules/\n")
    _git("add", ".gitignore", "frontend/package.json", cwd=repo)
    _git("commit", "-m", "add frontend", cwd=repo)
    issue = CodexIssue(
        id="issue-deps0003",
        session_id="s1",
        project_id=project.id,
        title="frontend work",
    )

    with pytest.raises(WorktreeError, match="resolve outside the project repo"):
        await manager.prepare_issue_worktree(project, issue)


@pytest.mark.asyncio
async def test_setup_script_runs_structured_commands_with_minimal_env(
    tmp_path: Path,
    manager: WorktreeManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (backend / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_spawn(*argv: str, **kwargs: object) -> FakeProcess:
        calls.append((argv, kwargs))
        return FakeProcess()

    monkeypatch.setenv("CONSOLE_AUTH_TOKEN", "console-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    await manager._run_setup(
        "(cd frontend && npm install) && (cd backend && python -m pip install -r requirements.txt)",
        tmp_path,
    )

    assert [call[0] for call in calls] == [
        ("npm", "install"),
        ("python", "-m", "pip", "install", "-r", "requirements.txt"),
    ]
    assert [call[1]["cwd"] for call in calls] == [str(frontend), str(backend)]
    for _, kwargs in calls:
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert "CONSOLE_AUTH_TOKEN" not in env
        assert "OPENAI_API_KEY" not in env


@pytest.mark.asyncio
async def test_setup_script_refusal_happens_before_spawn(
    tmp_path: Path,
    manager: WorktreeManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_spawn(*args: object, **kwargs: object) -> None:
        raise AssertionError("refused setup command must not create a process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)

    with pytest.raises(WorktreeError, match="shell_syntax_not_allowed"):
        await manager._run_setup("npm install > leaked.log", tmp_path)


# ---- Per-agent (swarm) worktree ----


async def _issue_with_worktree(
    project: Project, manager: WorktreeManager, issue_id: str
) -> CodexIssue:
    issue = CodexIssue(id=issue_id, session_id="s1", project_id=project.id, title="swarm work")
    branch, path, base = await manager.prepare_issue_worktree(project, issue)
    issue.git_branch = branch
    issue.git_worktree_path = path
    issue.git_base_branch = base
    return issue


def _prepared_issue_git(issue: CodexIssue) -> tuple[str, Path]:
    assert issue.git_branch is not None
    assert issue.git_worktree_path is not None
    return issue.git_branch, Path(issue.git_worktree_path)


@pytest.mark.asyncio
async def test_prepare_agent_worktree_forks_from_issue_branch(
    project: Project, manager: WorktreeManager
):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0001")
    branch, path, base = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert branch == f"swarm/{issue.id[:8]}-engineera"
    assert Path(path).exists()
    # base is the issue integration branch, not the project default
    assert base == issue.git_branch
    assert base != project.default_branch


@pytest.mark.asyncio
async def test_prepare_agent_worktree_requires_issue_branch(
    project: Project, manager: WorktreeManager
):
    issue = CodexIssue(
        id="issue-swrm0002", session_id="s1", project_id=project.id, title="no branch yet"
    )
    with pytest.raises(WorktreeError):
        await manager.prepare_agent_worktree(project, issue, "engineerA")


@pytest.mark.asyncio
async def test_agent_worktrees_are_isolated(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0003")
    _, path_a, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    _, path_b, _ = await manager.prepare_agent_worktree(project, issue, "engineerB")
    assert path_a != path_b
    # Writes in one agent worktree are not visible in the other.
    (Path(path_a) / "a_only.txt").write_text("from A")
    (Path(path_b) / "b_only.txt").write_text("from B")
    assert not (Path(path_b) / "a_only.txt").exists()
    assert not (Path(path_a) / "b_only.txt").exists()


@pytest.mark.asyncio
async def test_prepare_agent_worktree_is_idempotent(project: Project, manager: WorktreeManager):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0004")
    b1, p1, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    b2, p2, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert (b1, p1) == (b2, p2)


@pytest.mark.asyncio
async def test_cleanup_agent_worktree_removes_and_is_idempotent(
    project: Project, manager: WorktreeManager
):
    issue = await _issue_with_worktree(project, manager, "issue-swrm0005")
    _, path, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert Path(path).exists()
    await manager.cleanup_agent_worktree(project, issue, "engineerA")
    assert not Path(path).exists()
    # Calling again on a now-missing worktree must not raise.
    await manager.cleanup_agent_worktree(project, issue, "engineerA")


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_noop_when_no_swarm(
    project: Project, manager: WorktreeManager
):
    """Terminal-state sweep is a safe no-op on an issue that never ran a swarm
    batch: no worktrees/branches to remove, no raise, idempotent."""
    issue = await _issue_with_worktree(project, manager, "issue-swrm0006")
    main_before = subprocess.run(
        ["git", "rev-parse", "main"], cwd=project.repo_path, capture_output=True, text=True
    ).stdout.strip()

    # No swarm worktree exists -> no-op, no raise.
    await manager.cleanup_issue_swarm_worktrees(project, issue)
    # Idempotent: a second call is also a no-op.
    await manager.cleanup_issue_swarm_worktrees(project, issue)

    # main untouched and the issue worktree/branch still intact.
    main_after = subprocess.run(
        ["git", "rev-parse", "main"], cwd=project.repo_path, capture_output=True, text=True
    ).stdout.strip()
    issue_branch, issue_worktree = _prepared_issue_git(issue)
    assert main_after == main_before
    assert issue_worktree.exists()
    assert await manager.git.branch_exists(project.repo_path, issue_branch)


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_removes_residual_agents(
    project: Project, manager: WorktreeManager
):
    """Removes residual per-agent swarm worktrees + `swarm/*` branch refs while
    leaving the shared issue worktree/branch and main untouched."""
    issue = await _issue_with_worktree(project, manager, "issue-swrm0007")
    br_a, wt_a, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    br_b, wt_b, _ = await manager.prepare_agent_worktree(project, issue, "qaB")
    assert Path(wt_a).exists() and Path(wt_b).exists()

    await manager.cleanup_issue_swarm_worktrees(project, issue)

    # swarm worktrees + branches gone.
    assert not Path(wt_a).exists() and not Path(wt_b).exists()
    assert not await manager.git.branch_exists(project.repo_path, br_a)
    assert not await manager.git.branch_exists(project.repo_path, br_b)
    # Shared issue worktree/branch survive (cleanup is swarm-scoped only).
    issue_branch, issue_worktree = _prepared_issue_git(issue)
    assert issue_worktree.exists()
    assert await manager.git.branch_exists(project.repo_path, issue_branch)


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_removes_filesystem_only_stale_dirs(
    project: Project, manager: WorktreeManager
):
    """A previous cleanup/restart can leave a plain directory after git has
    already pruned the worktree metadata. The issue-scoped sweep must remove
    those filesystem-only `swarm-<issue-id>-*` directories too, otherwise the
    next dispatch_batch run cannot recreate the same per-agent worktree path."""
    issue = await _issue_with_worktree(project, manager, "issue-swrm0008")
    worktree_parent = Path(project.repo_path).parent / f"{project.name}-worktrees"
    stale = worktree_parent / f"swarm-{issue.id}-engineer"
    stale.mkdir(parents=True)
    (stale / "issues").mkdir()
    (stale / "issues" / "leftover.txt").write_text("stale")

    await manager.cleanup_issue_swarm_worktrees(project, issue)

    assert not stale.exists()
    issue_branch, issue_worktree = _prepared_issue_git(issue)
    assert issue_worktree.exists()
    assert await manager.git.branch_exists(project.repo_path, issue_branch)


@pytest.mark.asyncio
async def test_cleanup_issue_swarm_worktrees_does_not_touch_sibling_issue(
    project: Project, manager: WorktreeManager
):
    """Cross-issue isolation boundary (risk #1): cleaning issue A must NOT remove
    issue B's swarm worktrees or branches when the two issues have DISTINCT
    ``id[:8]`` prefixes (the production case — issue ids are uuid4, so an 8-hex
    prefix collision is astronomically unlikely). Locks the invariant that the
    discovery prefixes (`swarm-<full-id>-` for dirs, `swarm/<id[:8]>-` for
    branches) are issue-scoped, not a blanket `swarm/*` sweep that would delete a
    concurrently-finalizing sibling issue's branches."""
    # Distinct ids => distinct id[:8] => distinct branch prefixes.
    issue_a = await _issue_with_worktree(project, manager, "aaaa1111-issueA")
    issue_b = await _issue_with_worktree(project, manager, "bbbb2222-issueB")
    assert issue_a.id[:8] != issue_b.id[:8]

    br_a, wt_a, _ = await manager.prepare_agent_worktree(project, issue_a, "engineer")
    br_b, wt_b, _ = await manager.prepare_agent_worktree(project, issue_b, "engineer")

    # Sweep ONLY issue A.
    await manager.cleanup_issue_swarm_worktrees(project, issue_a)

    # A is cleaned.
    assert not Path(wt_a).exists()
    assert not await manager.git.branch_exists(project.repo_path, br_a)
    # B is fully untouched: worktree dir + swarm branch + issue branch all survive.
    assert Path(wt_b).exists()
    assert await manager.git.branch_exists(project.repo_path, br_b)
    issue_b_branch, issue_b_worktree = _prepared_issue_git(issue_b)
    assert issue_b_worktree.exists()
    assert await manager.git.branch_exists(project.repo_path, issue_b_branch)


# ---- PR3: upstream visibility + merge-back ----


def _commit(path: Path, name: str, content: str) -> None:
    (Path(path) / name).write_text(content)
    _git("add", name, cwd=Path(path))
    _git("-c", "user.email=t@e", "-c", "user.name=T", "commit", "-m", f"add {name}", cwd=Path(path))


@pytest.mark.asyncio
async def test_commit_issue_worktree_flushes_uncommitted(
    project: Project, manager: WorktreeManager
):
    issue = await _issue_with_worktree(project, manager, "issue-flsh0001")
    _issue_branch, issue_worktree = _prepared_issue_git(issue)
    # Upstream artifact left uncommitted in the shared issue worktree.
    (issue_worktree / "prd.md").write_text("requirements")
    sha = await manager.commit_issue_worktree(issue)
    assert sha is not None
    # Clean tree afterwards.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=issue_worktree,
        capture_output=True,
        text=True,
    ).stdout
    assert status.strip() == ""
    # Idempotent: nothing to commit now.
    assert await manager.commit_issue_worktree(issue) is None


@pytest.mark.asyncio
async def test_agent_worktree_sees_committed_upstream_artifacts(
    project: Project, manager: WorktreeManager
):
    """Upstream-visibility fix: after flushing the issue worktree, a per-agent
    worktree forked from the issue branch can see the upstream artifact."""
    issue = await _issue_with_worktree(project, manager, "issue-flsh0002")
    _issue_branch, issue_worktree = _prepared_issue_git(issue)
    (issue_worktree / "prd.md").write_text("upstream PM output")
    await manager.commit_issue_worktree(issue)
    _, agent_path, _ = await manager.prepare_agent_worktree(project, issue, "engineerA")
    assert (Path(agent_path) / "prd.md").read_text() == "upstream PM output"


async def _merge_candidate(
    project: Project,
    manager: WorktreeManager,
    issue: CodexIssue,
    agent_key: str,
    filename: str,
    content: str,
) -> AgentMergeSpec:
    branch, path, _ = await manager.prepare_agent_worktree(project, issue, agent_key)
    _commit(Path(path), filename, content)
    return {"agent_key": agent_key, "role": "engineer", "branch": branch, "worktree_path": path}


@pytest.mark.asyncio
async def test_merge_agent_worktrees_sequential_no_conflict(
    project: Project, manager: WorktreeManager
):
    issue = await _issue_with_worktree(project, manager, "issue-mrg00001")
    a = await _merge_candidate(project, manager, issue, "engineerA", "a.txt", "AAA")
    b = await _merge_candidate(project, manager, issue, "engineerB", "b.txt", "BBB")
    issue_branch, _issue_worktree = _prepared_issue_git(issue)

    summary = await manager.merge_agent_worktrees(project, issue, [a, b])
    assert summary["conflict"] is None
    assert len(summary["merged"]) == 2
    assert summary["skipped"] == []

    # Both files landed on the issue branch (verify in a fresh detached worktree).
    log = subprocess.run(
        ["git", "log", "--oneline", issue_branch],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "merge swarm agent engineerA" in log
    assert "merge swarm agent engineerB" in log
    # Second agent saw the first's commit (divergence handled).
    assert summary["merged"][1]["behind_at_merge"] >= 1
    # Both agent worktrees cleaned up after merge.
    assert not Path(a["worktree_path"]).exists()
    assert not Path(b["worktree_path"]).exists()


@pytest.mark.asyncio
async def test_merge_agent_worktrees_conflict_stops_and_keeps_worktree(
    project: Project, manager: WorktreeManager
):
    issue = await _issue_with_worktree(project, manager, "issue-mrg00002")
    # Two agents edit the SAME file with different content → conflict.
    a = await _merge_candidate(project, manager, issue, "engineerA", "shared.txt", "from A\n")
    b = await _merge_candidate(project, manager, issue, "engineerB", "shared.txt", "from B\n")
    c = await _merge_candidate(project, manager, issue, "engineerC", "c.txt", "CCC")
    issue_branch, _issue_worktree = _prepared_issue_git(issue)

    summary = await manager.merge_agent_worktrees(project, issue, [a, b, c])

    # First merged cleanly; second conflicts; third skipped (stop on conflict).
    assert len(summary["merged"]) == 1
    assert summary["merged"][0]["agent_key"] == "engineerA"
    conflict = summary["conflict"]
    assert conflict is not None
    assert conflict["agent_key"] == "engineerB"
    assert "shared.txt" in conflict["files"]
    assert conflict["diff"]  # diff captured for reconcile
    assert [s["agent_key"] for s in summary["skipped"]] == ["engineerC"]

    # First (merged) agent worktree cleaned; conflicting one KEPT for reconcile.
    assert not Path(a["worktree_path"]).exists()
    assert Path(b["worktree_path"]).exists()
    # Already-merged agent A's commit was not rolled back.
    log = subprocess.run(
        ["git", "log", "--oneline", issue_branch],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "merge swarm agent engineerA" in log
    assert "merge swarm agent engineerB" not in log


@pytest.mark.asyncio
async def test_merge_agent_worktrees_does_not_pollute_default_branch(
    project: Project, manager: WorktreeManager
):
    """Regression: merge-back must NOT advance the project default branch.

    The issue branch descends from `main`, so `main` is an ancestor of the
    squash commit. A naive `git merge --ff-only` in the primary repo (which is
    checked out on `main`) would happily fast-forward `main` onto unreviewed
    agent changes, bypassing the `merge_issue` review flow. The swarm-safe
    primitive must touch only the issue branch ref.
    """
    issue = await _issue_with_worktree(project, manager, "issue-pollu001")
    issue_branch, issue_worktree = _prepared_issue_git(issue)
    main_before = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    a = await _merge_candidate(project, manager, issue, "engineerA", "a.txt", "AAA")
    b = await _merge_candidate(project, manager, issue, "engineerB", "b.txt", "BBB")
    summary = await manager.merge_agent_worktrees(project, issue, [a, b])
    assert len(summary["merged"]) == 2

    # main must be byte-for-byte unchanged.
    main_after = subprocess.run(
        ["git", "rev-parse", "main"],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert main_after == main_before
    # main must not contain the agent files.
    main_tree = subprocess.run(
        ["git", "ls-tree", "--name-only", "main"],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "a.txt" not in main_tree
    assert "b.txt" not in main_tree
    # The issue branch DID accumulate both agents' files.
    issue_tree = subprocess.run(
        ["git", "ls-tree", "--name-only", issue_branch],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "a.txt" in issue_tree and "b.txt" in issue_tree
    # The shared issue worktree is consistent with the moved branch ref (no
    # stale index reporting phantom deletions) and has both files on disk.
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=issue_worktree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status.strip() == ""
    assert (issue_worktree / "a.txt").exists()
    assert (issue_worktree / "b.txt").exists()


async def _noop_candidate(
    project: Project,
    manager: WorktreeManager,
    issue: CodexIssue,
    agent_key: str,
) -> AgentMergeSpec:
    """An agent worktree with NO changes relative to the issue branch.

    Production flushes the issue worktree (committing the injected `.claude/`
    hooks) before forking agents, so a fork that writes nothing is truly even
    with the issue branch. Mirror that here.
    """
    await manager.commit_issue_worktree(issue)
    branch, path, _ = await manager.prepare_agent_worktree(project, issue, agent_key)
    return {"agent_key": agent_key, "role": "engineer", "branch": branch, "worktree_path": path}


@pytest.mark.asyncio
async def test_merge_agent_worktrees_noop_agent_is_not_conflict(
    project: Project, manager: WorktreeManager
):
    """Core regression: an agent that produced NO changes must not be treated as
    a conflict. Its branch has nothing ahead of the issue branch, so the squash
    merge would fail at the empty commit; that must be a clean no-op (worktree
    cleaned, no conflict, no stop)."""
    issue = await _issue_with_worktree(project, manager, "issue-noop0001")
    b = await _noop_candidate(project, manager, issue, "engineerB")

    summary = await manager.merge_agent_worktrees(project, issue, [b])

    assert summary["conflict"] is None
    assert summary["merged"] == []
    assert summary["skipped"] == []
    assert [n["agent_key"] for n in summary["noop"]] == ["engineerB"]
    # No-op agent's worktree was cleaned up (no leak).
    assert not Path(b["worktree_path"]).exists()


@pytest.mark.asyncio
async def test_merge_agent_worktrees_mixed_noop_does_not_stop_others(
    project: Project, manager: WorktreeManager
):
    """[changed A, no-op B, changed C] → A and C merge, B is a clean no-op, no
    conflict, no worktree leak, B does not stop C."""
    issue = await _issue_with_worktree(project, manager, "issue-noop0002")
    issue_branch, _issue_worktree = _prepared_issue_git(issue)
    a = await _merge_candidate(project, manager, issue, "engineerA", "a.txt", "AAA")
    b = await _noop_candidate(project, manager, issue, "engineerB")
    c = await _merge_candidate(project, manager, issue, "engineerC", "c.txt", "CCC")

    summary = await manager.merge_agent_worktrees(project, issue, [a, b, c])

    assert summary["conflict"] is None
    assert summary["skipped"] == []
    assert [m["agent_key"] for m in summary["merged"]] == ["engineerA", "engineerC"]
    assert [n["agent_key"] for n in summary["noop"]] == ["engineerB"]

    # All three worktrees cleaned up (merged A/C + no-op B), none leaked.
    assert not Path(a["worktree_path"]).exists()
    assert not Path(b["worktree_path"]).exists()
    assert not Path(c["worktree_path"]).exists()

    # Both changed agents landed on the issue branch.
    issue_tree = subprocess.run(
        ["git", "ls-tree", "--name-only", issue_branch],
        cwd=project.repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "a.txt" in issue_tree and "c.txt" in issue_tree


@pytest.mark.asyncio
async def test_merge_agent_worktrees_real_conflict_still_stops_after_noop(
    project: Project, manager: WorktreeManager
):
    """A real conflict (two agents editing the same file) must STILL stop-on-first
    and keep the conflicting worktree, even when a no-op agent precedes it — the
    no-op handling must not weaken real-conflict semantics."""
    issue = await _issue_with_worktree(project, manager, "issue-noop0003")
    n = await _noop_candidate(project, manager, issue, "engineerN")
    a = await _merge_candidate(project, manager, issue, "engineerA", "shared.txt", "from A\n")
    b = await _merge_candidate(project, manager, issue, "engineerB", "shared.txt", "from B\n")
    c = await _merge_candidate(project, manager, issue, "engineerC", "c.txt", "CCC")

    summary = await manager.merge_agent_worktrees(project, issue, [n, a, b, c])

    assert [nn["agent_key"] for nn in summary["noop"]] == ["engineerN"]
    assert [m["agent_key"] for m in summary["merged"]] == ["engineerA"]
    conflict = summary["conflict"]
    assert conflict is not None
    assert conflict["agent_key"] == "engineerB"
    assert "shared.txt" in conflict["files"]
    assert conflict["diff"]
    # C skipped (stop on first real conflict).
    assert [s["agent_key"] for s in summary["skipped"]] == ["engineerC"]
    # Conflicting worktree KEPT for reconcile; no-op + merged cleaned.
    assert not Path(n["worktree_path"]).exists()
    assert not Path(a["worktree_path"]).exists()
    assert Path(b["worktree_path"]).exists()
