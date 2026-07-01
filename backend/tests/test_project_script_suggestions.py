from __future__ import annotations

import asyncio
import socket
import sys
from datetime import datetime

import pytest

from app.application.project_script_suggestions import (
    build_project_script_suggestion_prompt,
    collect_project_script_context,
    infer_project_script_suggestion,
    parse_project_script_suggestion,
    suggest_project_scripts,
    verify_project_launch,
)
from app.domain.models import Project


def _project(repo_path: str) -> Project:
    return Project(
        id="project-1",
        name="demo",
        repo_path=repo_path,
        default_branch="main",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_collect_project_script_context_summarizes_package_scripts(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"dev":"vite","build":"tsc"},"dependencies":{"vite":"latest"}}'
    )

    context = collect_project_script_context(str(tmp_path))

    assert '"package.json"' in context
    assert '"dev": "vite"' in context
    assert '"vite"' in context


def test_build_prompt_keeps_setup_and_run_fields_separate(tmp_path):
    project = _project(str(tmp_path))

    prompt = build_project_script_suggestion_prompt(
        project=project,
        repo_context='{"files":[]}',
        existing_setup_script="npm install",
        existing_run_command="npm run dev",
    )

    assert '"setup_script"' in prompt
    assert '"run_command"' in prompt
    assert "Put dev servers/watchers in run_command, not setup_script." in prompt
    assert "npm install" in prompt
    assert "npm run dev" in prompt


def test_parse_project_script_suggestion_accepts_fenced_json():
    suggestion = parse_project_script_suggestion(
        '```json\n{"setupScript":"npm install","launchCommand":"npm run dev"}\n```'
    )

    assert suggestion is not None
    assert suggestion.setup_script == "npm install"
    assert suggestion.run_command == "npm run dev"


def test_infer_project_script_suggestion_prefers_dev_local(tmp_path):
    (tmp_path / "dev-local.sh").write_text("#!/usr/bin/env bash\n")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")

    suggestion = infer_project_script_suggestion(str(tmp_path))

    assert suggestion is not None
    assert suggestion.setup_script == ""
    assert suggestion.run_command == "./dev-local.sh"
    assert suggestion.agent_name == "Operations Engineer"


def test_infer_project_script_suggestion_uses_subshells_for_multi_package_setup(tmp_path):
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (frontend / "package.json").write_text('{"scripts":{"dev":"next dev"}}')
    (backend / "requirements.txt").write_text("fastapi\n")

    suggestion = infer_project_script_suggestion(str(tmp_path))

    assert suggestion is not None
    assert suggestion.setup_script == (
        "(cd frontend && npm install) && (cd backend && python -m pip install -r requirements.txt)"
    )
    assert suggestion.run_command == "cd frontend && npm run dev"
    assert suggestion.access_url == "http://127.0.0.1:3000"


def test_parse_project_script_suggestion_accepts_operations_fields():
    suggestion = parse_project_script_suggestion(
        '{"setup_script":"","run_command":"npm run dev","access_url":"http://localhost:5173","notes":["vite"]}'
    )

    assert suggestion is not None
    assert suggestion.agent_name == "Operations Engineer"
    assert suggestion.access_url == "http://localhost:5173"
    assert suggestion.notes == ["vite"]


@pytest.mark.asyncio
async def test_suggest_project_scripts_returns_none_for_unusable_response(tmp_path):
    async def runner(_: str) -> str | None:
        return "not json"

    suggestion = await suggest_project_scripts(project=_project(str(tmp_path)), runner=runner)

    assert suggestion is None


@pytest.mark.asyncio
async def test_suggest_project_scripts_falls_back_when_ai_times_out(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}')

    async def runner(_: str) -> str | None:
        await asyncio.sleep(0.05)
        return '{"setup_script":"slow","run_command":"slow"}'

    suggestion = await suggest_project_scripts(
        project=_project(str(tmp_path)),
        runner=runner,
        timeout_s=0.001,
    )

    assert suggestion is not None
    assert suggestion.setup_script == "npm install"
    assert suggestion.run_command == "npm run dev"


@pytest.mark.asyncio
async def test_suggest_project_scripts_falls_back_when_ai_runner_raises(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}')

    async def runner(_: str) -> str | None:
        raise RuntimeError("provider unavailable")

    suggestion = await suggest_project_scripts(
        project=_project(str(tmp_path)),
        runner=runner,
    )

    assert suggestion is not None
    assert suggestion.setup_script == "npm install"
    assert suggestion.run_command == "npm run dev"


@pytest.mark.asyncio
async def test_verify_project_launch_reaches_local_http_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    suggestion = parse_project_script_suggestion(
        f'{{"setup_script":"","run_command":"{sys.executable} -m http.server {port}",'
        f'"access_url":"http://127.0.0.1:{port}"}}'
    )

    assert suggestion is not None
    verification = await verify_project_launch(
        repo_path=str(tmp_path),
        suggestion=suggestion,
        timeout_s=1.0,
    )

    assert verification.status == "verified"
    assert verification.access_url == f"http://127.0.0.1:{port}"


def test_project_script_suggestion_endpoint_returns_commands(client, tmp_path, monkeypatch):
    import app.application.llm_runner as llm_runner_module
    import app.interfaces.api as api_module

    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}')
    project = _project(str(tmp_path))

    class FakeProjectService:
        async def get(self, project_id: str) -> Project:
            assert project_id == project.id
            return project

    async def runner(prompt: str) -> str:
        assert "Repository evidence" in prompt
        assert '"dev": "vite"' in prompt
        return '{"setup_script":"npm install","run_command":"npm run dev"}'

    monkeypatch.setattr(api_module, "project_service", FakeProjectService())
    monkeypatch.setattr(api_module, "_get_runtime_catalog_service", lambda: object())
    monkeypatch.setattr(llm_runner_module, "build_llm_runner", lambda *args, **kwargs: runner)

    response = client.post(
        f"/api/projects/{project.id}/script-suggestion",
        json={"setup_script": "", "run_command": "", "verify": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["setup_script"] == "npm install"
    assert body["run_command"] == "npm run dev"
    assert body["agent_name"] == "Operations Engineer"
