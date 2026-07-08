from __future__ import annotations

"""Prototype design tool service.

Streams a single-file HTML prototype from the LLM, versionizes iterations,
and mirrors each version to disk under `<repo_path>/.agent-collab/prototypes/`.

SSE contract (consumed by `frontend/src/features/prototype/PrototypeCanvas.tsx`):
    event: meta   -> {"model": "..."}
    event: delta  -> {"chunk": "..."}            (multiple)
    event: done   -> {"version_no": int, "html": str, "disk_path": str}
    event: error  -> {"message": "..."}          (terminal)

Notes on the SSE loop:
- We deliberately do NOT use `stream_llm`'s `{"assistant_prefill": "{"}` trick.
  That prefill forces the model into a JSON-shaped continuation, which is
  the opposite of what we want for free-form HTML. The `_stream_html` loop
  below is otherwise a structural copy of `stream_llm`'s SSE parse
  (`llm_runner.py:357-384`) so it stays debuggable.
- We yield chunks *as they arrive* and persist the final HTML once, only on
  `message_stop`. If the client closes the connection mid-stream, no DB row
  is written (the version counter is unchanged). The disk mirror only happens
  after the full document is committed.
"""


import json  # noqa: E402, I001
import logging  # noqa: E402
import os  # noqa: E402, F401
import re  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from collections.abc import AsyncIterator, Mapping  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Protocol  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402

from app.adapters.async_sqlite_store import AsyncSQLiteStore  # noqa: E402
from app.application.code_prototype_discovery import (  # noqa: E402
    CodePrototypeCandidate,
    CodePrototypeDiscoveryService,
)
from app.application.llm_runner import (  # noqa: E402
    StreamingPlanContext,
    _llm_http_client,
    llm_api_url,
    resolve_streaming_context,
)
from app.domain.models import Prototype, PrototypeVersion, Project, RuntimeCatalog  # noqa: E402
from app.json_safety import object_dict, parse_json_object, string_value  # noqa: E402

logger = logging.getLogger(__name__)


class PrototypeError(RuntimeError):
    """User-visible prototype error (mapped to HTTP 4xx by the API layer)."""


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


@dataclass
class StreamEvent:
    """An SSE event to yield. `data` is JSON-serializable."""

    event: str
    data: Mapping[str, object]


class RuntimeCatalogLoader(Protocol):
    async def load_catalog(self) -> RuntimeCatalog: ...


@dataclass(frozen=True)
class RuntimePrototypeEvidence:
    """Safe request-scoped browser evidence for code-backed generation."""

    attempted_url: str | None = None
    final_url: str | None = None
    success: bool = False
    title: str | None = None
    viewport: dict[str, object] | None = None
    visible_text_excerpt: str | None = None
    structure_summary: str | None = None
    console_errors: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    failure_reason: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> RuntimePrototypeEvidence | None:
        if not isinstance(payload, dict):
            return None
        return cls(
            attempted_url=_trim_optional_text(payload.get("attempted_url"), 500),
            final_url=_trim_optional_text(payload.get("final_url"), 500),
            success=payload.get("success") is True,
            title=_trim_optional_text(payload.get("title"), 240),
            viewport=_safe_viewport(payload.get("viewport")),
            visible_text_excerpt=_trim_optional_text(payload.get("visible_text_excerpt"), 560),
            structure_summary=_trim_optional_text(payload.get("structure_summary"), 420),
            console_errors=_safe_console_errors(payload.get("console_errors")),
            screenshot_path=_trim_optional_text(payload.get("screenshot_path"), 500),
            failure_reason=_trim_optional_text(payload.get("failure_reason"), 500),
        )

    def to_prompt_block(self) -> str:
        lines = ["Runtime browser evidence for this route:"]
        if self.success:
            lines.append(
                "- Capture status: success; prefer this visible runtime evidence over source-only inference when they conflict."
            )
        else:
            lines.append(
                "- Capture status: failed or unavailable; fall back to the source excerpt and do not mention capture failure in the artifact."
            )
        if self.attempted_url:
            lines.append(f"- Attempted URL: {self.attempted_url}")
        if self.final_url:
            lines.append(f"- Final URL: {self.final_url}")
        if self.title:
            lines.append(f"- Page title: {self.title}")
        if self.viewport:
            width = self.viewport.get("width")
            height = self.viewport.get("height")
            if width is not None or height is not None:
                lines.append(f"- Viewport: {width or '?'}x{height or '?'}")
        if self.visible_text_excerpt:
            lines.append("- Visible text excerpt:")
            lines.append(self.visible_text_excerpt)
        if self.structure_summary:
            lines.append("- Structural inventory:")
            lines.append(self.structure_summary)
        if self.console_errors:
            lines.append("- Console errors observed:")
            lines.extend(f"  - {item}" for item in self.console_errors)
        if self.screenshot_path:
            lines.append(f"- Screenshot metadata/path: {self.screenshot_path}")
        if self.failure_reason and not self.success:
            lines.append(f"- Capture failure reason: {self.failure_reason}")
        return "\n".join(lines)

    def to_meta(self) -> dict[str, object]:
        return {
            "attempted_url": self.attempted_url,
            "final_url": self.final_url,
            "success": self.success,
            "title": self.title,
            "viewport": self.viewport,
            "visible_text_excerpt": self.visible_text_excerpt,
            "structure_summary": self.structure_summary,
            "console_errors": self.console_errors,
            "screenshot_path": self.screenshot_path,
            "failure_reason": self.failure_reason,
        }


class RuntimeCaptureService(Protocol):
    async def capture_candidate(
        self,
        project: Project,
        candidate: CodePrototypeCandidate,
        base_url: str | None,
    ) -> RuntimePrototypeEvidence: ...


_MD_FENCE = re.compile(r"^```(?:html|HTML)?\s*\n(.*?)\n```\s*$", re.DOTALL)
_SOURCE_UNIT_RE = re.compile(r"(?:^|\n\n)--- ([^-][^\n]*?) ---\n")
CODE_BRIEF_MAX_SOURCE_CHARS = 1_800
CODE_BRIEF_MAX_UNIT_CHARS = 560
CODE_BRIEF_HEAD_CHARS = 220


def _trim_optional_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:limit]


def _safe_viewport(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    viewport: dict[str, object] = {}
    for key in ("width", "height", "device_scale_factor"):
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int | float):
            viewport[key] = raw
    return viewport or None


def _safe_console_errors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    errors: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        clean = item.strip()
        if not clean:
            continue
        errors.append(clean[:220])
        if len(errors) >= 5:
            break
    return errors


def is_complete_html_document(text: str) -> bool:
    """Return whether the generated artifact is a complete HTML document."""
    stripped = text.strip()
    lowered = stripped.lower()
    return (
        lowered.startswith("<!doctype html>")
        and "<html" in lowered
        and "</html>" in lowered
        and lowered.endswith("</html>")
    )


def strip_markdown_fence(text: str) -> str:
    """Strip a single ```html ... ``` wrapper if the model emitted one.

    The system prompt forbids markdown, but Claude sometimes adds a fence
    anyway. Returning the inner body keeps the saved HTML clean.
    """
    stripped = text.strip()
    match = _MD_FENCE.match(stripped)
    if match:
        return match.group(1).strip()
    # Handle the rarer case where the model writes ```html without the
    # closing fence (truncated stream). Drop the leading fence line if so.
    if stripped.startswith("```html") or stripped.startswith("```HTML"):
        return re.sub(r"^```(?:html|HTML)\s*\n?", "", stripped).strip()
    return stripped


def _is_high_signal_source_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    high_signal_tokens = (
        "return (",
        "return <",
        "className=",
        "t(",
        "useState(",
        "useMemo(",
        "useCallback(",
        "InteractionEmptyState",
        "Dialog",
        "PageFrame",
        "Button",
        "Input",
        "Tabs",
        "Table",
        "Card",
        "loading",
        "empty",
        "error",
        "failed",
        "title",
        "description",
        "placeholder",
    )
    if stripped.startswith(("export function ", "function ", "const ")) and (
        "=>" in stripped or stripped.endswith("{")
    ):
        return True
    if stripped.startswith(("<", "{", "</")):
        return True
    return any(token in stripped for token in high_signal_tokens)


def _split_source_excerpt_units(source_excerpt: str) -> list[tuple[str, str]]:
    matches = list(_SOURCE_UNIT_RE.finditer(source_excerpt))
    if not matches:
        return [("source", source_excerpt)]
    units: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_excerpt)
        units.append((match.group(1).strip(), source_excerpt[start:end].strip()))
    return units


def compact_code_source_excerpt(source_excerpt: str) -> str:
    """Shrink source context for LLM generation while preserving UI signal.

    The scanner intentionally keeps rich source metadata for traceability and
    hashing. The LLM prompt has a different job: provide enough structure to
    generate a complete static prototype. Large route files often spend their
    first thousands of characters on imports/state setup, so a naive prefix
    truncation hides the JSX and pushes the model into max-token failures.
    """
    excerpt = source_excerpt.strip()
    if len(excerpt) <= CODE_BRIEF_MAX_SOURCE_CHARS:
        return excerpt

    chunks: list[str] = []
    remaining = CODE_BRIEF_MAX_SOURCE_CHARS
    for rel, content in _split_source_excerpt_units(excerpt):
        if remaining <= 0:
            break
        header = f"\n\n--- {rel} ---\n"
        head = content[:CODE_BRIEF_HEAD_CHARS].rstrip()
        high_signal_lines: list[str] = []
        seen: set[str] = set()
        for line in content.splitlines():
            normalized = line.strip()
            if normalized in seen or not _is_high_signal_source_line(line):
                continue
            seen.add(normalized)
            high_signal_lines.append(line.rstrip())
            if sum(len(item) + 1 for item in high_signal_lines) >= CODE_BRIEF_MAX_UNIT_CHARS:
                break
        signal_block = ""
        if high_signal_lines:
            signal_block = (
                "// High-signal UI lines extracted for generation:\n"
                + "\n".join(high_signal_lines)
            )
        if signal_block:
            head_budget = max(0, CODE_BRIEF_MAX_UNIT_CHARS - len(signal_block) - 2)
            body = "\n\n".join(
                part
                for part in (head[:head_budget].rstrip(), signal_block)
                if part
            ).strip()
        else:
            body = head[:CODE_BRIEF_MAX_UNIT_CHARS].rstrip()
        unit = f"{header}{body}"
        if len(unit) > remaining:
            unit = unit[:remaining].rstrip()
        chunks.append(unit)
        remaining -= len(unit)

    compacted = "".join(chunks).strip()
    if not compacted:
        return excerpt[:CODE_BRIEF_MAX_SOURCE_CHARS].rstrip()
    return (
        compacted
        + "\n\n[Source excerpt compacted for generation; full source paths and hash are preserved in metadata.]"
    )


def build_editable_code_candidate_brief(candidate: CodePrototypeCandidate) -> str:
    """Build a short user-editable candidate brief shown before generation."""
    source_paths = ", ".join(candidate.source_paths[:4])
    signals = ", ".join(candidate.signals[:6])
    return (
        f"Route: {candidate.route}\n"
        f"Title: {candidate.title}\n"
        f"Primary source: {candidate.primary_source_path}\n"
        f"Related sources: {source_paths}\n"
        f"Framework: {candidate.framework_hint}\n"
        f"Signals: {signals or 'page candidate'}\n\n"
        "Generate a compact, complete static prototype for this page. "
        "Preserve the visible navigation, primary workflow, important controls, "
        "and one representative loading/empty/error state when relevant."
    )


def build_html_system_prompt(brief: str) -> str:
    """Single-file HTML system prompt.

    The prompt is intentionally strict: single file, Tailwind CDN allowed,
    inline JS only, no external dependencies. The trailing `<!DOCTYPE html>`
    anchors the model on the right format and discourages markdown fences.
    """
    return (
        "You are a senior product designer who generates single-file HTML prototypes.\n"
        "Output ONLY a complete HTML document. No markdown, no explanation, no code fences.\n"
        "Strict constraints:\n"
        "- ONE HTML file. Inline all CSS in <style>, all JS in <script>.\n"
        '- Use Tailwind via CDN: <script src="https://cdn.tailwindcss.com"></script>.\n'
        "- Inline any icon set as inline SVG or via emoji; no external CDN fonts/icons.\n"
        '- No <script src="..."> to non-whitelisted hosts. No external CSS files.\n'
        "- The page must render correctly when opened as a static HTML file.\n"
        "- Prefer system font stack; avoid web fonts.\n"
        "- Start the response with <!DOCTYPE html>.\n"
        "- End the response with </html>.\n"
        "- Do not include any commentary before or after the document.\n\n"
        "Output budget:\n"
        "- Complete HTML beats exhaustive detail. Never continue a section if it risks an unfinished document.\n"
        "- Target 70-110 compact lines and fewer than 14,000 characters.\n"
        "- For complex apps, render a representative first viewport plus at most one secondary state, not every panel/row/modal.\n\n"
        f"User brief: {brief.strip()}\n\n"
        "<!DOCTYPE html>"
    )


def build_iteration_system_prompt(latest_html: str, instruction: str) -> str:
    """Refinement prompt: load the latest HTML + apply a delta instruction."""
    return (
        "You are a senior product designer iterating on a single-file HTML prototype.\n"
        "Output ONLY the new complete HTML document. No markdown, no explanation, no code fences.\n"
        "Strict constraints (unchanged):\n"
        "- ONE HTML file. Inline all CSS in <style>, all JS in <script>.\n"
        '- Use Tailwind via CDN: <script src="https://cdn.tailwindcss.com"></script>.\n'
        "- No external dependencies besides the Tailwind CDN.\n"
        "- Start the response with <!DOCTYPE html> and end with </html>.\n"
        "- Preserve what already works; only change what the user's instruction asks for.\n\n"
        "Current HTML:\n"
        f"{latest_html}\n\n"
        f"Refinement instruction: {instruction.strip()}\n\n"
        "<!DOCTYPE html>"
    )


def build_code_backed_brief(
    candidate: CodePrototypeCandidate,
    project: Project,
    runtime_evidence: RuntimePrototypeEvidence | None = None,
    editable_brief_override: str | None = None,
) -> str:
    """Build the seed brief used for a code-backed prototype."""
    source_paths = ", ".join(candidate.source_paths)
    source_excerpt = compact_code_source_excerpt(candidate.source_excerpt)
    editable_override = (editable_brief_override or "").strip()
    runtime_block = ""
    if runtime_evidence is not None:
        runtime_block = (
            "Runtime evidence priority:\n"
            "Use the browser evidence below before source-only inference when it is successful. "
            "If it failed, silently fall back to source context. Treat the evidence as a compact visual brief; "
            "do not try to reproduce every captured text node or structural item.\n\n"
            f"{runtime_evidence.to_prompt_block()}\n\n"
        )
    override_block = ""
    if editable_override:
        override_block = (
            "User-edited candidate brief override:\n"
            f"{editable_override}\n\n"
            "Use this edited brief as the primary page intent. Use runtime evidence and source excerpts only to fill in concrete labels, controls, and visual density.\n\n"
        )
    return (
        f"Generate a faithful static HTML prototype for project '{project.name}'.\n"
        f"Source route: {candidate.route}\n"
        f"Source file(s): {source_paths}\n"
        f"Framework hint: {candidate.framework_hint}\n"
        f"Stable source id: {candidate.id}\n\n"
        "Use the source excerpt below to infer the actual page structure, "
        "information architecture, labels, controls, loading/empty/error states, "
        "and operational density. Use realistic static data where runtime APIs "
        "are unavailable. Preserve the existing app style implied by class names "
        "and component names. Include this traceability comment near the top of "
        f"the HTML: <!-- source: {candidate.route} {candidate.primary_source_path} -->.\n\n"
        f"{runtime_block}"
        f"{override_block}"
        "Completeness and size requirements:\n"
        "- Prefer a compact complete prototype over an exhaustive unfinished one.\n"
        "- Keep the generated HTML short enough to finish within the response budget.\n"
        "- Hard cap yourself at a compact first-screen artifact; omit lower-priority details rather than risking truncation.\n"
        "- Prioritize the first viewport, primary workflow, and navigation structure.\n"
        "- Include at most one of the representative loading/empty/error states, and omit the rest when space is tight.\n"
        "- Summarize repetitive lower-priority sections instead of expanding every item.\n"
        "- Keep the HTML concise: target roughly 80-140 lines, with compact CSS and JS.\n"
        "- For complex admin/workbench pages, make a representative first-screen slice, "
        "not a full product clone.\n"
        "- Do not reproduce every table row, modal variant, settings field, graph node, "
        "or long script; use 2-3 representative samples.\n"
        "- The final output must still be a complete document ending with </html>.\n\n"
        "Source excerpt:\n"
        f"{source_excerpt}"
    )


async def _stream_html(prompt: str, ctx: StreamingPlanContext) -> AsyncIterator[str]:
    """Stream text deltas from an Anthropic-compatible /v1/messages SSE.

    This is `stream_llm` (`llm_runner.py:318`) minus the `{"assistant":
    "{"}` prefill trick. We rely on `<!DOCTYPE html>` from the system
    prompt instead to anchor the output format. The parse loop is otherwise
    the same shape (content_block_delta -> text_delta -> yield).
    """
    url = llm_api_url(ctx.endpoint, "/v1/messages")
    payload = {
        "model": ctx.model,
        "max_tokens": ctx.max_tokens,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": ctx.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    async with _llm_http_client(ctx.timeout_s) as client:  # noqa: SIM117
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(f"prototype stream HTTP {response.status_code}: {body[:300]!r}")
            stop_reason: str | None = None
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "[DONE]"):
                    continue
                event = parse_json_object(raw)
                if event is None:
                    continue
                etype = event.get("type")
                if etype == "content_block_delta":
                    delta = object_dict(event.get("delta"))
                    if delta.get("type") == "text_delta":
                        text = string_value(delta.get("text"))
                        if text:
                            yield text
                elif etype == "message_delta":
                    delta = object_dict(event.get("delta"))
                    raw_stop_reason = delta.get("stop_reason")
                    if isinstance(raw_stop_reason, str):
                        stop_reason = raw_stop_reason
                elif etype == "message_stop":
                    if stop_reason == "max_tokens":
                        raise RuntimeError(
                            "prototype stream stopped before a complete HTML document "
                            "because the model reached its max token limit"
                        )
                    return


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PrototypeService:
    """Owns the prototype + version lifecycle.

    The runtime catalog is loaded lazily on each generate/iterate call so
    edits made mid-session (e.g. via the Settings page) take effect without
    a server restart — same approach as `build_llm_runner` and the
    conductor stream endpoint.
    """

    def __init__(
        self,
        store: AsyncSQLiteStore,
        runtime_catalog_service: RuntimeCatalogLoader,
        discovery_service: CodePrototypeDiscoveryService | None = None,
        runtime_capture_service: RuntimeCaptureService | None = None,
    ) -> None:
        self.store = store
        self.runtime_catalog_service = runtime_catalog_service
        self.discovery_service = discovery_service or CodePrototypeDiscoveryService()
        self.runtime_capture_service = runtime_capture_service

    # --- CRUD pass-throughs ----------------------------------------------------

    async def create(self, project_id: str, title: str, brief: str) -> Prototype:
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypeError(f"project not found: {project_id}")
        title_clean = (title or "").strip() or "Untitled prototype"
        brief_clean = (brief or "").strip()
        if not brief_clean:
            raise PrototypeError("brief is required")
        now = datetime.now()
        prototype = Prototype(
            id=str(uuid4()),
            project_id=project_id,
            title=title_clean,
            framework="html",
            current_version=0,
            source_kind="manual",
            created_at=now,
            updated_at=now,
        )
        await self.store.save_prototype(prototype)
        # Stash the brief on a synthetic v0 metadata field via prototype_versions
        # so generate_stream can read it without an extra column. This row is
        # never shown in the version picker (list_prototype_versions filters
        # out version_no=0 — see note below).
        seed = PrototypeVersion(
            id=str(uuid4()),
            prototype_id=prototype.id,
            version_no=0,
            instruction=brief_clean,
            html="",
            disk_path=None,
            created_at=now,
        )
        await self.store.save_prototype_version(seed)
        return prototype

    async def list_for_project(self, project_id: str) -> list[Prototype]:
        return await self.store.list_prototypes(project_id)

    async def get(self, prototype_id: str) -> Prototype:
        prototype = await self.store.load_prototype(prototype_id)
        if prototype is None:
            raise PrototypeError(f"prototype not found: {prototype_id}")
        return prototype

    async def get_with_versions(self, prototype_id: str) -> dict[str, object]:
        """Detail view: prototype + version metadata (no html bodies)."""
        prototype = await self.get(prototype_id)
        versions = await self.store.list_prototype_versions(prototype_id)
        # Hide the seed v0 row from the UI; it only carries the original brief.
        user_versions = [v for v in versions if v.version_no > 0]
        return {
            "prototype": prototype,
            "versions": user_versions,
        }

    async def get_version_html(self, prototype_id: str, version_no: int) -> str:
        version = await self.store.load_prototype_version(prototype_id, version_no)
        if version is None:
            raise PrototypeError(
                f"version not found: prototype={prototype_id} version={version_no}"
            )
        return version.html

    async def delete(self, prototype_id: str) -> None:
        await self.get(prototype_id)  # 404 surface
        await self.store.delete_prototype(prototype_id)

    # --- Streaming generation --------------------------------------------------

    async def stream_events(
        self, prototype_id: str, instruction: str | None
    ) -> AsyncIterator[StreamEvent]:
        """Yield SSE events for the client.

        Caller is responsible for turning this into `event: <type>\\ndata: ...`
        framing (see api.py).
        """
        prototype = await self.get(prototype_id)
        project = await self.store.load_project(prototype.project_id)
        if project is None:
            raise PrototypeError(f"project missing for prototype: {prototype_id}")

        catalog = await self.runtime_catalog_service.load_catalog()
        ctx = resolve_streaming_context(catalog)
        if ctx is None:
            yield StreamEvent("error", {"message": "no usable LLM executor configured"})
            return

        yield StreamEvent("meta", {"model": ctx.model})

        # Build prompt: instruction → iterate on latest; else use seed brief.
        iteration = (instruction or "").strip()
        if iteration:
            latest = await self.store.load_prototype_version(
                prototype_id, prototype.current_version
            )
            if latest is None or not latest.html:
                yield StreamEvent(
                    "error",
                    {
                        "message": (
                            "cannot iterate: no prior version to refine "
                            f"(prototype {prototype_id} current_version={prototype.current_version})"
                        )
                    },
                )
                return
            prompt = build_iteration_system_prompt(latest.html, iteration)
            next_version = prototype.current_version + 1
            version_instruction = iteration
        else:
            seed = await self.store.load_prototype_version(prototype_id, 0)
            if seed is None or not (seed.instruction or "").strip():
                yield StreamEvent(
                    "error",
                    {"message": f"prototype {prototype_id} has no brief to generate from"},
                )
                return
            prompt = build_html_system_prompt(seed.instruction or "")
            next_version = prototype.current_version + 1
            version_instruction = seed.instruction

        # Stream + accumulate. We deliberately do NOT write the DB row until
        # the model finishes; a mid-stream client disconnect must leave the
        # prototype in a coherent state (version_no unchanged, no orphan
        # version row, no half-written disk file).
        chunks: list[str] = []
        try:
            async for chunk in _stream_html(prompt, ctx):
                chunks.append(chunk)
                yield StreamEvent("delta", {"chunk": chunk})
        except (httpx.TimeoutException, RuntimeError) as exc:
            logger.warning("prototype stream aborted: %s", exc)
            yield StreamEvent("error", {"message": str(exc)})
            return

        raw_html = "".join(chunks)
        cleaned = strip_markdown_fence(raw_html).strip()
        if not cleaned:
            yield StreamEvent("error", {"message": "LLM returned empty HTML"})
            return
        if not is_complete_html_document(cleaned):
            yield StreamEvent(
                "error",
                {
                    "message": (
                        "LLM returned an incomplete HTML document; generation was not saved"
                    )
                },
            )
            return

        # Disk mirror: <repo>/.agent-collab/prototypes/<id>/v<n>/index.html
        version_id = str(uuid4())
        disk_target = self._version_disk_path(project, prototype.id, next_version)
        disk_path: Path | None = disk_target
        try:
            disk_target.parent.mkdir(parents=True, exist_ok=True)
            disk_target.write_text(cleaned, encoding="utf-8")
        except OSError as exc:
            # Disk failure is non-fatal: the DB still holds the html. We
            # log + keep the disk_path as None so the UI doesn't show a
            # broken link.
            logger.warning("prototype disk mirror failed: %s", exc)
            disk_path = None

        now = datetime.now()
        version = PrototypeVersion(
            id=version_id,
            prototype_id=prototype_id,
            version_no=next_version,
            instruction=version_instruction,
            html=cleaned,
            disk_path=str(disk_path) if disk_path else None,
            created_at=now,
        )
        await self.store.save_prototype_version(version)

        yield StreamEvent(
            "done",
            {
                "version_no": version.version_no,
                "html": version.html,
                "disk_path": version.disk_path,
            },
        )

    # --- Project-level batch regen --------------------------------------------

    async def regenerate_all_stream(self, project_id: str) -> AsyncIterator[StreamEvent]:
        """Project-level batch regen: re-run generation for every prototype
        under `project_id` from its original seed brief (i.e. `instruction=None`,
        which is the same path as the first-time generation — no iteration
        drift).

        Serial: one prototype at a time, sharing the single SSE connection
        back to the caller. Inner failures are recorded into `failed` and
        surfaced as `prototype_error` events; we never break the loop on a
        bad prototype so a single LLM hiccup doesn't strand the rest.

        Event contract:
            event: batch_meta       {"count": int}
            event: prototype_start  {"prototype_id", "title"}
            event: prototype_delta  {"prototype_id", "chunk"}    (zero or more)
            event: prototype_done   {"prototype_id", "version_no", "html", "disk_path"}
            event: prototype_error  {"prototype_id", "message"}
            ... (per prototype, in order)
            event: all_done         {"ok": [prototype_id...], "failed": [{"prototype_id","message"}]}
        """
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypeError(f"project not found: {project_id}")

        prototypes = await self.list_for_project(project_id)
        yield StreamEvent("batch_meta", {"count": len(prototypes)})

        ok: list[str] = []
        failed: list[dict[str, str]] = []

        for p in prototypes:
            yield StreamEvent(
                "prototype_start",
                {"prototype_id": p.id, "title": p.title},
            )
            try:
                async for ev in self.stream_events(p.id, instruction=None):
                    if ev.event == "meta":
                        # Outer already announced prototype_start with the title;
                        # the inner model name is noise in the batch view.
                        continue
                    if ev.event == "delta":
                        yield StreamEvent(
                            "prototype_delta",
                            {"prototype_id": p.id, **ev.data},
                        )
                    elif ev.event == "done":
                        ok.append(p.id)
                        yield StreamEvent(
                            "prototype_done",
                            {"prototype_id": p.id, **ev.data},
                        )
                    elif ev.event == "error":
                        message = str(ev.data.get("message", "unknown error"))
                        failed.append({"prototype_id": p.id, "message": message})
                        yield StreamEvent(
                            "prototype_error",
                            {"prototype_id": p.id, "message": message},
                        )
            except Exception as exc:  # noqa: BLE001, RUF100
                # stream_events normally translates all internal failures
                # (timeout, runtime error, empty html, missing seed, ...) into
                # an `error` event and returns cleanly. Anything that bubbles
                # up here is unexpected (e.g. DB write failure); we still
                # record it and keep going so the rest of the batch runs.
                logger.warning("regenerate_all: prototype %s aborted: %s", p.id, exc)
                message = str(exc) or exc.__class__.__name__
                failed.append({"prototype_id": p.id, "message": message})
                yield StreamEvent(
                    "prototype_error",
                    {"prototype_id": p.id, "message": message},
                )

        yield StreamEvent("all_done", {"ok": ok, "failed": failed})

    # --- Code-driven generation ----------------------------------------------

    async def list_code_candidates(self, project_id: str) -> dict[str, object]:
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypeError(f"project not found: {project_id}")
        candidates = self.discovery_service.scan_project(project)
        items: list[dict[str, object]] = []
        counts = {"create": 0, "regenerate": 0, "skip": 0, "unsupported": 0}
        for candidate in candidates:
            existing = await self.store.load_prototype_by_source(project_id, candidate.id)
            action = "create"
            if candidate.unsupported_reason:
                action = "unsupported"
            elif (
                existing
                and existing.current_version > 0
                and existing.source_hash == candidate.source_hash
            ):
                action = "skip"
            elif existing:
                action = "regenerate"
            counts[action] += 1
            item = candidate.to_dict()
            item.update(
                {
                    "editable_brief": build_editable_code_candidate_brief(candidate),
                    "action": action,
                    "prototype_id": existing.id if existing else None,
                }
            )
            items.append(item)
        return {"project_id": project_id, "count": len(items), "counts": counts, "candidates": items}

    async def generate_all_from_code_stream(
        self,
        project_id: str,
        candidate_ids: list[str] | None = None,
        instruction: str | None = None,
        candidate_instructions: dict[str, str] | None = None,
        candidate_brief_overrides: dict[str, str] | None = None,
        runtime_evidence_by_candidate: dict[str, RuntimePrototypeEvidence] | None = None,
        use_runtime_evidence: bool = False,
        runtime_base_url: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        project = await self.store.load_project(project_id)
        if project is None:
            raise PrototypeError(f"project not found: {project_id}")

        selected_ids = {item for item in (candidate_ids or []) if item}
        custom_instruction = (instruction or "").strip()
        candidate_instruction_map = {
            key: value.strip()
            for key, value in (candidate_instructions or {}).items()
            if key and value.strip()
        }
        candidate_brief_override_map = {
            key: value.strip()
            for key, value in (candidate_brief_overrides or {}).items()
            if key and value.strip()
        }
        runtime_evidence_map = runtime_evidence_by_candidate or {}
        runtime_capture_requested = use_runtime_evidence and bool((runtime_base_url or "").strip())
        discovered = self.discovery_service.scan_project(project)
        candidates = [
            candidate
            for candidate in discovered
            if not selected_ids or candidate.id in selected_ids
        ]
        discovered_ids = {candidate.id for candidate in discovered}
        missing_candidate_ids = sorted(selected_ids - discovered_ids)
        classified: list[tuple[CodePrototypeCandidate, Prototype | None, str]] = []
        counts = {"create": 0, "regenerate": 0, "skip": 0, "unsupported": 0}
        for candidate in candidates:
            existing = await self.store.load_prototype_by_source(project_id, candidate.id)
            if candidate.unsupported_reason:
                action = "unsupported"
            elif (
                existing
                and existing.current_version > 0
                and existing.source_hash == candidate.source_hash
                and not custom_instruction
                and candidate.id not in candidate_instruction_map
                and candidate.id not in candidate_brief_override_map
                and candidate.id not in runtime_evidence_map
                and not runtime_capture_requested
            ):
                action = "skip"
            elif existing:
                action = "regenerate"
            else:
                action = "create"
            counts[action] += 1
            classified.append((candidate, existing, action))

        yield StreamEvent(
            "scan_meta",
            {
                "count": len(candidates),
                "created_count": counts["create"],
                "changed_count": counts["regenerate"],
                "unchanged_count": counts["skip"],
                "unsupported_count": counts["unsupported"],
                "requested_count": len(selected_ids) if selected_ids else None,
                "matched_count": len(candidates),
                "missing_candidate_ids": missing_candidate_ids,
                "candidates": [
                    {
                        **candidate.to_dict(),
                        "editable_brief": build_editable_code_candidate_brief(candidate),
                        "action": action,
                        "prototype_id": existing.id if existing else None,
                    }
                    for candidate, existing, action in classified
                ],
            },
        )

        summary = {"created": 0, "regenerated": 0, "skipped": 0, "failed": 0, "unsupported": 0}
        for missing_id in missing_candidate_ids:
            summary["failed"] += 1
            yield StreamEvent(
                "prototype_error",
                {
                    "candidate_id": missing_id,
                    "prototype_id": None,
                    "message": "selected candidate was not found in the latest scan",
                },
            )

        for candidate, existing, action in classified:
            yield StreamEvent(
                "candidate_start",
                {
                    "candidate_id": candidate.id,
                    "route": candidate.route,
                    "title": candidate.title,
                    "action": action,
                },
            )
            if action == "skip":
                summary["skipped"] += 1
                yield StreamEvent(
                    "candidate_skip",
                    {
                        "candidate_id": candidate.id,
                        "prototype_id": existing.id if existing else None,
                        "reason": "unchanged",
                    },
                )
                continue
            if action == "unsupported":
                summary["unsupported"] += 1
                yield StreamEvent(
                    "prototype_error",
                    {
                        "candidate_id": candidate.id,
                        "message": candidate.unsupported_reason or "unsupported candidate",
                    },
                )
                continue

            prototype = existing
            try:
                effective_instruction = self._combined_code_instruction(
                    custom_instruction,
                    candidate_instruction_map.get(candidate.id),
                )
                editable_brief_override = candidate_brief_override_map.get(candidate.id)
                runtime_evidence = runtime_evidence_map.get(candidate.id)
                if runtime_evidence is None and runtime_capture_requested:
                    yield StreamEvent(
                        "candidate_capture",
                        {
                            "candidate_id": candidate.id,
                            "route": candidate.route,
                            "base_url": runtime_base_url,
                        },
                    )
                    runtime_evidence = await self._capture_runtime_evidence(
                        project,
                        candidate,
                        runtime_base_url,
                    )
                    if runtime_evidence.success:
                        yield StreamEvent(
                            "candidate_capture_done",
                            {
                                "candidate_id": candidate.id,
                                "attempted_url": runtime_evidence.attempted_url,
                                "final_url": runtime_evidence.final_url,
                                "screenshot_path": runtime_evidence.screenshot_path,
                            },
                        )
                    else:
                        yield StreamEvent(
                            "candidate_capture_failed",
                            {
                                "candidate_id": candidate.id,
                                "attempted_url": runtime_evidence.attempted_url,
                                "message": runtime_evidence.failure_reason
                                or "runtime capture unavailable",
                            },
                        )
                if prototype is None:
                    prototype = await self._create_code_prototype(
                        project,
                        candidate,
                        instruction=effective_instruction,
                        editable_brief_override=editable_brief_override,
                        runtime_evidence=runtime_evidence,
                    )
                    yield StreamEvent(
                        "prototype_created",
                        {
                            "candidate_id": candidate.id,
                            "prototype_id": prototype.id,
                            "title": prototype.title,
                        },
                    )
                else:
                    await self._refresh_code_seed(
                        project,
                        prototype,
                        candidate,
                        instruction=effective_instruction,
                        editable_brief_override=editable_brief_override,
                        runtime_evidence=runtime_evidence,
                    )

                completed = False
                async for ev in self.stream_events(prototype.id, instruction=None):
                    if ev.event == "meta":
                        continue
                    if ev.event == "delta":
                        yield StreamEvent(
                            "prototype_delta",
                            {
                                "candidate_id": candidate.id,
                                "prototype_id": prototype.id,
                                **ev.data,
                            },
                        )
                    elif ev.event == "done":
                        completed = True
                        await self.store.update_prototype_source_metadata(
                            prototype.id,
                            candidate.source_hash,
                            json.dumps(
                                self._candidate_meta(candidate, runtime_evidence),
                                ensure_ascii=False,
                            ),
                        )
                        if action == "create":
                            summary["created"] += 1
                        else:
                            summary["regenerated"] += 1
                        yield StreamEvent(
                            "prototype_done",
                            {
                                "candidate_id": candidate.id,
                                "prototype_id": prototype.id,
                                **ev.data,
                            },
                        )
                    elif ev.event == "error":
                        raise PrototypeError(str(ev.data.get("message", "unknown error")))
                if not completed:
                    raise PrototypeError("prototype generation ended without a done event")
            except Exception as exc:
                summary["failed"] += 1
                yield StreamEvent(
                    "prototype_error",
                    {
                        "candidate_id": candidate.id,
                        "prototype_id": prototype.id if prototype else None,
                        "message": str(exc) or exc.__class__.__name__,
                    },
                )

        yield StreamEvent("all_done", summary)

    async def _create_code_prototype(
        self,
        project: Project,
        candidate: CodePrototypeCandidate,
        instruction: str | None = None,
        editable_brief_override: str | None = None,
        runtime_evidence: RuntimePrototypeEvidence | None = None,
    ) -> Prototype:
        now = datetime.now()
        prototype = Prototype(
            id=str(uuid4()),
            project_id=project.id,
            title=candidate.title,
            framework="html",
            current_version=0,
            source_kind="code",
            source_ref=candidate.id,
            source_hash=candidate.source_hash,
            source_meta_json=json.dumps(
                self._candidate_meta(candidate, runtime_evidence),
                ensure_ascii=False,
            ),
            created_at=now,
            updated_at=now,
        )
        await self.store.save_prototype(prototype)
        seed = PrototypeVersion(
            id=str(uuid4()),
            prototype_id=prototype.id,
            version_no=0,
            instruction=self._build_code_seed_brief(
                candidate,
                project,
                instruction,
                editable_brief_override,
                runtime_evidence,
            ),
            html="",
            disk_path=None,
            created_at=now,
        )
        await self.store.save_prototype_version(seed)
        return prototype

    async def _refresh_code_seed(
        self,
        project: Project,
        prototype: Prototype,
        candidate: CodePrototypeCandidate,
        instruction: str | None = None,
        editable_brief_override: str | None = None,
        runtime_evidence: RuntimePrototypeEvidence | None = None,
    ) -> None:
        now = datetime.now()
        seed = PrototypeVersion(
            id=str(uuid4()),
            prototype_id=prototype.id,
            version_no=0,
            instruction=self._build_code_seed_brief(
                candidate,
                project,
                instruction,
                editable_brief_override,
                runtime_evidence,
            ),
            html="",
            disk_path=None,
            created_at=now,
        )
        await self.store.save_prototype_version(seed)

    def _build_code_seed_brief(
        self,
        candidate: CodePrototypeCandidate,
        project: Project,
        instruction: str | None,
        editable_brief_override: str | None = None,
        runtime_evidence: RuntimePrototypeEvidence | None = None,
    ) -> str:
        brief = build_code_backed_brief(
            candidate,
            project,
            runtime_evidence,
            editable_brief_override,
        )
        clean_instruction = (instruction or "").strip()
        if not clean_instruction:
            return brief
        return (
            f"{brief}\n\n"
            "Additional user guidance for this selected generation run:\n"
            f"{clean_instruction}"
        )

    def _combined_code_instruction(
        self,
        shared_instruction: str | None,
        candidate_instruction: str | None,
    ) -> str | None:
        parts = []
        shared = (shared_instruction or "").strip()
        candidate = (candidate_instruction or "").strip()
        if shared:
            parts.append(f"Shared guidance: {shared}")
        if candidate:
            parts.append(f"Candidate-specific guidance: {candidate}")
        return "\n".join(parts) if parts else None

    async def _capture_runtime_evidence(
        self,
        project: Project,
        candidate: CodePrototypeCandidate,
        runtime_base_url: str | None,
    ) -> RuntimePrototypeEvidence:
        if self.runtime_capture_service is None:
            return RuntimePrototypeEvidence(
                success=False,
                failure_reason="runtime capture service is not configured",
            )
        return await self.runtime_capture_service.capture_candidate(
            project,
            candidate,
            runtime_base_url,
        )

    def _candidate_meta(
        self,
        candidate: CodePrototypeCandidate,
        runtime_evidence: RuntimePrototypeEvidence | None = None,
    ) -> dict[str, object]:
        meta: dict[str, object] = {
            "route": candidate.route,
            "kind": candidate.kind,
            "framework_hint": candidate.framework_hint,
            "source_paths": candidate.source_paths,
            "primary_source_path": candidate.primary_source_path,
            "signals": candidate.signals,
        }
        if runtime_evidence is not None:
            meta["runtime_evidence"] = runtime_evidence.to_meta()
        return meta

    # --- Disk helpers ----------------------------------------------------------

    @staticmethod
    def _version_disk_path(project: Project, prototype_id: str, version_no: int) -> Path:
        return (
            Path(project.repo_path)
            / ".agent-collab"
            / "prototypes"
            / prototype_id
            / f"v{version_no}"
            / "index.html"
        )


# ---------------------------------------------------------------------------
# Self-test (CLI): `python -m app.application.prototype_service`
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover - manual smoke
    logger.info(
        "build_html_system_prompt('pricing page') -> %s ...",
        build_html_system_prompt("pricing page")[:120],
    )
    sample = "```html\n<!DOCTYPE html>\n<html></html>\n```"
    logger.info("strip_markdown_fence -> %s", strip_markdown_fence(sample)[:60])
