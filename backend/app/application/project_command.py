from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

_INLINE_CODE_MARKERS = ("$(", "${", "`", "\n", "\r", "\x00")
_PACKAGE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun", "npx"})
_PACKAGE_EXEC_WRAPPERS = frozenset({"exec", "x", "dlx"})
_PACKAGE_DIRECT_DEV_SCRIPTS = frozenset({"dev", "develop", "preview", "serve", "start", "watch"})
_NPX_DEV_EXECUTABLES = frozenset(
    {
        "astro",
        "next",
        "nuxt",
        "remix",
        "serve",
        "vite",
        "webpack",
        "webpack-dev-server",
    }
)
_SETUP_PACKAGE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun"})
_SETUP_PACKAGE_ACTIONS = frozenset({"ci", "i", "install"})
_MUTATING_PACKAGE_ACTIONS = frozenset(
    {
        "add",
        "config",
        "create",
        "install",
        "link",
        "login",
        "logout",
        "pack",
        "publish",
        "remove",
        "uninstall",
        "unlink",
        "update",
    }
)
_PYTHON_RUN_MODULES = frozenset(
    {
        "flask",
        "gunicorn",
        "http.server",
        "streamlit",
        "uvicorn",
    }
)
_SETUP_PATH_FLAGS = frozenset(
    {
        "--cache-dir",
        "--prefix",
        "--project",
        "--root",
        "--target",
        "--userconfig",
        "--directory",
        "--global-dir",
        "--global-bin-dir",
        "--store-dir",
        "--virtualenvs-path",
    }
)
_DIRECT_DEV_COMMANDS = frozenset(
    {
        "cargo",
        "fastapi",
        "flask",
        "go",
        "gradle",
        "gunicorn",
        "make",
        "mvn",
        "streamlit",
        "uvicorn",
    }
)
_CARGO_DEV_COMMANDS = frozenset({"run"})
_MAVEN_DEV_GOALS = frozenset(
    {
        "spring-boot:run",
        "quarkus:dev",
        "vertx:run",
        "tomcat7:run",
    }
)
_GRADLE_DEV_TASKS = frozenset({"appRun", "bootRun", "quarkusDev", "run"})
_MAKE_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]*$")
_SCOPE_PATH_OPTIONS: dict[str, frozenset[str]] = {
    "bun": frozenset({"--cwd"}),
    "cargo": frozenset({"--manifest-path", "--target-dir"}),
    "docker": frozenset({"-f", "--file", "--env-file", "--project-directory"}),
    "docker-compose": frozenset(
        {"-f", "--file", "--env-file", "--project-directory"}
    ),
    "fastapi": frozenset({"--entrypoint"}),
    "flask": frozenset({"--app"}),
    "go": frozenset({"-C"}),
    "gradle": frozenset(
        {"-p", "--project-dir", "-b", "--build-file", "-c", "--settings-file"}
    ),
    "./gradlew": frozenset(
        {"-p", "--project-dir", "-b", "--build-file", "-c", "--settings-file"}
    ),
    "gunicorn": frozenset({"--chdir", "-c", "--config"}),
    "make": frozenset({"-C", "--directory", "-f", "--file"}),
    "mvn": frozenset({"-f", "--file"}),
    "npm": frozenset({"--prefix"}),
    "pnpm": frozenset({"-C", "--dir", "--prefix", "--workspace-dir"}),
    "uvicorn": frozenset({"--app-dir"}),
    "yarn": frozenset({"--cwd"}),
}
_COMPOSE_OPTIONS_WITH_VALUE = frozenset(
    {
        "-f",
        "--file",
        "--env-file",
        "--project-directory",
        "--profile",
        "--project-name",
        "--ansi",
        "--progress",
        "--parallel",
    }
)
_COMPOSE_BOOLEAN_OPTIONS = frozenset({"--compatibility", "--dry-run"})
_ENV_ALLOWLIST = frozenset(
    {
        "COLORTERM",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "NO_COLOR",
        "PATH",
        "PNPM_HOME",
        "SHELL",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "USER",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
)


class ProjectCommandError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ParsedProjectCommand:
    argv: tuple[str, ...]
    cwd: Path
    display: str


def _tokenize(command: str) -> list[str]:
    if any(marker in command for marker in _INLINE_CODE_MARKERS):
        raise ProjectCommandError("shell_syntax_not_allowed")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ProjectCommandError("invalid_command_syntax") from exc
    if not tokens:
        raise ProjectCommandError("no_run_command")
    return tokens


def _resolve_cwd(root: Path, requested: str) -> Path:
    requested_path = Path(requested)
    if requested_path.is_absolute():
        raise ProjectCommandError("cwd_outside_project")
    candidate = (root / requested_path).resolve()
    if not candidate.is_relative_to(root):
        raise ProjectCommandError("cwd_outside_project")
    if not candidate.is_dir():
        raise ProjectCommandError("cwd_not_found")
    return candidate


def _is_shell_operator(token: str) -> bool:
    return bool(token) and all(char in ";&|<>" for char in token)


def _split_cwd(tokens: list[str], root: Path) -> tuple[list[str], Path]:
    operators = [index for index, token in enumerate(tokens) if _is_shell_operator(token)]
    if not operators:
        return tokens, root
    if (
        len(operators) == 1
        and tokens[operators[0]] == "&&"
        and operators[0] == 2
        and tokens[0] == "cd"
        and len(tokens) > 3
    ):
        return tokens[3:], _resolve_cwd(root, tokens[1])
    raise ProjectCommandError("shell_syntax_not_allowed")


def _validate_repo_script(executable: str, cwd: Path) -> None:
    script_path = Path(executable)
    if script_path.is_absolute() or not executable.startswith("./"):
        raise ProjectCommandError("executable_not_allowed")
    resolved = (cwd / script_path).resolve()
    if not resolved.is_relative_to(cwd) or not resolved.is_file():
        raise ProjectCommandError("script_not_found")
    if not os.access(resolved, os.X_OK):
        raise ProjectCommandError("script_not_executable")


def _validate_python(argv: list[str], cwd: Path) -> None:
    if len(argv) < 2:
        raise ProjectCommandError("interpreter_inline_code_not_allowed")
    command_index = 1
    while command_index < len(argv) and argv[command_index] in {
        "-B",
        "-E",
        "-I",
        "-O",
        "-OO",
        "-s",
        "-S",
        "-u",
    }:
        command_index += 1
    if command_index >= len(argv) or argv[command_index] in {"-c", "--command", "-"}:
        raise ProjectCommandError("interpreter_inline_code_not_allowed")
    if argv[command_index] == "-m":
        if len(argv) <= command_index + 1 or argv[command_index + 1].startswith("-"):
            raise ProjectCommandError("invalid_python_module")
        if argv[command_index + 1] not in _PYTHON_RUN_MODULES:
            raise ProjectCommandError("python_module_not_allowed")
        return
    script = Path(argv[command_index])
    if script.is_absolute() or script.suffix != ".py":
        raise ProjectCommandError("python_script_not_allowed")
    resolved = (cwd / script).resolve()
    if not resolved.is_relative_to(cwd) or not resolved.is_file():
        raise ProjectCommandError("python_script_not_allowed")


def _ensure_path_within_project(value: str, *, cwd: Path, root: Path) -> None:
    candidate_path = Path(value).expanduser()
    if PureWindowsPath(value).is_absolute():
        raise ProjectCommandError("cwd_outside_project")
    candidate = candidate_path if candidate_path.is_absolute() else cwd / candidate_path
    if not candidate.resolve().is_relative_to(root):
        raise ProjectCommandError("cwd_outside_project")


def _validate_scoped_arguments(argv: list[str], *, cwd: Path, root: Path) -> None:
    options = _SCOPE_PATH_OPTIONS.get(argv[0], frozenset())
    index = 1
    while index < len(argv):
        argument = argv[index]
        option, separator, inline_value = argument.partition("=")
        if option in options:
            if separator:
                if not inline_value:
                    raise ProjectCommandError("invalid_scope_path")
                _ensure_path_within_project(inline_value, cwd=cwd, root=root)
            else:
                if index + 1 >= len(argv):
                    raise ProjectCommandError("invalid_scope_path")
                _ensure_path_within_project(argv[index + 1], cwd=cwd, root=root)
                index += 1
        else:
            attached_option = next(
                (
                    candidate
                    for candidate in options
                    if candidate.startswith("-")
                    and not candidate.startswith("--")
                    and argument.startswith(candidate)
                    and len(argument) > len(candidate)
                ),
                None,
            )
            if attached_option is not None:
                _ensure_path_within_project(
                    argument[len(attached_option) :],
                    cwd=cwd,
                    root=root,
                )

        path_candidates = [argument]
        if separator:
            path_candidates.append(inline_value)
        for candidate_value in path_candidates:
            path = Path(candidate_value)
            if (
                path.is_absolute()
                or PureWindowsPath(candidate_value).is_absolute()
                or candidate_value.startswith("~")
                or ".." in path.parts
            ):
                _ensure_path_within_project(candidate_value, cwd=cwd, root=root)
        index += 1


def _validate_npx(argv: list[str]) -> None:
    package_index = 1
    while package_index < len(argv) and argv[package_index] in {"-y", "--yes", "--no-install"}:
        package_index += 1
    if package_index >= len(argv):
        raise ProjectCommandError("package_command_not_allowed")
    if argv[package_index] not in _NPX_DEV_EXECUTABLES:
        raise ProjectCommandError("package_command_not_allowed")
    if "--no-install" not in argv[1:package_index]:
        raise ProjectCommandError("package_download_not_allowed")
    if any(
        argument in {"-c", "--call", "-p", "--package", "--shell"}
        or argument.startswith("--package=")
        for argument in argv[1:]
    ):
        raise ProjectCommandError("interpreter_inline_code_not_allowed")


def _validate_package_manager(argv: list[str]) -> None:
    if len(argv) < 2:
        raise ProjectCommandError("package_command_not_allowed")
    if argv[0] == "npx":
        _validate_npx(argv)
        return
    if argv[0] == "bun" and any(
        argument in {"-e", "--eval", "-p", "--print"}
        or argument.startswith(("--eval=", "--print="))
        for argument in argv[1:]
    ):
        raise ProjectCommandError("interpreter_inline_code_not_allowed")

    value_options = {
        "npm": frozenset({"--prefix"}),
        "pnpm": frozenset(
            {"-C", "--dir", "--filter", "--prefix", "--workspace-dir"}
        ),
        "yarn": frozenset({"--cwd"}),
        "bun": frozenset({"--cwd", "--filter"}),
    }[argv[0]]
    command_index = 1
    while command_index < len(argv):
        argument = argv[command_index]
        option = argument.split("=", 1)[0]
        if option in value_options:
            command_index += 1 if "=" in argument else 2
            continue
        if argument.startswith("-"):
            command_index += 1
            continue
        break
    if command_index >= len(argv):
        raise ProjectCommandError("package_command_not_allowed")

    command = argv[command_index].lower()
    if command in _PACKAGE_EXEC_WRAPPERS or command in {"explore", "node", "shell"}:
        raise ProjectCommandError("package_command_not_allowed")
    if command in _MUTATING_PACKAGE_ACTIONS:
        raise ProjectCommandError("package_command_not_allowed")
    if argv[0] == "npm":
        if command not in {"run", "run-script", "start"}:
            raise ProjectCommandError("package_command_not_allowed")
        if command in {"run", "run-script"} and command_index + 1 >= len(argv):
            raise ProjectCommandError("package_command_not_allowed")
        return
    if command in {"run", "run-script"}:
        if command_index + 1 >= len(argv):
            raise ProjectCommandError("package_command_not_allowed")
        return
    if command not in _PACKAGE_DIRECT_DEV_SCRIPTS:
        raise ProjectCommandError("package_command_not_allowed")


def _validate_cargo(argv: list[str]) -> None:
    value_options = _SCOPE_PATH_OPTIONS["cargo"]
    command: str | None = None
    index = 1
    while index < len(argv):
        argument = argv[index]
        option = argument.split("=", 1)[0]
        if option in value_options:
            index += 1 if "=" in argument else 2
            continue
        if not argument.startswith("-"):
            command = argument
            break
        index += 1
    if command not in _CARGO_DEV_COMMANDS:
        raise ProjectCommandError("cargo_command_not_allowed")


def _validate_go(argv: list[str], *, cwd: Path, root: Path) -> None:
    command_index = 1
    while command_index < len(argv):
        argument = argv[command_index]
        option = argument.split("=", 1)[0]
        if option in _SCOPE_PATH_OPTIONS["go"]:
            command_index += 1 if "=" in argument else 2
            continue
        if argument.startswith("-"):
            command_index += 1
            continue
        break
    if command_index >= len(argv) or argv[command_index] != "run":
        raise ProjectCommandError("go_command_not_allowed")
    targets = [argument for argument in argv[command_index + 1 :] if not argument.startswith("-")]
    if not targets:
        raise ProjectCommandError("go_command_not_allowed")
    for target in targets:
        if "@" in target or target.startswith(("http://", "https://")):
            raise ProjectCommandError("go_remote_module_not_allowed")
        if target == ".":
            continue
        path = Path(target)
        if not (target.startswith("./") or path.suffix == ".go"):
            raise ProjectCommandError("go_remote_module_not_allowed")
        _ensure_path_within_project(target, cwd=cwd, root=root)


def _validate_maven(argv: list[str]) -> None:
    if any(
        argument.startswith(("exec:", "-Dexec.", "-Dexec="))
        for argument in argv[1:]
    ):
        raise ProjectCommandError("maven_exec_not_allowed")
    goals: list[str] = []
    index = 1
    while index < len(argv):
        argument = argv[index]
        option = argument.split("=", 1)[0]
        if option in _SCOPE_PATH_OPTIONS["mvn"]:
            index += 1 if "=" in argument else 2
            continue
        if not argument.startswith("-"):
            goals.append(argument)
        index += 1
    if not goals or any(goal not in _MAVEN_DEV_GOALS for goal in goals):
        raise ProjectCommandError("maven_goal_not_allowed")


def _validate_gradle(argv: list[str]) -> None:
    if any(
        argument in {"-I", "--init-script"}
        or argument.startswith(("-I", "--init-script="))
        for argument in argv[1:]
    ):
        raise ProjectCommandError("gradle_init_script_not_allowed")
    value_options = _SCOPE_PATH_OPTIONS[argv[0]]
    tasks: list[str] = []
    index = 1
    while index < len(argv):
        argument = argv[index]
        option = argument.split("=", 1)[0]
        if option in value_options:
            index += 1 if "=" in argument else 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        tasks.append(argument)
        index += 1
    if not tasks or any(task.rsplit(":", 1)[-1] not in _GRADLE_DEV_TASKS for task in tasks):
        raise ProjectCommandError("gradle_task_not_allowed")


def _validate_make(argv: list[str]) -> None:
    if any(
        argument in {"-I", "--include-dir", "--eval"}
        or argument.startswith(("-I", "--include-dir=", "--eval="))
        for argument in argv[1:]
    ):
        raise ProjectCommandError("make_injection_not_allowed")
    value_options = _SCOPE_PATH_OPTIONS["make"]
    index = 1
    while index < len(argv):
        argument = argv[index]
        option = argument.split("=", 1)[0]
        if option in value_options:
            index += 1 if "=" in argument else 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        if "=" in argument or not _MAKE_TARGET_RE.fullmatch(argument):
            raise ProjectCommandError("make_injection_not_allowed")
        index += 1


def _compose_command(argv: list[str], start: int) -> str | None:
    index = start
    while index < len(argv):
        option = argv[index].split("=", 1)[0]
        if option in _COMPOSE_BOOLEAN_OPTIONS:
            index += 1
            continue
        if option in _COMPOSE_OPTIONS_WITH_VALUE:
            index += 1 if "=" in argv[index] else 2
            continue
        return argv[index]
    return None


def _validate_argv(argv: list[str], cwd: Path, root: Path) -> None:
    executable = argv[0]
    if executable in {"sh", "bash", "zsh", "fish", "dash", "node", "ruby", "perl"}:
        raise ProjectCommandError("interpreter_inline_code_not_allowed")
    if executable in {"python", "python3"}:
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        _validate_python(argv, cwd)
        return
    if executable == "docker":
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        if len(argv) < 3 or argv[1] != "compose" or _compose_command(argv, 2) != "up":
            raise ProjectCommandError("docker_command_not_allowed")
        return
    if executable == "docker-compose":
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        if _compose_command(argv, 1) != "up":
            raise ProjectCommandError("docker_command_not_allowed")
        return
    if executable in _PACKAGE_MANAGERS:
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        _validate_package_manager(argv)
        return
    if executable == "cargo":
        _validate_cargo(argv)
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        return
    if executable == "go":
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        _validate_go(argv, cwd=cwd, root=root)
        return
    if executable == "mvn":
        _validate_maven(argv)
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        return
    if executable in {"gradle", "./gradlew"}:
        _validate_gradle(argv)
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        if executable == "./gradlew":
            _validate_repo_script(executable, cwd)
        return
    if executable == "make":
        _validate_make(argv)
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        return
    if executable in _DIRECT_DEV_COMMANDS:
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        return
    if executable.startswith("./"):
        _validate_scoped_arguments(argv, cwd=cwd, root=root)
        _validate_repo_script(executable, cwd)
        return
    raise ProjectCommandError("executable_not_allowed")


def _validate_setup_flags(argv: list[str], *, cwd: Path, root: Path) -> None:
    for index, argument in enumerate(argv[1:], start=1):
        option = argument.split("=", 1)[0]
        if option in _SETUP_PATH_FLAGS or argument in {"-g", "--global"}:
            raise ProjectCommandError("setup_path_override_not_allowed")
        if option in {"--cwd", "--dir", "--prefix"}:
            raise ProjectCommandError("setup_path_override_not_allowed")
        if argument in {"-c", "--command"}:
            raise ProjectCommandError("interpreter_inline_code_not_allowed")
        if index > 0 and (argument.startswith("http://") or argument.startswith("https://")):
            raise ProjectCommandError("setup_remote_url_not_allowed")
        if argument.startswith(("file:", "git+", "github:")):
            raise ProjectCommandError("setup_remote_url_not_allowed")
        if argument.startswith(("./", "../")) or Path(argument).is_absolute():
            candidate = (cwd / argument).resolve() if not Path(argument).is_absolute() else Path(argument)
            if not candidate.is_relative_to(root):
                raise ProjectCommandError("setup_path_override_not_allowed")


def _validate_setup_python(argv: list[str], *, cwd: Path, root: Path) -> None:
    command_index = 1
    while command_index < len(argv) and argv[command_index] in {
        "-B",
        "-E",
        "-I",
        "-s",
        "-S",
        "-u",
    }:
        command_index += 1
    if argv[command_index : command_index + 3] != ["-m", "pip", "install"]:
        raise ProjectCommandError("setup_python_command_not_allowed")
    _validate_setup_flags(argv, cwd=cwd, root=root)


def _validate_setup_argv(argv: list[str], cwd: Path, root: Path) -> None:
    executable = argv[0]
    if executable in {"sh", "bash", "zsh", "fish", "dash", "node", "ruby", "perl"}:
        raise ProjectCommandError("interpreter_inline_code_not_allowed")
    if executable in _SETUP_PACKAGE_MANAGERS:
        if len(argv) < 2 or argv[1].lower() not in _SETUP_PACKAGE_ACTIONS:
            raise ProjectCommandError("setup_package_command_not_allowed")
        actions = [argument.lower() for argument in argv[2:] if not argument.startswith("-")]
        if any(
            action in _MUTATING_PACKAGE_ACTIONS and action not in _SETUP_PACKAGE_ACTIONS
            for action in actions
        ):
            raise ProjectCommandError("setup_package_command_not_allowed")
        _validate_setup_flags(argv, cwd=cwd, root=root)
        return
    if executable in {"python", "python3"}:
        _validate_setup_python(argv, cwd=cwd, root=root)
        return
    if executable in {"pip", "pip3"}:
        if len(argv) < 2 or argv[1] != "install":
            raise ProjectCommandError("setup_python_command_not_allowed")
        _validate_setup_flags(argv, cwd=cwd, root=root)
        return
    if executable == "uv":
        if argv[1:2] != ["sync"]:
            raise ProjectCommandError("setup_package_command_not_allowed")
        _validate_setup_flags(argv, cwd=cwd, root=root)
        return
    if executable == "poetry":
        if argv[1:2] != ["install"]:
            raise ProjectCommandError("setup_package_command_not_allowed")
        _validate_setup_flags(argv, cwd=cwd, root=root)
        return
    if executable.startswith("./"):
        _validate_repo_script(executable, cwd)
        return
    raise ProjectCommandError("setup_executable_not_allowed")


def _tokenize_setup(command: str) -> list[str]:
    if any(marker in command for marker in _INLINE_CODE_MARKERS):
        raise ProjectCommandError("shell_syntax_not_allowed")
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ProjectCommandError("invalid_command_syntax") from exc
    if not tokens:
        raise ProjectCommandError("no_setup_command")
    return tokens


def _parse_setup_unit(
    tokens: list[str],
    start: int,
    root: Path,
) -> tuple[ParsedProjectCommand, int]:
    index = start
    wrapped = index < len(tokens) and tokens[index] == "("
    if wrapped:
        index += 1

    cwd = root
    if tokens[index : index + 1] == ["cd"]:
        if index + 3 >= len(tokens) or tokens[index + 2] != "&&":
            raise ProjectCommandError("invalid_setup_cwd")
        cwd = _resolve_cwd(root, tokens[index + 1])
        index += 3

    argv_start = index
    terminators = {")", "&&"}
    while index < len(tokens) and tokens[index] not in terminators:
        if tokens[index] in {"(", ";", "&", "|", "||", ">", ">>", "<", "<<"}:
            raise ProjectCommandError("shell_syntax_not_allowed")
        index += 1
    argv = tokens[argv_start:index]
    if not argv:
        raise ProjectCommandError("no_setup_command")
    _validate_setup_argv(argv, cwd, root)

    if wrapped:
        if index >= len(tokens) or tokens[index] != ")":
            raise ProjectCommandError("invalid_setup_group")
        index += 1
    elif index < len(tokens) and tokens[index] == ")":
        raise ProjectCommandError("invalid_setup_group")

    return ParsedProjectCommand(argv=tuple(argv), cwd=cwd, display=shlex.join(argv)), index


def parse_project_command(command: str, project_root: str | Path) -> ParsedProjectCommand:
    display = command.strip()
    if not display:
        raise ProjectCommandError("no_run_command")
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ProjectCommandError("project_root_not_found")
    argv, cwd = _split_cwd(_tokenize(display), root)
    _validate_argv(argv, cwd, root)
    return ParsedProjectCommand(argv=tuple(argv), cwd=cwd, display=display)


def parse_project_setup_commands(
    command: str,
    project_root: str | Path,
) -> tuple[ParsedProjectCommand, ...]:
    display = command.strip()
    if not display:
        raise ProjectCommandError("no_setup_command")
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ProjectCommandError("project_root_not_found")
    tokens = _tokenize_setup(display)
    commands: list[ParsedProjectCommand] = []
    index = 0
    while index < len(tokens):
        parsed, index = _parse_setup_unit(tokens, index, root)
        commands.append(parsed)
        if index == len(tokens):
            break
        if tokens[index] != "&&":
            raise ProjectCommandError("shell_syntax_not_allowed")
        index += 1
        if index == len(tokens):
            raise ProjectCommandError("no_setup_command")
    return tuple(commands)


def build_project_child_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = os.environ if source is None else source
    child_env = {key: value for key, value in environment.items() if key in _ENV_ALLOWLIST}
    child_env.setdefault("PATH", os.defpath)
    child_env["PYTHONUNBUFFERED"] = "1"
    return child_env
