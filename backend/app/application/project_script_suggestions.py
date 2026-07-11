from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
from pathlib import Path
from typing import Awaitable, Callable, Literal  # noqa: UP035

import httpx
from pydantic import BaseModel, Field

from app.application import timeouts
from app.application.project_command import (
    ProjectCommandError,
    build_project_child_env,
    parse_project_command,
)
from app.application.qa_output_redaction import (
    SecretOutputRedactionError,
    SecretOutputRedactor,
)
from app.domain.models import Project
from app.json_safety import object_dict, parse_json_object

ScriptSuggestionRunner = Callable[[str], Awaitable[str | None]]
VerificationStatus = Literal["verified", "started", "failed", "skipped"]
logger = logging.getLogger(__name__)


class ProjectScriptVerification(BaseModel):
    status: VerificationStatus
    message: str
    access_url: str | None = None
    exit_code: int | None = None
    logs: list[str] = Field(default_factory=list)


class EnvVarEntry(BaseModel):
    """A single environment variable inferred by the Operations Engineer agent."""

    name: str
    value: str | None = None  # null = needs user input
    secret: bool = False
    source: str = ""  # where the agent inferred this from


class ProjectScriptSuggestion(BaseModel):
    setup_script: str
    run_command: str
    agent_name: str = "Operations Engineer"
    access_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    verification: ProjectScriptVerification | None = None
    env_vars: list[EnvVarEntry] = Field(default_factory=list)


_CONTEXT_FILES = [
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "bun.lockb",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "poetry.lock",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "docker-compose.yml",
    "compose.yml",
    "dev-local.sh",
    "README.md",
    "frontend/package.json",
    "backend/package.json",
    "backend/requirements.txt",
    "backend/pyproject.toml",
]


def _safe_read(path: Path, limit: int = 8000) -> str | None:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def collect_project_script_context(repo_path: str) -> str:
    root = Path(repo_path)
    files: list[dict[str, object]] = []
    for relative in _CONTEXT_FILES:
        path = root / relative
        text = _safe_read(path)
        if text is None:
            continue
        entry: dict[str, object] = {"path": relative}
        if relative.endswith("package.json"):
            data = parse_json_object(text)
            if data is None:
                entry["excerpt"] = text
            else:
                scripts = object_dict(data.get("scripts"))
                dependencies = object_dict(data.get("dependencies"))
                dev_dependencies = object_dict(data.get("devDependencies"))
                entry["packageManager"] = data.get("packageManager")
                entry["scripts"] = scripts
                entry["dependencies"] = sorted(dependencies.keys())[:40]
                entry["devDependencies"] = sorted(dev_dependencies.keys())[:40]
        else:
            entry["excerpt"] = text[:2000]
        files.append(entry)
    return json.dumps({"files": files}, ensure_ascii=False, indent=2)


def build_project_script_suggestion_prompt(
    *,
    project: Project,
    repo_context: str,
    existing_setup_script: str | None = None,
    existing_run_command: str | None = None,
) -> str:
    return "\n".join(
        [
            "You are an Operations Engineer responsible for making a local git project start and become accessible.",
            "Study the repository evidence below and produce the safest commands a developer should use.",
            "Use only repository evidence. Do not invent tools that are not indicated.",
            "",
            f"Project name: {project.name}",
            f"Repository path: {project.repo_path}",
            f"Existing setup script: {(existing_setup_script or '').strip() or '(empty)'}",
            f"Existing run command: {(existing_run_command or '').strip() or '(empty)'}",
            "",
            "Repository evidence:",
            repo_context,
            "",
            "Return JSON only with this exact shape:",
            "{",
            '  "setup_script": "one-time setup command(s), or empty string",',
            '  "run_command": "long-running local dev command, or empty string",',
            '  "access_url": "http://localhost:port if discoverable, or null",',
            '  "notes": ["short operational notes, verification assumptions, or risks"],',
            '  "env_vars": [',
            '    {"name": "VAR_NAME", "value": "inferred_default_or_null", "secret": false, "source": "where you found this"}',
            '  ]',
            "}",
            "",
            "Rules:",
            "- Put dependency installation or one-time preparation in setup_script.",
            "- Put dev servers/watchers in run_command, not setup_script.",
            "- Prefer package manager lockfiles and package.json scripts when present.",
            "- Prefer project-provided dev-local scripts over generic package commands when present.",
            "- Prefer docker compose when compose files are the only startup evidence.",
            "- Use cd when the command belongs to a subdirectory, such as cd frontend && npm run dev.",
            "- If an access URL or port is documented in README, compose ports, or scripts, set access_url.",
            "- Keep commands safe and non-destructive. Do not include rm -rf, git reset, git clean, database drops, or migrations.",
            "- If a command is not discoverable from evidence, return an empty string for that field.",
            "- No markdown fences, no comments, no explanation.",
            "",
            "Environment variable analysis (env_vars):",
            "- Inspect docker-compose.yml / compose.yml for ${VAR} references and env_file: declarations.",
            "- Read .env.example files (root, frontend/, backend/, or any subdirectory) for expected variable names.",
            "- Read README.md for documented ports, hosts, and configuration instructions.",
            "- Each env_vars entry: name (required), value (inferred default or null), secret (boolean), source (brief).",
            "- Infer sensible defaults for non-secret vars (ports like 3000, 8000, 8080; hosts like 0.0.0.0; URL bases) from README, compose ports, Dockerfile EXPOSE, or package.json scripts.",
            "- If a var appears in compose with ${VAR:-default}, use that default as value.",
            "- If a var appears in compose as plain ${VAR} with no default, infer from README/Dockerfile/context or set value to null.",
            "- Secret detection: if the variable name contains KEY, SECRET, TOKEN, PASSWORD, or API_KEY (case-insensitive), set secret=true and value MUST be null. NEVER invent values for secret variables.",
            "- If no env_vars are discoverable, return an empty array [].",
            "- env_vars is optional; old clients ignore it. Always include the field (even if empty).",
        ]
    )


def _extract_json_object(raw_text: str) -> str | None:
    trimmed = raw_text.strip()
    if trimmed.startswith("```"):
        lines = trimmed.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            trimmed = "\n".join(lines[1:-1]).strip()
    start = trimmed.find("{")
    end = trimmed.rfind("}")
    if start < 0 or end <= start:
        return None
    return trimmed[start : end + 1]


def _read_string(data: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _read_string_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _read_env_vars(data: dict[str, object]) -> list[EnvVarEntry]:
    # Accept multiple field names: env_vars, envVars, environment, env
    for key in ("env_vars", "envVars", "environment", "env"):
        raw = data.get(key)
        if isinstance(raw, list):
            entries: list[EnvVarEntry] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = _read_string(item, ("name", "key", "var"))
                if not name:
                    continue
                value_raw = item.get("value")
                value: str | None = None
                if isinstance(value_raw, str) and value_raw.strip():
                    value = value_raw.strip()
                elif value_raw is not None and not isinstance(value_raw, str):
                    # Non-string truthy values (numbers, booleans) -> stringify
                    value = str(value_raw)
                secret = item.get("secret")
                secret_bool: bool = (
                    isinstance(secret, bool) and secret
                ) or (
                    isinstance(secret, str) and secret.strip().lower() in ("true", "1", "yes")
                )
                source = _read_string(item, ("source", "description", "note", "reason", "from"))
                entries.append(EnvVarEntry(name=name, value=value, secret=secret_bool, source=source))
            return entries
    return []


def parse_project_script_suggestion(raw_text: str) -> ProjectScriptSuggestion | None:
    json_text = _extract_json_object(raw_text)
    if not json_text:
        return None
    parsed = parse_json_object(json_text)
    if parsed is None:
        return None
    return ProjectScriptSuggestion(
        setup_script=_read_string(parsed, ("setup_script", "setupScript", "setup")),
        run_command=_read_string(
            parsed,
            ("run_command", "runCommand", "launch_command", "launchCommand", "startCommand"),
        ),
        access_url=_read_string(parsed, ("access_url", "accessUrl", "url")) or None,
        notes=_read_string_list(parsed, "notes"),
        env_vars=_read_env_vars(parsed),
    )


def _package_manager_for(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lockb").exists():
        return "bun"
    return "npm"


def _read_package_scripts(package_json: Path) -> dict[str, object]:
    try:
        text = package_json.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    parsed = parse_json_object(text)
    if parsed is None:
        return {}
    return object_dict(parsed.get("scripts"))


_PORT_RE = re.compile(r"(?:(?:localhost|127\.0\.0\.1|0\.0\.0\.0):|PORT=|--port\s+|-p\s+)(\d{2,5})")
_COMPOSE_PORT_RE = re.compile(r"(?:published:\s*|['\"]?)(\d{2,5})(?::\d{1,5}|['\"]?\s*$)")


def _first_valid_port(values: list[str]) -> int | None:
    for value in values:
        try:
            port = int(value)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            return port
    return None


def _infer_compose_port(root: Path) -> int | None:
    for name in ("docker-compose.yml", "compose.yml"):
        text = _safe_read(root / name, limit=12000)
        if not text:
            continue
        port = _first_valid_port(_COMPOSE_PORT_RE.findall(text))
        if port is not None:
            return port
    return None


def _infer_access_url(root: Path, run_command: str) -> str | None:
    command_port = _first_valid_port(_PORT_RE.findall(run_command))
    if command_port is not None:
        return f"http://127.0.0.1:{command_port}"

    compose_port = _infer_compose_port(root)
    if compose_port is not None:
        return f"http://127.0.0.1:{compose_port}"

    lowered = run_command.lower()
    if "next" in lowered:
        return "http://127.0.0.1:3000"
    if "vite" in lowered:
        return "http://127.0.0.1:5173"
    if "uvicorn" in lowered or "django" in lowered:
        return "http://127.0.0.1:8000"
    if "flask" in lowered:
        return "http://127.0.0.1:5000"
    return None


def infer_project_script_suggestion(repo_path: str) -> ProjectScriptSuggestion | None:
    root = Path(repo_path)
    if (root / "dev-local.sh").is_file():
        run_command = "./dev-local.sh"
        return ProjectScriptSuggestion(
            setup_script="",
            run_command=run_command,
            access_url=_infer_access_url(root, run_command),
            notes=["Operations Engineer inferred startup from dev-local.sh."],
        )

    package_json = root / "package.json"
    if package_json.is_file():
        manager = _package_manager_for(root)
        scripts = _read_package_scripts(package_json)
        run_script = "dev" if "dev" in scripts else "start" if "start" in scripts else ""
        run_command = f"{manager} run {run_script}" if run_script else ""
        script_command = scripts.get(run_script)
        access_hint = (
            f"{run_command} {script_command}" if isinstance(script_command, str) else run_command
        )
        return ProjectScriptSuggestion(
            setup_script=f"{manager} install",
            run_command=run_command,
            access_url=_infer_access_url(root, access_hint),
            notes=[
                f"Operations Engineer inferred startup from root package.json script '{run_script}'."
            ]
            if run_script
            else ["Operations Engineer found root package.json but no dev/start script."],
        )

    frontend_package = root / "frontend" / "package.json"
    if frontend_package.is_file():
        manager = _package_manager_for(root / "frontend")
        scripts = _read_package_scripts(frontend_package)
        run_script = "dev" if "dev" in scripts else "start" if "start" in scripts else ""
        setup_parts = [f"(cd frontend && {manager} install)"]
        if (root / "backend" / "requirements.txt").is_file():
            setup_parts.append("(cd backend && python -m pip install -r requirements.txt)")
        run_command = f"cd frontend && {manager} run {run_script}" if run_script else ""
        script_command = scripts.get(run_script)
        access_hint = (
            f"{run_command} {script_command}" if isinstance(script_command, str) else run_command
        )
        return ProjectScriptSuggestion(
            setup_script=" && ".join(setup_parts),
            run_command=run_command,
            access_url=_infer_access_url(root / "frontend", access_hint),
            notes=[
                f"Operations Engineer inferred startup from frontend package.json script '{run_script}'."
            ]
            if run_script
            else ["Operations Engineer found frontend/package.json but no dev/start script."],
        )

    if (root / "docker-compose.yml").is_file() or (root / "compose.yml").is_file():
        run_command = "docker compose up"
        return ProjectScriptSuggestion(
            setup_script="",
            run_command=run_command,
            access_url=_infer_access_url(root, run_command),
            notes=["Operations Engineer inferred startup from compose file."],
        )

    if (root / "requirements.txt").is_file() or (root / "pyproject.toml").is_file():
        setup = (
            "python -m pip install -r requirements.txt"
            if (root / "requirements.txt").is_file()
            else ""
        )
        return ProjectScriptSuggestion(
            setup_script=setup,
            run_command="",
            notes=["Operations Engineer found Python dependency metadata but no server command."],
        )

    return None


_LOCAL_URL_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{1,5})?[^\s'\"<>)]+"
)


def _normalize_local_url(url: str) -> str:
    # This normalizes command output text; it does not bind a server socket.
    return url.replace("0.0.0.0", "127.0.0.1").replace("[::1]", "127.0.0.1").rstrip(".,;")  # nosec B104


def _candidate_access_urls(
    root: Path, suggestion: ProjectScriptSuggestion, logs: list[str]
) -> list[str]:
    urls: list[str] = []
    if suggestion.access_url:
        urls.append(_normalize_local_url(suggestion.access_url))
    for line in logs:
        urls.extend(_normalize_local_url(match) for match in _LOCAL_URL_RE.findall(line))
    inferred = _infer_access_url(root, suggestion.run_command)
    if inferred:
        urls.append(inferred)

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique[:5]


async def _read_process_lines(
    stream: asyncio.StreamReader | None,
    tag: str,
    logs: list[str],
    redactor: SecretOutputRedactor,
    limit: int = 80,
) -> None:
    if stream is None:
        return
    try:
        while len(logs) < limit:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            logs.append(redactor.redact(f"{tag}: {line}")[:1000])
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "project launch verification log reader failed: stream=%s",
            tag,
            exc_info=True,
        )


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        with contextlib.suppress(ProcessLookupError, Exception):
            proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except asyncio.TimeoutError:  # noqa: UP041
        with contextlib.suppress(ProcessLookupError, Exception):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=2.0)


async def _probe_access_urls(urls: list[str]) -> tuple[str | None, str | None]:
    if not urls:
        return None, "No local access URL or port was discoverable."
    async with httpx.AsyncClient(timeout=1.5, follow_redirects=True, trust_env=False) as client:
        last_error = None
        for url in urls:
            try:
                response = await client.get(url)
            except Exception as exc:  # noqa: BLE001, RUF100
                last_error = str(exc)
                continue
            if response.status_code < 500:
                return url, f"Access check reached {url} with HTTP {response.status_code}."
            last_error = f"HTTP {response.status_code}"
    return None, f"Access checks failed for {', '.join(urls)}: {last_error or 'unreachable'}."


async def verify_project_launch(
    *,
    repo_path: str,
    suggestion: ProjectScriptSuggestion,
    timeout_s: float | None = None,
) -> ProjectScriptVerification:
    command = suggestion.run_command.strip()
    if not command:
        return ProjectScriptVerification(
            status="skipped",
            message="Operations Engineer could not verify launch because run_command is empty.",
        )
    root = Path(repo_path)
    try:
        parsed = parse_project_command(command, root)
    except ProjectCommandError as exc:
        return ProjectScriptVerification(
            status="skipped",
            message=(
                "Operations Engineer skipped launch verification because the command was refused: "
                f"{exc.reason}"
            ),
        )

    child_env = build_project_child_env()
    try:
        redactor = SecretOutputRedactor.from_workspace(str(root), child_env)
    except SecretOutputRedactionError:
        logger.warning(
            "project launch verification output redaction unavailable; refusing launch: repo=%s",
            root,
            exc_info=True,
        )
        return ProjectScriptVerification(
            status="skipped",
            message=(
                "Operations Engineer skipped launch verification because output "
                "redaction was unavailable."
            ),
        )

    logs: list[str] = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *parsed.argv,
            cwd=str(parsed.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
            start_new_session=True,
        )
    except OSError as exc:
        return ProjectScriptVerification(
            status="failed",
            message=(
                "Operations Engineer could not start the command: "
                f"{redactor.redact(str(exc))}"
            ),
        )

    readers = [
        asyncio.create_task(_read_process_lines(proc.stdout, "stdout", logs, redactor)),
        asyncio.create_task(_read_process_lines(proc.stderr, "stderr", logs, redactor)),
    ]
    running_after_timeout = False
    effective_timeout_s = (
        timeout_s if timeout_s is not None else timeouts.project_script_verification_timeout_s()
    )
    try:
        try:
            exit_code = await asyncio.wait_for(proc.wait(), timeout=effective_timeout_s)
        except asyncio.TimeoutError:  # noqa: UP041
            running_after_timeout = True
            exit_code = None
        await asyncio.sleep(0.2)
        urls = _candidate_access_urls(root, suggestion, logs)
        reached_url, access_message = await _probe_access_urls(urls)
        if reached_url is not None:
            suggestion.access_url = reached_url
            return ProjectScriptVerification(
                status="verified",
                message=access_message or "Operations Engineer verified local access.",
                access_url=reached_url,
                exit_code=exit_code,
                logs=logs[-20:],
            )
        if running_after_timeout:
            return ProjectScriptVerification(
                status="started",
                message=(
                    "Operations Engineer confirmed the command stayed running, "
                    f"but access was not verified. {access_message or ''}"
                ).strip(),
                exit_code=None,
                logs=logs[-20:],
            )
        return ProjectScriptVerification(
            status="failed",
            message=(
                f"Operations Engineer launch check exited with code {exit_code}. "
                f"{access_message or ''}"
            ).strip(),
            exit_code=exit_code,
            logs=logs[-20:],
        )
    finally:
        await _terminate_process(proc)
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


async def _with_optional_verification(
    project: Project,
    suggestion: ProjectScriptSuggestion | None,
    *,
    verify: bool,
) -> ProjectScriptSuggestion | None:
    if suggestion is None or not verify:
        return suggestion
    suggestion.verification = await verify_project_launch(
        repo_path=project.repo_path,
        suggestion=suggestion,
    )
    if suggestion.verification.status != "failed":
        return suggestion

    fallback = infer_project_script_suggestion(project.repo_path)
    if fallback is None or fallback.run_command == suggestion.run_command:
        return suggestion
    fallback.verification = await verify_project_launch(
        repo_path=project.repo_path,
        suggestion=fallback,
    )
    if fallback.verification.status in {"verified", "started"}:
        fallback.notes = [
            "Operations Engineer replaced the AI candidate with a locally inferred command after verification failed.",
            *fallback.notes,
        ]
        return fallback
    return suggestion


async def suggest_project_scripts(
    *,
    project: Project,
    runner: ScriptSuggestionRunner,
    existing_setup_script: str | None = None,
    existing_run_command: str | None = None,
    timeout_s: float | None = None,
    verify: bool = False,
) -> ProjectScriptSuggestion | None:
    repo_context = collect_project_script_context(project.repo_path)
    prompt = build_project_script_suggestion_prompt(
        project=project,
        repo_context=repo_context,
        existing_setup_script=existing_setup_script,
        existing_run_command=existing_run_command,
    )
    effective_timeout_s = (
        timeout_s if timeout_s is not None else timeouts.project_script_suggestion_timeout_s()
    )
    try:
        raw = await asyncio.wait_for(runner(prompt), timeout=effective_timeout_s)
    except asyncio.TimeoutError:  # noqa: UP041
        raw = None
    except Exception as exc:  # noqa: BLE001, RUF100
        logger.warning(
            "project script AI suggestion failed; falling back to repo inference: %s", exc
        )
        raw = None
    if not raw:
        return await _with_optional_verification(
            project,
            infer_project_script_suggestion(project.repo_path),
            verify=verify,
        )
    suggestion = parse_project_script_suggestion(raw)
    if suggestion and (suggestion.setup_script or suggestion.run_command):
        return await _with_optional_verification(project, suggestion, verify=verify)
    return await _with_optional_verification(
        project,
        infer_project_script_suggestion(project.repo_path),
        verify=verify,
    )
