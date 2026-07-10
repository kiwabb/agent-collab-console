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


import logging  # noqa: E402
import os  # noqa: E402, F401
import re  # noqa: E402
from collections.abc import AsyncIterator, Mapping  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Protocol  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402

from app.adapters.async_sqlite_store import AsyncSQLiteStore  # noqa: E402
from app.application.llm_runner import (  # noqa: E402
    StreamingPlanContext,
    _llm_http_client,
    llm_api_url,
    resolve_streaming_context,
)
from app.domain.models import Project, Prototype, PrototypeVersion, RuntimeCatalog  # noqa: E402
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



_MD_FENCE = re.compile(r"^```(?:html|HTML)?\s*\n(.*?)\n```\s*$", re.DOTALL)


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
    ) -> None:
        self.store = store
        self.runtime_catalog_service = runtime_catalog_service

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
