"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, RefreshCw, FileText, Hash } from "lucide-react";
import {
  getEmbeddingStatus,
  searchKnowledge,
  triggerKnowledgeReindex,
  type EmbeddingStatus,
  type KnowledgeSearchResponse,
  type KnowledgeSearchMode,
  type KnowledgeSearchScope,
} from "@/lib/api/knowledge";
import { listProjects } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { TeamNotesEditor } from "./TeamNotesEditor";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { EmptyStateAction, InteractionEmptyState } from "@/components/ui/interaction-empty-state";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { cn } from "@/lib/utils";

type Tab = "search" | "team-notes";

const MODES: { value: KnowledgeSearchMode; key: string }[] = [
  { value: "hybrid", key: "knowledge.mode.hybrid" },
  { value: "fts", key: "knowledge.mode.fts" },
  { value: "semantic", key: "knowledge.mode.semantic" },
];

const SCOPES: { value: KnowledgeSearchScope; key: string }[] = [
  { value: "all", key: "knowledge.scope.all" },
  { value: "issues", key: "knowledge.scope.issues" },
  { value: "artifacts", key: "knowledge.scope.artifacts" },
];

export function KnowledgePage() {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<Tab>("search");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectFilter, setProjectFilter] = useState<string>("");
  const [scope, setScope] = useState<KnowledgeSearchScope>("all");
  const [mode, setMode] = useState<KnowledgeSearchMode>("hybrid");
  const [query, setQuery] = useState<string>("");
  const [results, setResults] = useState<KnowledgeSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [reindexedAt, setReindexedAt] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void listProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
    void getEmbeddingStatus()
      .then(setEmbedding)
      .catch(() => setEmbedding(null));
  }, []);

  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setQuery(q);
  }, [searchParams]);

  const runSearch = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResults(null);
        return;
      }
      setLoading(true);
      try {
        const data = await searchKnowledge({
          q,
          scope,
          mode,
          limit: 25,
          ...(projectFilter ? { projectId: projectFilter } : {}),
        });
        setResults(data);
      } catch {
        setResults({ issues: [], artifacts: [], mode, query: q });
      } finally {
        setLoading(false);
      }
    },
    [scope, mode, projectFilter],
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void runSearch(query);
    }, 220);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, runSearch]);

  const handleReindex = useCallback(async () => {
    setReindexing(true);
    try {
      const stats = await triggerKnowledgeReindex(projectFilter || undefined);
      const msg = `${stats.indexed_issues}+${stats.indexed_artifacts}`;
      setReindexedAt(new Date().toLocaleTimeString() + " · " + msg);
      void runSearch(query);
    } finally {
      setReindexing(false);
    }
  }, [projectFilter, query, runSearch]);

  const total = (results?.issues.length || 0) + (results?.artifacts.length || 0);

  return (
    <PageFrame
      eyebrow={t("knowledge.title")}
      title={t("knowledge.title")}
      description={t("knowledge.subtitle")}
      actions={
        <>
          <span
            className={
              embedding?.enabled
                ? "inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-400 text-xs"
                : "inline-flex items-center gap-1 rounded-full bg-zinc-500/15 px-2 py-0.5 text-text-muted text-xs"
            }
            title={embedding?.model || ""}
          >
            <span className="inline-block size-1.5 rounded-full bg-current" />
            {embedding?.enabled
              ? t("knowledge.embedding.online")
              : t("knowledge.embedding.offline")}
          </span>
          <button
            type="button"
            onClick={handleReindex}
            disabled={reindexing}
            data-density={reindexing ? "knowledge-reindex-tool" : "knowledge-reindex"}
            className={cn(
              "inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-50",
              reindexing && "motion-essential",
            )}
          >
            {reindexing ? (
              <AgentThinkingIndicator phase="tool" size={12} />
            ) : (
              <RefreshCw size={12} />
            )}
            {t("knowledge.reindex")}
          </button>
        </>
      }
      contentClassName="space-y-4"
    >
      <nav className="enterprise-card flex items-center gap-2 rounded-2xl px-2 text-xs">
        <TabButton active={tab === "search"} onClick={() => setTab("search")}>
          {t("knowledge.tab.search")}
        </TabButton>
        <TabButton active={tab === "team-notes"} onClick={() => setTab("team-notes")}>
          {t("knowledge.tab.teamNotes")}
        </TabButton>
        {reindexedAt && (
          <span className="ml-auto text-text-muted">
            {t("knowledge.lastReindex")}: {reindexedAt}
          </span>
        )}
      </nav>

      {tab === "search" ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="enterprise-card flex flex-wrap items-center gap-2 rounded-2xl p-2">
            <div className="flex flex-1 items-center gap-2 rounded-xl border border-border-subtle bg-surface-input/80 px-3 py-2 min-w-[260px]">
              <Search size={14} className="text-text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("knowledge.searchPlaceholder")}
                className="flex-1 bg-transparent text-sm outline-none"
              />
              {loading && <span className="text-xs text-text-muted">…</span>}
            </div>
            <select
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
              className="rounded-xl border border-border-subtle bg-surface-input px-2 py-2 text-xs"
            >
              <option value="">{t("knowledge.allProjects")}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-1 rounded-xl border border-border-subtle bg-surface/70 p-0.5 text-[11px]">
              {SCOPES.map((s) => (
                <button
                  key={s.value}
                  onClick={() => setScope(s.value)}
                  className={
                    scope === s.value
                      ? "rounded px-1.5 py-0.5 bg-brand/15 text-brand"
                      : "rounded px-1.5 py-0.5 text-text-muted hover:text-foreground"
                  }
                >
                  {t(s.key)}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1 rounded-xl border border-border-subtle bg-surface/70 p-0.5 text-[11px]">
              {MODES.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setMode(m.value)}
                  disabled={m.value === "semantic" && !embedding?.enabled}
                  className={
                    mode === m.value
                      ? "rounded px-1.5 py-0.5 bg-brand/15 text-brand"
                      : "rounded px-1.5 py-0.5 text-text-muted hover:text-foreground disabled:opacity-30"
                  }
                  title={
                    m.value === "semantic" && !embedding?.enabled
                      ? t("knowledge.embedding.semanticUnavailable")
                      : ""
                  }
                >
                  {t(m.key)}
                </button>
              ))}
            </div>
          </div>

          <div className="flex min-h-0 flex-1 gap-3">
            <section className="enterprise-panel min-h-0 flex-1 overflow-auto rounded-2xl">
              {!query.trim() ? (
                <InteractionEmptyState
                  title={t("knowledge.emptyHint")}
                  description={t("knowledge.emptyDescription")}
                  action={
                    <EmptyStateAction onClick={() => void handleReindex()}>
                      {t("knowledge.reindex")}
                    </EmptyStateAction>
                  }
                />
              ) : !results || total === 0 ? (
                <InteractionEmptyState
                  tone={loading ? "loading" : "empty"}
                  title={loading ? t("knowledge.loading") : t("knowledge.noResults")}
                  description={t("knowledge.noResultsHint")}
                  action={
                    <EmptyStateAction onClick={() => setQuery("")}>
                      {t("knowledge.clearQuery")}
                    </EmptyStateAction>
                  }
                />
              ) : (
                <ul className="divide-y divide-border text-sm">
                  {results.issues.map((hit) => (
                    <li
                      key={`i:${hit.issue_id}`}
                      onClick={() => router.push(`/issues/${hit.issue_id}`)}
                      className="flex cursor-pointer items-start gap-2 p-3 hover:bg-surface-hover"
                    >
                      <Hash size={14} className="mt-0.5 text-text-muted" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">{hit.title || hit.issue_id}</span>
                          {hit.source && (
                            <span className="rounded bg-brand/10 px-1 py-px text-[10px] text-brand">
                              {hit.source}
                            </span>
                          )}
                        </div>
                        {hit.snippet && (
                          <p
                            className="mt-1 truncate text-xs text-text-muted"
                            dangerouslySetInnerHTML={{ __html: hit.snippet }}
                          />
                        )}
                      </div>
                    </li>
                  ))}
                  {results.artifacts.map((hit) => (
                    <li
                      key={`a:${hit.artifact_id}`}
                      onClick={() => router.push(`/issues/${hit.issue_id}?tab=artifacts`)}
                      className="flex cursor-pointer items-start gap-2 p-3 hover:bg-surface-hover"
                    >
                      <FileText size={14} className="mt-0.5 text-text-muted" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">{hit.name}</span>
                          {hit.role && (
                            <span className="rounded bg-zinc-500/15 px-1 py-px text-[10px] text-text-muted">
                              {hit.role}
                            </span>
                          )}
                          {hit.source && (
                            <span className="rounded bg-brand/10 px-1 py-px text-[10px] text-brand">
                              {hit.source}
                            </span>
                          )}
                        </div>
                        {hit.snippet && (
                          <p
                            className="mt-1 line-clamp-2 text-xs text-text-muted"
                            dangerouslySetInnerHTML={{ __html: hit.snippet }}
                          />
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      ) : (
        <TeamNotesEditor
          projects={projects}
          projectId={projectFilter || projects[0]?.id || ""}
          onProjectChange={setProjectFilter}
        />
      )}
    </PageFrame>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "border-b-2 border-brand px-2 py-1.5 font-medium text-foreground"
          : "border-b-2 border-transparent px-2 py-1.5 text-text-muted hover:text-foreground"
      }
    >
      {children}
    </button>
  );
}

// Helper hook unused right now but kept for memoization affordances.
export function useStableSearchKey(...args: unknown[]) {
  return useMemo(() => args.join("|"), [args]);
}
