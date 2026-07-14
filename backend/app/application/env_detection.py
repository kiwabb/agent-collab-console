"""DEPRECATED (2026-07-09): This deterministic env-detection rules engine is superseded
by the Agent-driven approach (see .trellis/tasks/07-09-ops-runcommand-envfix/prd.md).

The correct architecture: Operations Engineer Agent reads the repo (README,
compose, .env.example, Dockerfile) and produces a startup plan including
env_vars with inferred defaults. Deterministic code handles only
safety/guardrails: secret-never-invent, command safety, encrypted storage,
idempotent .env materialization.

This file is kept as reference only. Do NOT import it in new code.
It will be removed once the Agent-driven replacement is stable.

--- original docstring below ---

Deterministic environment-variable requirement detection for a project repo.

The goal: given a git project, work out *which* env vars it needs to start, so
the console can show the user a fill-in form instead of letting `docker compose`
fail with `env file .env not found` + `${VAR} not set` warnings.

This is the "sensing layer". It is deliberately **deterministic, no LLM** — we
parse concrete evidence and classify each variable into a three-state model
(the industry consensus across Coolify / Vercel / Replit / envalid; see
`research/env-schema-validation.md`):

    required=True,  default=None   → 🔴 user MUST fill (or 🔴 secret)
    required=False, default=<val>  → 🟡 optional, prefilled, user may change
    required=True,  default=<val>  → 🟢 has a safe inferred default

Evidence sources, in priority order:

1. docker-compose `${VAR}` interpolation, using compose's own three-state
   syntax to decide required/default:
     ${VAR}          → referenced, no default        (required, no default)
     ${VAR:-default} → default when unset OR empty    (optional, default)
     ${VAR-default}  → default when unset             (optional, default)
     ${VAR:?err}     → REQUIRED, error when unset      (required, no default)
     ${VAR:+alt}     → conditional; not a real input  (skipped)
2. `.env.example` / `backend/.env.example` etc. — the de-facto "needed vars"
   schema. A key present here with a value becomes that var's default/example.
3. README / Dockerfile `ENV` lines — a fallback source for port/host defaults.

Secret classification is name-based (KEY / SECRET / TOKEN / PASSWORD / ...): a
secret is always `required` and NEVER gets an auto-filled default — the hard
red line shared by every mature tool is "never invent a credential"
(see `research/ai-agent-auto-setup.md`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --- Data model -------------------------------------------------------------


@dataclass
class EnvVarSpec:
    """One required/optional environment variable a project needs to start.

    This is the backend→frontend contract for the "environment config" panel.
    """

    name: str
    required: bool = False
    default: str | None = None
    secret: bool = False
    description: str = ""
    # Where we learned about this var: compose | env_example | readme | dockerfile
    source: str = "compose"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "required": self.required,
            "default": self.default,
            "secret": self.secret,
            "description": self.description,
            "source": self.source,
        }


@dataclass
class EnvRequirements:
    """The full env requirement listing for a project."""

    specs: list[EnvVarSpec] = field(default_factory=list)
    # env_file paths the compose files reference, resolved relative to repo root.
    env_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "specs": [s.to_dict() for s in self.specs],
            "env_files": self.env_files,
        }


# --- Secret classification --------------------------------------------------

# Substrings (case-insensitive) that mark a variable as a secret. A secret is
# always required and never auto-filled with a default.
_SECRET_HINTS = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "APIKEY",
    "API_KEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "AUTH",
    "SALT",
    "SIGNING",
)
# Standalone "KEY" is a secret only as a word boundary component (API_KEY,
# OPENAI_KEY) — plain names like "KEYCLOAK_URL" should not trip. We test the
# tokenized name for a bare KEY segment.
_KEY_SEGMENT_RE = re.compile(r"(^|_)KEY(_|$)")


def is_secret_name(name: str) -> bool:
    """Return True when a variable name looks like a credential."""
    upper = name.upper()
    if any(hint in upper for hint in _SECRET_HINTS):
        return True
    return bool(_KEY_SEGMENT_RE.search(upper))


# --- docker-compose ${VAR} interpolation parsing ----------------------------

# Matches ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:?err}, ${VAR?err},
# ${VAR:+alt}, ${VAR+alt}. Group 1 = name, group 2 = operator (:-, -, :?, ?,
# :+, +, or empty), group 3 = argument.
_INTERP_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)((?::-|:\?|:\+|-|\?|\+)?)([^}]*)\}"
)
# Bare $VAR form (no braces). No default/required syntax possible.
_BARE_RE = re.compile(r"(?<![\\$])\$([A-Za-z_][A-Za-z0-9_]*)")

_COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _classify_interpolation(operator: str, argument: str) -> tuple[bool, str | None]:
    """Map a compose interpolation operator to (required, default).

    ${VAR}          ""   → (required, None)   — referenced, no fallback
    ${VAR:-x} / -x  :-/-  → (optional, "x")    — default when unset/empty
    ${VAR:?e} / ?e  :?/?  → (required, None)   — error when unset
    ${VAR:+a} / +a  :+/+  → treated as (optional, None) — presence-conditional,
                            not a real user input; caller skips these
    """
    if operator in (":-", "-"):
        return False, argument if argument != "" else None
    if operator in (":?", "?"):
        return True, None
    if operator in (":+", "+"):
        # Conditional alternate value — not something the user fills in.
        return False, None
    # No operator: plain ${VAR} reference.
    return True, None


def _iter_compose_files(root: Path) -> list[Path]:
    return [root / name for name in _COMPOSE_NAMES if (root / name).is_file()]


def _extract_env_file_refs(text: str) -> list[str]:
    """Pull `env_file:` targets out of raw compose YAML (string or list form).

    We parse textually rather than with a YAML lib to avoid a new dependency
    and to tolerate the `${VAR}` interpolation that a strict YAML loader is
    fine with but that we want to read verbatim.
    """
    refs: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        # Match `env_file:` with whatever (possibly nothing) follows the colon.
        m = re.match(r"env_file:\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        value = m.group(1).strip()
        if value and not value.startswith("#"):
            # Inline forms on the same line.
            if value.startswith("["):
                # `env_file: [.env, .env.local]`
                for part in value.strip("[]").split(","):
                    cleaned = part.strip().strip("'\"")
                    if cleaned:
                        refs.append(cleaned)
            else:
                # `env_file: .env`  OR  `env_file: "./x.env"`
                cleaned = value.strip("'\"")
                if cleaned:
                    refs.append(cleaned)
            i += 1
            continue
        # Block list form: `env_file:` on its own line, then `- path` items.
        j = i + 1
        while j < len(lines):
            item = lines[j].strip()
            im = re.match(r"-\s*(.+)$", item)
            if not im:
                break
            cleaned = im.group(1).strip().strip("'\"")
            # `- path: .env` (long form) or `- .env`
            pm = re.match(r"path:\s*(.+)$", cleaned)
            if pm:
                cleaned = pm.group(1).strip().strip("'\"")
            if cleaned:
                refs.append(cleaned)
            j += 1
        i = j
    return refs


def parse_compose_vars(text: str) -> dict[str, tuple[bool, str | None]]:
    """Return {name: (required, default)} for every ${VAR} in compose text.

    When the same var appears multiple times, a concrete default wins over
    "no default", and required wins only if no default was ever seen.
    """
    found: dict[str, tuple[bool, str | None]] = {}
    for match in _INTERP_RE.finditer(text):
        name, operator, argument = match.group(1), match.group(2), match.group(3)
        required, default = _classify_interpolation(operator, argument)
        _merge_var(found, name, required, default)
    for match in _BARE_RE.finditer(text):
        name = match.group(1)
        # Skip common shell/compose builtins that are not project inputs.
        if name in _BARE_IGNORE:
            continue
        _merge_var(found, name, True, None)
    return found


# Bare $VAR names that are never project env inputs.
_BARE_IGNORE = frozenset({"PWD", "HOME", "PATH", "USER", "SHELL"})


def _merge_var(
    acc: dict[str, tuple[bool, str | None]],
    name: str,
    required: bool,
    default: str | None,
) -> None:
    if name not in acc:
        acc[name] = (required, default)
        return
    prev_required, prev_default = acc[name]
    # Prefer a concrete default from any occurrence.
    merged_default = prev_default if prev_default is not None else default
    # If we have a default, the var is satisfiable → not strictly required.
    if merged_default is not None:
        acc[name] = (False, merged_default)
    else:
        acc[name] = (prev_required or required, None)


# --- .env.example parsing ---------------------------------------------------

_ENV_EXAMPLE_NAMES = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.defaults",
)
_ENV_EXAMPLE_SUBDIRS = ("", "backend", "frontend")


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env-style file. Returns {key: value}.

    Handles `export KEY=`, quoted values, inline comments, and blank/comment
    lines. Values are returned with surrounding quotes stripped.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^export\s+", "", line)
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        # Strip a trailing inline comment only for unquoted values.
        if value[:1] not in ("'", '"'):
            value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def _find_env_examples(root: Path) -> list[tuple[Path, dict[str, str]]]:
    results: list[tuple[Path, dict[str, str]]] = []
    for subdir in _ENV_EXAMPLE_SUBDIRS:
        base = root / subdir if subdir else root
        for name in _ENV_EXAMPLE_NAMES:
            path = base / name
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                results.append((path, parse_dotenv(text)))
    return results


# --- README / Dockerfile default inference ----------------------------------

_DOCKERFILE_ENV_RE = re.compile(r"^\s*ENV\s+([A-Za-z_][A-Za-z0-9_]*)[=\s]+(\S+)", re.MULTILINE)


def _infer_dockerfile_defaults(root: Path) -> dict[str, str]:
    """Pull `ENV KEY value` / `ENV KEY=value` defaults from Dockerfiles."""
    defaults: dict[str, str] = {}
    for path in root.rglob("Dockerfile*"):
        if not path.is_file():
            continue
        # Skip vendored / nested node_modules etc.
        if any(part in {"node_modules", ".git", "venv", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _DOCKERFILE_ENV_RE.finditer(text):
            key, value = m.group(1), m.group(2).strip().strip("'\"\\")
            defaults.setdefault(key, value)
    return defaults


# --- Description hints -------------------------------------------------------

_DESCRIPTION_HINTS = {
    "PORT": "服务监听端口",
    "HOST": "服务绑定地址 (0.0.0.0 = 所有网卡)",
    "URL": "访问地址",
    "KEY": "密钥 (敏感, 请手动填写)",
    "SECRET": "密钥 (敏感, 请手动填写)",
    "TOKEN": "访问令牌 (敏感, 请手动填写)",
    "PASSWORD": "密码 (敏感, 请手动填写)",
    "DB": "数据库配置",
    "DATABASE": "数据库配置",
    "REGISTRY": "镜像仓库地址",
    "MIRROR": "镜像源地址",
}


def _describe(name: str, secret: bool) -> str:
    upper = name.upper()
    if secret:
        return "敏感凭据 (系统不会自动填写, 请手动录入)"
    for hint, desc in _DESCRIPTION_HINTS.items():
        if hint in upper:
            return desc
    return ""


# --- Top-level detection -----------------------------------------------------


def detect_env_requirements(repo_path: str) -> EnvRequirements:
    """Build the three-state env requirement listing for a project repo.

    Pure/deterministic — no LLM, no network. Safe to call on every panel open.
    """
    root = Path(repo_path)
    requirements = EnvRequirements()
    if not root.is_dir():
        return requirements

    # 1. Parse all compose files → {name: (required, default)} + env_file refs.
    compose_vars: dict[str, tuple[bool, str | None]] = {}
    env_file_refs: list[str] = []
    for compose_path in _iter_compose_files(root):
        try:
            text = compose_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, spec in parse_compose_vars(text).items():
            _merge_var(compose_vars, name, spec[0], spec[1])
        env_file_refs.extend(_extract_env_file_refs(text))

    # Resolve + dedupe env_file references relative to repo root.
    seen_files: set[str] = set()
    for ref in env_file_refs:
        resolved = ref
        if resolved not in seen_files:
            seen_files.add(resolved)
            requirements.env_files.append(resolved)

    # 2. Read .env.example files → example values become defaults.
    example_values: dict[str, str] = {}
    example_keys: set[str] = set()
    for _path, values in _find_env_examples(root):
        for key, value in values.items():
            example_keys.add(key)
            if value and key not in example_values:
                example_values[key] = value

    # 3. Dockerfile ENV defaults as a fallback source.
    dockerfile_defaults = _infer_dockerfile_defaults(root)

    # 4. Merge all sources into EnvVarSpec list. Compose vars are the primary
    #    "what does this project need" signal; example-only keys are added too.
    all_names: list[str] = []
    for name in compose_vars:
        all_names.append(name)
    for name in example_keys:
        if name not in compose_vars:
            all_names.append(name)

    for name in all_names:
        secret = is_secret_name(name)
        compose_spec = compose_vars.get(name)
        if compose_spec is not None:
            required, default = compose_spec
            source = "compose"
        else:
            required, default = True, None
            source = "env_example"

        # Layer in defaults from example / dockerfile when compose gave none.
        if default is None and not secret:
            if name in example_values:
                default = example_values[name]
                source = "env_example" if source == "compose" else source
            elif name in dockerfile_defaults:
                default = dockerfile_defaults[name]
                source = "dockerfile" if source == "compose" else source

        # Hard red line: a secret never carries an auto-filled default, and is
        # always required regardless of compose syntax.
        if secret:
            default = None
            required = True

        requirements.specs.append(
            EnvVarSpec(
                name=name,
                required=required,
                default=default,
                secret=secret,
                description=_describe(name, secret),
                source=source,
            )
        )

    # Stable ordering: secrets last (they need attention but sort predictably),
    # otherwise alphabetical for a calm, diff-friendly panel.
    requirements.specs.sort(key=lambda s: (s.secret, s.name))
    return requirements
