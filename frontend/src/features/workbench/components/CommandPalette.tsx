"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Inbox, FileBox, FileText, GitBranch, Library, Loader2, Search, ShieldCheck, Users } from "lucide-react";
import { getCodexIssues, getWorkspaces, listProjects, searchKnowledge } from "@/lib/api";
import type { CodexIssue, Project, Workspace } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Hit {
  id: string;
  kind: "issue" | "workspace" | "project" | "nav" | "artifact" | "knowledge-link";
  label: string;
  hint?: string;
  href: string;
  snippet?: string;
}

const NAV_ITEMS = [
  { id: "nav-inbox", kind: "nav" as const, labelKey: "cmd.inbox", hintKey: "cmd.inboxHint", href: "/" },
  { id: "nav-projects", kind: "nav" as const, labelKey: "nav.workspace", hintKey: "cmd.projectsHint", href: "/projects" },
  { id: "nav-approvals", kind: "nav" as const, labelKey: "cmd.approvals", hintKey: "cmd.approvalsHint", href: "/approvals" },
  { id: "nav-artifacts", kind: "nav" as const, labelKey: "cmd.artifacts", hintKey: "cmd.artifactsHint", href: "/artifacts" },
  { id: "nav-knowledge", kind: "nav" as const, labelKey: "sidebar.knowledge", hintKey: "knowledge.subtitle", href: "/knowledge" },
  { id: "nav-agents", kind: "nav" as const, labelKey: "cmd.agents", hintKey: "cmd.agentsHint", href: "/agents" },
  { id: "nav-settings", kind: "nav" as const, labelKey: "cmd.settings", hintKey: "cmd.settingsHint", href: "/settings" },
];

/**
 * ⌘K palette — fuzzy filter across issues + workspaces + projects + nav.
 *
 * Lazy-loads the candidate list on first open and caches in memory so
 * subsequent open-close cycles are instant. Arrow keys + enter to pick;
 * esc to close.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [ftsIssueHits, setFtsIssueHits] = useState<Hit[]>([]);
  const [ftsArtifactHits, setFtsArtifactHits] = useState<Hit[]>([]);
  const fetchedRef = useRef(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const ftsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Lazy fetch on first open.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelectedIdx(0);
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    setLoading(true);
    void Promise.all([
      getCodexIssues(null, null),
      getWorkspaces(null),
      listProjects(),
    ])
      .then(([iss, ws, pr]) => {
        setIssues(iss);
        setWorkspaces(ws);
        setProjects(pr);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (open) {
      // Focus after Sheet animation begins.
      const id = window.setTimeout(() => inputRef.current?.focus(), 50);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // Knowledge FTS: debounced backend search to back up the local fuzzy match.
  // Fires only when the query is non-trivial (>=2 chars) so blank palette
  // doesn't pound the API.
  useEffect(() => {
    if (ftsDebounceRef.current) clearTimeout(ftsDebounceRef.current);
    const q = query.trim();
    if (!open || q.length < 2) {
      setFtsIssueHits([]);
      setFtsArtifactHits([]);
      return;
    }
    ftsDebounceRef.current = setTimeout(() => {
      void searchKnowledge({ q, scope: "all", mode: "fts", limit: 10 })
        .then((res) => {
          setFtsIssueHits(
            res.issues.slice(0, 5).map((h) => ({
              id: `fts-issue-${h.issue_id}`,
              kind: "issue" as const,
              label: h.title || h.issue_id,
              hint: h.snippet?.replace(/<\/?mark>/g, ""),
              href: `/issues/${h.issue_id}`,
            })),
          );
          setFtsArtifactHits(
            res.artifacts.slice(0, 5).map((h) => ({
              id: `fts-artifact-${h.artifact_id}`,
              kind: "artifact" as const,
              label: h.name || h.artifact_id,
              hint: h.role,
              href: `/issues/${h.issue_id}?tab=artifacts`,
              snippet: h.snippet,
            })),
          );
        })
        .catch(() => {
          setFtsIssueHits([]);
          setFtsArtifactHits([]);
        });
    }, 180);
    return () => {
      if (ftsDebounceRef.current) clearTimeout(ftsDebounceRef.current);
    };
  }, [open, query]);

  const hits = useMemo<Hit[]>(() => {
    const q = query.trim().toLowerCase();
    const match = (text: string) => !q || text.toLowerCase().includes(q);

    const issueHits: Hit[] = issues
      .filter((i) => match(i.title || "") || match(i.id))
      .slice(0, 12)
      .map((i) => ({
        id: `issue-${i.id}`,
        kind: "issue",
        label: i.title || i.id.slice(0, 8),
        hint: i.git_branch ?? undefined,
        href: `/issues/${i.id}`,
      }));
    const wsHits: Hit[] = workspaces
      .filter((w) => match(w.title || "") || match(w.id))
      .slice(0, 6)
      .map((w) => ({
        id: `ws-${w.id}`,
        kind: "workspace",
        label: w.title || `Workspace #${w.id.slice(0, 8)}`,
        hint: w.cwd ?? undefined,
        href: `/workspaces/${w.id}`,
      }));
    const projHits: Hit[] = projects
      .filter((p) => match(p.name || ""))
      .slice(0, 6)
      .map((p) => ({
        id: `proj-${p.id}`,
        kind: "project",
        label: p.name,
        hint: p.repo_path ?? undefined,
        href: `/projects/${p.id}`,
      }));
    const navHits = NAV_ITEMS.filter((n) => match(t(n.labelKey))).map((n) => ({
      ...n,
      label: t(n.labelKey),
      hint: t(n.hintKey),
    }));

    // Merge FTS hits in front of local fuzzy hits, dedup by id.
    const seen = new Set<string>();
    const merged: Hit[] = [];
    for (const h of [...ftsIssueHits, ...issueHits, ...ftsArtifactHits]) {
      const key = h.kind + ":" + h.href;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(h);
    }
    const trailing: Hit[] = [...wsHits, ...projHits, ...navHits];
    const out = [...merged, ...trailing];

    // "Search in Knowledge" CTA when query has something
    if (q && (ftsIssueHits.length || ftsArtifactHits.length || out.length)) {
      out.push({
        id: "nav-knowledge-search",
        kind: "knowledge-link",
        label: `${t("knowledge.searchInKnowledge")} "${q.slice(0, 24)}"`,
        href: `/knowledge?q=${encodeURIComponent(q)}`,
      });
    }

    return out;
  }, [query, issues, workspaces, projects, ftsIssueHits, ftsArtifactHits, t]);

  useEffect(() => {
    if (selectedIdx >= hits.length) setSelectedIdx(0);
  }, [hits.length, selectedIdx]);

  if (!open) return null;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const hit = hits[selectedIdx];
      if (hit) {
        router.push(hit.href);
        onClose();
      }
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-24 bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl rounded-xl bg-popover shadow-2xl ring-1 ring-foreground/10 overflow-hidden flex flex-col"
      >
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-subtle">
          <Search size={14} className="text-text-muted shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Jump to issue / workspace / page…"
            className="flex-1 bg-transparent outline-none text-[14px] placeholder:text-text-muted"
          />
          {loading && <Loader2 size={12} className="animate-spin text-text-muted" />}
          <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-surface-input text-text-muted border border-border-subtle">
            esc
          </kbd>
        </div>
        <div className="max-h-[60vh] overflow-auto py-1">
          {hits.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-text-muted">
              {loading ? "Loading…" : "Nothing matches."}
            </div>
          )}
          {hits.map((hit, i) => (
            <button
              key={hit.id}
              type="button"
              onMouseEnter={() => setSelectedIdx(i)}
              onClick={() => {
                router.push(hit.href);
                onClose();
              }}
              className={cn(
                "w-full px-3 py-2 flex items-center gap-2.5 text-left text-[13px]",
                i === selectedIdx ? "bg-brand/10" : "hover:bg-surface-hover",
              )}
            >
              <HitIcon kind={hit.kind} />
              <div className="min-w-0 flex-1">
                <div className="truncate">{hit.label}</div>
                {hit.hint && (
                  <div className="text-[10px] text-text-muted font-mono truncate">
                    {hit.hint}
                  </div>
                )}
              </div>
              <span className="text-[10px] uppercase tracking-wider text-text-muted shrink-0">
                {hit.kind}
              </span>
            </button>
          ))}
        </div>
        <div className="px-3 py-1.5 border-t border-border-subtle text-[10px] text-text-muted flex justify-between">
          <span>↑↓ navigate · ↵ open · esc close</span>
          <span>{hits.length} {hits.length === 1 ? "result" : "results"}</span>
        </div>
      </div>
    </div>
  );
}

function HitIcon({ kind }: { kind: Hit["kind"] }) {
  const cls = "text-text-muted shrink-0";
  if (kind === "issue") return <GitBranch size={13} className={cls} />;
  if (kind === "workspace") return <Inbox size={13} className={cls} />;
  if (kind === "project") return <FileBox size={13} className={cls} />;
  if (kind === "artifact") return <FileText size={13} className={cls} />;
  if (kind === "knowledge-link") return <Library size={13} className={cls} />;
  if (kind === "nav") {
    return <Users size={13} className={cls} />;
  }
  return <ShieldCheck size={13} className={cls} />;
}
