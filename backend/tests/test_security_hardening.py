from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

import app.interfaces.api as api_module
from app.domain.models import CodexIssue


class _ArtifactStoreStub:
    def __init__(self, issue: CodexIssue, workspace_cwd: Path):
        self.issue = issue
        self.workspace = type("W", (), {"cwd": str(workspace_cwd)})()
        self.saved_artifacts: list[dict] = []

    async def load_codex_issue(self, issue_id):
        return self.issue if issue_id == self.issue.id else None

    async def load_codex_workspace(self, session_id):
        return self.workspace

    async def list_codex_tasks(self, **kwargs):
        return []

    async def list_artifacts(self, issue_id):
        return list(self.saved_artifacts)

    async def save_artifact(self, row):
        self.saved_artifacts.append(row)


def _issue(workspace_path: Path) -> CodexIssue:
    now = datetime.now()
    return CodexIssue(
        id="issue-sec-1",
        session_id="ws-sec-1",
        title="Security issue",
        current_phase="requirements",
        status="open",
        git_worktree_path=str(workspace_path),
        created_at=now,
        updated_at=now,
    )


def test_skills_proxy_rejects_loopback_url(client):
    resp = client.get("/api/skills/proxy", params={"url": "http://127.0.0.1:8000/secret.md"})

    assert resp.status_code == 400
    assert "not allowed" in resp.text.lower()


@pytest.mark.asyncio
async def test_artifact_scan_skips_symlinks_outside_issue_root(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    pm_dir = issue_root / "pm"
    pm_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("do not leak", encoding="utf-8")
    (pm_dir / "leak.md").symlink_to(outside)

    store = _ArtifactStoreStub(issue, tmp_path)
    monkeypatch.setattr(api_module, "codex_store", store)
    typed_store = cast(api_module.CodexApiStore, store)

    artifacts = await api_module._scan_and_backfill_artifacts(
        issue.id, issue.session_id, typed_store
    )

    assert artifacts == []
    assert store.saved_artifacts == []


@pytest.mark.asyncio
async def test_artifact_preview_skips_symlink_artifacts(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    pm_dir = issue_root / "pm"
    pm_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("do not preview", encoding="utf-8")
    link = pm_dir / "leak.md"
    link.symlink_to(outside)
    artifacts = [
        {
            "id": f"{issue.id}:pm/leak.md",
            "issue_id": issue.id,
            "task_id": None,
            "name": "pm/leak.md",
            "path": str(link),
            "kind": "product",
            "created_at": datetime.now().isoformat(),
        }
    ]
    store = _ArtifactStoreStub(issue, tmp_path)
    store.saved_artifacts = artifacts
    monkeypatch.setattr(api_module, "codex_store", store)

    async def _no_scan(*args, **kwargs):
        return artifacts

    monkeypatch.setattr(api_module, "_scan_and_backfill_artifacts", _no_scan)

    assert await api_module.get_codex_issue_artifacts(issue.id) == []


@pytest.mark.asyncio
async def test_artifact_zip_skips_symlink_artifacts(monkeypatch, tmp_path):
    issue = _issue(tmp_path)
    issue_root = tmp_path / "issues" / issue.id
    pm_dir = issue_root / "pm"
    pm_dir.mkdir(parents=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("do not zip", encoding="utf-8")
    link = pm_dir / "leak.md"
    link.symlink_to(outside)
    artifacts = [
        {
            "id": f"{issue.id}:pm/leak.md",
            "issue_id": issue.id,
            "task_id": None,
            "name": "pm/leak.md",
            "path": str(link),
            "kind": "product",
            "created_at": datetime.now().isoformat(),
        }
    ]
    store = _ArtifactStoreStub(issue, tmp_path)
    store.saved_artifacts = artifacts
    monkeypatch.setattr(api_module, "codex_store", store)

    async def _no_scan(*args, **kwargs):
        return artifacts

    monkeypatch.setattr(api_module, "_scan_and_backfill_artifacts", _no_scan)
    response = await api_module.download_issue_artifacts_zip(issue.id)
    body = getattr(response, "body", b"")

    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert zf.namelist() == []
