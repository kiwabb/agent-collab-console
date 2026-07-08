"""Runtime browser evidence capture for code-backed prototypes.

The service is intentionally conservative: it never starts install commands or
dev servers. Callers must provide a base URL for an already-running app. If a
browser adapter is unavailable or navigation fails, the service returns typed
failure evidence so generation can fall back to source-only context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urljoin

from app.application.code_prototype_discovery import CodePrototypeCandidate
from app.application.prototype_service import RuntimePrototypeEvidence
from app.domain.models import Project

if TYPE_CHECKING:
    from playwright.async_api import ViewportSize

CAPTURE_TEXT_MAX_CHARS = 1800
CAPTURE_STRUCTURE_MAX_ITEMS = 40
CAPTURE_CONSOLE_ERROR_MAX_ITEMS = 8
CAPTURE_TIMEOUT_MS = 5000
CAPTURE_VIEWPORT = {"width": 1440, "height": 900}


@dataclass(frozen=True)
class ResolvedRuntimeRoute:
    attempted_url: str
    route_path: str


def resolve_runtime_route(base_url: str, route: str) -> ResolvedRuntimeRoute:
    base = base_url.strip().rstrip("/") + "/"
    path = (route or "/").strip() or "/"
    path = re.sub(r":wsId\b", "demo-ws", path)
    path = re.sub(r":id\b", "demo-id", path)
    path = re.sub(r":([A-Za-z0-9_]+)\b", "demo", path)
    path = re.sub(r"\[\[\.\.\.[^\]]+\]\]", "demo", path)
    path = re.sub(r"\[\.\.\.[^\]]+\]", "demo", path)
    path = re.sub(r"\[[^\]]+\]", "demo", path)
    path = "/" + path.lstrip("/")
    return ResolvedRuntimeRoute(attempted_url=urljoin(base, path.lstrip("/")), route_path=path)


class RuntimePrototypeCaptureService:
    async def capture_candidate(
        self,
        project: Project,
        candidate: CodePrototypeCandidate,
        base_url: str | None,
    ) -> RuntimePrototypeEvidence:
        clean_base_url = (base_url or "").strip()
        if not clean_base_url:
            return RuntimePrototypeEvidence(
                success=False,
                failure_reason="runtime base URL was not provided",
            )
        resolved = resolve_runtime_route(clean_base_url, candidate.route)
        try:
            return await self._capture_with_playwright(project, resolved)
        except ModuleNotFoundError:
            return RuntimePrototypeEvidence(
                attempted_url=resolved.attempted_url,
                success=False,
                failure_reason="python playwright is not installed in the backend environment",
            )
        except Exception as exc:
            return RuntimePrototypeEvidence(
                attempted_url=resolved.attempted_url,
                success=False,
                failure_reason=str(exc) or exc.__class__.__name__,
            )

    async def _capture_with_playwright(
        self,
        project: Project,
        resolved: ResolvedRuntimeRoute,
    ) -> RuntimePrototypeEvidence:
        from playwright.async_api import async_playwright

        console_errors: list[str] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(viewport=cast("ViewportSize", CAPTURE_VIEWPORT))
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text)
                    if msg.type in {"error", "warning"}
                    and len(console_errors) < CAPTURE_CONSOLE_ERROR_MAX_ITEMS
                    else None,
                )
                response = await page.goto(
                    resolved.attempted_url,
                    wait_until="networkidle",
                    timeout=CAPTURE_TIMEOUT_MS,
                )
                title = await page.title()
                visible_text = await page.locator("body").inner_text(timeout=1000)
                structure = await page.evaluate(
                    """() => {
                      const pick = (selector) => Array.from(document.querySelectorAll(selector))
                        .slice(0, 40)
                        .map((el) => (el.innerText || el.getAttribute('aria-label') || el.textContent || '').trim())
                        .filter(Boolean)
                        .slice(0, 12);
                      return {
                        headings: pick('h1,h2,h3'),
                        buttons: pick('button,[role="button"]'),
                        links: pick('a[href]'),
                        inputs: Array.from(document.querySelectorAll('input,textarea,select'))
                          .slice(0, 12)
                          .map((el) => el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('name') || el.tagName.toLowerCase())
                          .filter(Boolean),
                        landmarks: Array.from(document.querySelectorAll('header,nav,main,aside,footer,section'))
                          .slice(0, 12)
                          .map((el) => el.tagName.toLowerCase())
                      };
                    }"""
                )
                screenshot_path = self._screenshot_path(project, resolved.route_path)
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path), full_page=False)
                status = response.status if response is not None else None
                return RuntimePrototypeEvidence(
                    attempted_url=resolved.attempted_url,
                    final_url=page.url,
                    success=status is None or status < 400,
                    title=title,
                    viewport=dict(CAPTURE_VIEWPORT),
                    visible_text_excerpt=visible_text[:CAPTURE_TEXT_MAX_CHARS],
                    structure_summary=_summarize_structure(structure),
                    console_errors=console_errors[:CAPTURE_CONSOLE_ERROR_MAX_ITEMS],
                    screenshot_path=str(screenshot_path),
                    failure_reason=None if status is None or status < 400 else f"HTTP {status}",
                )
            finally:
                await browser.close()

    def _screenshot_path(self, project: Project, route_path: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", route_path.strip("/") or "root").strip("-")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return Path(project.repo_path) / ".agent-collab" / "prototypes" / "runtime-captures" / f"{slug}-{stamp}.png"


def _summarize_structure(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    lines: list[str] = []
    for key in ("headings", "buttons", "links", "inputs", "landmarks"):
        raw_items = value.get(key)
        if not isinstance(raw_items, list):
            continue
        items = [str(item).strip() for item in raw_items if str(item).strip()]
        if not items:
            continue
        lines.append(f"{key}: {', '.join(items)[:500]}")
        if len(lines) >= CAPTURE_STRUCTURE_MAX_ITEMS:
            break
    return "\n".join(lines)
