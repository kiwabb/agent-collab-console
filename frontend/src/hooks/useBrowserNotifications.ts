"use client";

import { useEffect, useRef } from "react";
import { getCodexIssues } from "@/lib/api";
import type { CodexIssue } from "@/lib/types";

/**
 * Surfaces awaiting/completed/failed issue transitions through the browser
 * itself, so the user notices something happened even when this tab is
 * backgrounded:
 *
 *   - Tab title prefixed with `(N) ` where N is items that need attention
 *     (awaiting_approval + awaiting_review + just-failed in last 5 min).
 *   - Favicon overlaid with a tint dot when N > 0.
 *   - System Notification API push on every fresh transition (one per
 *     issue change, throttled by id+status memo so re-renders don't spam).
 *
 * Mount once at the WorkbenchShell level; the hook polls the global issue
 * list and diffs against its memory of the last snapshot.
 */
const POLL_INTERVAL_MS = 7000;
const ATTENTION_STATUSES = new Set(["awaiting_approval", "review"]);
const TERMINAL_STATUSES = new Set(["completed", "done", "failed"]);
const FAVICON_DOT_DATA_URL =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#e69552"/><text x="16" y="22" text-anchor="middle" font-family="Inter,sans-serif" font-size="20" font-weight="700" fill="#000">C</text><circle cx="25" cy="7" r="6" fill="#ef4444"/></svg>`,
  );
const FAVICON_DEFAULT_DATA_URL =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#e69552"/><text x="16" y="22" text-anchor="middle" font-family="Inter,sans-serif" font-size="20" font-weight="700" fill="#000">C</text></svg>`,
  );

function setFavicon(href: string) {
  if (typeof document === "undefined") return;
  let link = document.querySelector<HTMLLinkElement>("link[rel*='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.href = href;
}

const ORIGINAL_TITLE = typeof document !== "undefined" ? document.title : "";

function setTitleAttention(count: number) {
  if (typeof document === "undefined") return;
  const base = ORIGINAL_TITLE || "Agent Collaboration Workbench";
  document.title = count > 0 ? `(${count}) ${base}` : base;
  setFavicon(count > 0 ? FAVICON_DOT_DATA_URL : FAVICON_DEFAULT_DATA_URL);
}

interface SnapshotRow {
  status: string;
  title: string;
  updated: number;
}

export function useBrowserNotifications(): void {
  const lastSnapshot = useRef<Map<string, SnapshotRow>>(new Map());
  const permissionRef = useRef<NotificationPermission | "unsupported">("unsupported");
  const armedRef = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (typeof Notification !== "undefined") {
      permissionRef.current = Notification.permission;
      // Best-effort opt-in on the first tab interaction. We ask once and
      // remember the answer; never re-prompt.
      const askOnce = () => {
        if (Notification.permission === "default") {
          void Notification.requestPermission().then((perm) => {
            permissionRef.current = perm;
          });
        }
        window.removeEventListener("click", askOnce);
      };
      window.addEventListener("click", askOnce, { once: true });
    }

    let cancelled = false;
    armedRef.current = true;

    async function tick() {
      try {
        const issues = await getCodexIssues(null, null);
        if (cancelled) return;
        const next = new Map<string, SnapshotRow>();
        let attention = 0;
        for (const i of issues) {
          const status = i.status ?? "open";
          if (ATTENTION_STATUSES.has(status)) attention += 1;
          next.set(i.id, {
            status,
            title: i.title || i.id.slice(0, 8),
            updated: new Date(i.updated_at ?? i.created_at ?? 0).getTime(),
          });
        }
        diffAndNotify(lastSnapshot.current, next, issues, permissionRef.current);
        lastSnapshot.current = next;
        setTitleAttention(attention);
      } catch {
        // Network blip — try again next tick.
      }
    }

    void tick();
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      armedRef.current = false;
      window.clearInterval(id);
      setTitleAttention(0);
    };
  }, []);
}

function diffAndNotify(
  prev: Map<string, SnapshotRow>,
  next: Map<string, SnapshotRow>,
  issues: CodexIssue[],
  permission: NotificationPermission | "unsupported",
): void {
  // On the very first tick `prev` is empty — treat that as bootstrap, no
  // notifications. We only want to fire on actual transitions.
  if (prev.size === 0) return;
  for (const issue of issues) {
    const before = prev.get(issue.id);
    const after = next.get(issue.id);
    if (!after) continue;
    if (!before) {
      // Brand new issue → quiet (the creator already knows).
      continue;
    }
    if (before.status === after.status) continue;

    const becameAttention = ATTENTION_STATUSES.has(after.status) && !ATTENTION_STATUSES.has(before.status);
    const becameTerminal = TERMINAL_STATUSES.has(after.status) && !TERMINAL_STATUSES.has(before.status);
    if (!becameAttention && !becameTerminal) continue;

    if (permission === "granted" && typeof Notification !== "undefined") {
      const verb = becameAttention
        ? "needs your review"
        : after.status === "failed"
          ? "failed"
          : "is done";
      try {
        const note = new Notification(`Issue ${verb}`, {
          body: after.title,
          icon: "/favicon.ico",
          tag: `issue-${issue.id}`,
        });
        note.onclick = () => {
          window.focus();
          window.location.assign(`/issues/${issue.id}`);
          note.close();
        };
      } catch {
        // Notification API can throw on permission edge cases — silent.
      }
    }
  }
}
