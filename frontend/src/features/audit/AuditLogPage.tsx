"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import { getAuditLog, type AuditLog, type AuditLogCategory } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { useI18n } from "@/providers/I18nProvider";
import { normalizeSince, normalizeUntil } from "./timeBoundary";

const CATEGORIES: AuditLogCategory[] = [
  "llm_call",
  "llm_return",
  "tool_use",
  "tool_result",
  "command_exec",
  "git_command",
  "cli_spawn",
  "event",
  "agent_finalize",
];

const PAGE_LIMIT = 50;

/** Map category -> badge variant + accent color class. */
const CATEGORY_STYLE: Record<string, string> = {
  llm_call: "border-brand/40 bg-brand/10 text-brand",
  llm_return: "border-brand/40 bg-brand/10 text-brand",
  tool_use: "border-status-awaiting/40 bg-status-awaiting/10 text-status-awaiting",
  tool_result: "border-status-awaiting/40 bg-status-awaiting/10 text-status-awaiting",
  command_exec: "border-status-done/40 bg-status-done/10 text-status-done",
  git_command: "border-status-done/40 bg-status-done/10 text-status-done",
  cli_spawn: "border-border-subtle bg-surface-input/60 text-text-secondary",
  event: "border-border-subtle bg-surface-input/60 text-text-muted",
  agent_finalize: "border-brand/40 bg-brand/10 text-brand",
};

function categoryClass(category: string): string {
  return CATEGORY_STYLE[category] ?? "border-border-subtle bg-surface-input/60 text-text-muted";
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/** Build a short one-line summary of a row from its parsed payload. */
function summarize(parsed: unknown, entry: AuditLog): string {
  if (entry.error) return entry.error;
  if (parsed && typeof parsed === "object") {
    const p = parsed as Record<string, unknown>;
    const candidate =
      p.name ?? p.tool ?? p.command ?? p.model ?? p.cmd ?? p.message ?? p.type ?? p.summary;
    if (typeof candidate === "string" && candidate) return candidate;
    if (Array.isArray(p.cmd)) return (p.cmd as unknown[]).join(" ");
  }
  if (typeof parsed === "string") return parsed;
  return "";
}

interface ParsedPayload {
  ok: boolean;
  value: unknown;
  raw: string | null;
}

function parsePayload(raw: string | null): ParsedPayload {
  if (raw == null) return { ok: true, value: null, raw };
  try {
    return { ok: true, value: JSON.parse(raw), raw };
  } catch {
    return { ok: false, value: null, raw };
  }
}

export function AuditLogPage() {
  const { t } = useI18n();

  // Filter state (committed values used for fetching).
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [issueId, setIssueId] = useState("");
  const [taskId, setTaskId] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [query, setQuery] = useState("");

  // Data state.
  const [items, setItems] = useState<AuditLog[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Token guards against out-of-order responses from rapid filter changes.
  const requestToken = useRef(0);

  const filters = useMemo(
    () => ({
      category: selectedCategories.size > 0 ? Array.from(selectedCategories) : null,
      issueId: issueId.trim() || null,
      taskId: taskId.trim() || null,
      since: normalizeSince(since),
      until: normalizeUntil(until),
      q: query.trim() || null,
    }),
    [selectedCategories, issueId, taskId, since, until, query],
  );

  const load = useCallback(async () => {
    const token = ++requestToken.current;
    setLoading(true);
    setError(null);
    try {
      const page = await getAuditLog({ ...filters, limit: PAGE_LIMIT });
      if (token !== requestToken.current) return;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setExpanded(new Set());
    } catch (e) {
      if (token !== requestToken.current) return;
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
      setNextCursor(null);
    } finally {
      if (token === requestToken.current) setLoading(false);
    }
  }, [filters]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    const token = requestToken.current;
    setLoadingMore(true);
    try {
      const page = await getAuditLog({ ...filters, cursor: nextCursor, limit: PAGE_LIMIT });
      if (token !== requestToken.current) return;
      setItems((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (e) {
      if (token !== requestToken.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (token === requestToken.current) setLoadingMore(false);
    }
  }, [filters, nextCursor, loadingMore]);

  // Debounced reload on filter change.
  useEffect(() => {
    const id = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(id);
  }, [load]);

  const toggleCategory = useCallback((category: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }, []);

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setSelectedCategories(new Set());
    setIssueId("");
    setTaskId("");
    setSince("");
    setUntil("");
    setQuery("");
  }, []);

  const hasFilters =
    selectedCategories.size > 0 ||
    !!issueId.trim() ||
    !!taskId.trim() ||
    !!since.trim() ||
    !!until.trim() ||
    !!query.trim();

  return (
    <PageFrame
      eyebrow={t("auditLog.eyebrow")}
      title={t("auditLog.title")}
      description={t("auditLog.description")}
      actions={
        <Button size="sm" variant="outline" onClick={() => void load()} className="gap-2">
          <RefreshCw size={14} />
          {t("auditLog.refresh")}
        </Button>
      }
      contentClassName="space-y-4"
    >
      {/* Filter bar */}
      <div className="space-y-3 rounded-2xl border border-border-subtle bg-surface-raised/60 p-4">
        {/* Category chips */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            {t("auditLog.filter.category")}
          </span>
          {CATEGORIES.map((category) => {
            const active = selectedCategories.has(category);
            return (
              <button
                key={category}
                type="button"
                onClick={() => toggleCategory(category)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
                  active
                    ? categoryClass(category)
                    : "border-border-subtle bg-transparent text-text-muted hover:border-brand/40 hover:text-text-secondary",
                )}
              >
                {t(`auditLog.category.${category}`)}
              </button>
            );
          })}
        </div>

        {/* Text + range filters */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.search")}
            </span>
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("auditLog.filter.searchPlaceholder")}
                className="pl-8"
              />
            </div>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.issueId")}
            </span>
            <Input value={issueId} onChange={(e) => setIssueId(e.target.value)} placeholder="issue id" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.taskId")}
            </span>
            <Input value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="task id" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.since")}
            </span>
            <Input
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.until")}
            </span>
            <Input
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
          <div className="flex items-end">
            {hasFilters && (
              <Button size="sm" variant="ghost" onClick={clearFilters} className="gap-1.5">
                <X size={13} />
                {t("auditLog.filter.clear")}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-status-failed/30 bg-status-failed/10 px-4 py-3 text-sm font-medium text-status-failed">
          <AlertCircle size={15} />
          {t("auditLog.error", { message: error })}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="flex items-center gap-2 rounded-2xl border border-border-subtle bg-surface-input/40 px-6 py-12 text-sm text-text-muted">
          <Loader2 size={15} className="animate-spin" /> {t("auditLog.loading")}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          {t("auditLog.empty")}
        </div>
      ) : (
        <>
          <ul className="space-y-1.5">
            {items.map((entry) => (
              <AuditRow
                key={entry.id}
                entry={entry}
                expanded={expanded.has(entry.id)}
                onToggle={() => toggleExpanded(entry.id)}
              />
            ))}
          </ul>

          {nextCursor && (
            <div className="flex justify-center pt-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                className="gap-2"
              >
                {loadingMore && <Loader2 size={14} className="animate-spin" />}
                {t("auditLog.loadMore")}
              </Button>
            </div>
          )}
        </>
      )}
    </PageFrame>
  );
}

interface AuditRowProps {
  entry: AuditLog;
  expanded: boolean;
  onToggle: () => void;
}

function AuditRow({ entry, expanded, onToggle }: AuditRowProps) {
  const { t } = useI18n();
  const parsed = useMemo(() => parsePayload(entry.payload_json), [entry.payload_json]);
  const summary = useMemo(() => summarize(parsed.value, entry), [parsed.value, entry]);
  const pretty = useMemo(() => {
    if (!expanded) return null;
    if (parsed.ok && parsed.value != null) {
      try {
        return JSON.stringify(parsed.value, null, 2);
      } catch {
        return parsed.raw ?? "";
      }
    }
    return parsed.raw ?? "";
  }, [expanded, parsed]);

  const isError = entry.status === "error" || !!entry.error;

  return (
    <li className="rounded-xl border border-border-subtle bg-surface-raised/70">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface-input/40"
      >
        <span className="shrink-0 text-text-muted">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="w-40 shrink-0 font-mono text-xs text-text-muted">
          {formatTimestamp(entry.created_at)}
        </span>
        <Badge
          variant="outline"
          className={cn("shrink-0 font-mono text-[10px] uppercase", categoryClass(entry.category))}
        >
          {t(`auditLog.category.${entry.category}` as never) || entry.category}
        </Badge>
        {entry.actor && (
          <span className="shrink-0 truncate font-mono text-xs text-text-secondary max-w-[140px]">
            {entry.actor}
          </span>
        )}
        {entry.status && (
          <span
            className={cn(
              "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
              isError
                ? "border-status-failed/30 text-status-failed"
                : "border-status-done/30 text-status-done",
            )}
          >
            {entry.status}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-xs text-text-secondary">{summary}</span>
        {entry.duration_ms != null && (
          <span className="shrink-0 font-mono text-xs text-text-muted">{entry.duration_ms}ms</span>
        )}
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-border-subtle px-3 py-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-text-muted">
            <span>id: {entry.id}</span>
            {entry.issue_id && <span>issue: {entry.issue_id}</span>}
            {entry.task_id && <span>task: {entry.task_id}</span>}
            {entry.conductor_task_id && <span>conductor: {entry.conductor_task_id}</span>}
            {entry.execution_process_id && <span>exec_proc: {entry.execution_process_id}</span>}
            {entry.correlation_id && <span>corr: {entry.correlation_id}</span>}
          </div>
          {entry.error && (
            <div className="rounded-lg border border-status-failed/30 bg-status-failed/10 px-3 py-2 text-xs text-status-failed">
              {entry.error}
            </div>
          )}
          {entry.payload_json == null ? (
            <div className="text-xs text-text-muted">{t("auditLog.noPayload")}</div>
          ) : (
            <>
              {!parsed.ok && (
                <div className="text-[11px] text-status-awaiting">{t("auditLog.parseFailed")}</div>
              )}
              <pre className="max-h-[480px] overflow-auto rounded-lg border border-border-subtle bg-surface-input/40 p-3 font-mono text-[11px] leading-relaxed text-text-secondary whitespace-pre-wrap break-words">
                {pretty}
              </pre>
            </>
          )}
        </div>
      )}
    </li>
  );
}
