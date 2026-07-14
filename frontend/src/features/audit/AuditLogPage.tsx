"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, RefreshCw, Search, X } from "lucide-react";

import {
  getAgentTimeline,
  getAuditLog,
  type AuditLog,
  type AuditLogCategory,
  type AgentTimelineOperation,
} from "@/lib/api/audit";
import { listProjects } from "@/lib/api/projects";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { cn, isRecord, safeJsonParse } from "@/lib/utils";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { useI18n } from "@/providers/I18nProvider";
import { normalizeSince, normalizeUntil } from "./timeBoundary";
import { AuditRoleChainView } from "./AuditRoleChainView";

type ViewMode = "flat" | "timeline";

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

type AuditTranslate = (key: string, params?: Record<string, string | number>) => string;
type ProjectNameMap = ReadonlyMap<string, string>;

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
  if (entry.call_summary) return entry.call_summary;
  if (entry.call_name && entry.call_name !== entry.actor) return entry.call_name;
  if (entry.error) return entry.error;
  if (isRecord(parsed)) {
    const p = parsed;
    if (Array.isArray(p["argv"])) return p["argv"].map((part) => String(part)).join(" ");
    const candidate =
      p["name"] ??
      p["tool"] ??
      p["command"] ??
      p["model"] ??
      p["cmd"] ??
      p["message"] ??
      p["type"] ??
      p["summary"];
    if (typeof candidate === "string" && candidate) return candidate;
    if (Array.isArray(p["cmd"])) return p["cmd"].map((part) => String(part)).join(" ");
  }
  if (typeof parsed === "string") return parsed;
  return "";
}

function auditPayloadRecord(parsed: unknown): Record<string, unknown> | null {
  return isRecord(parsed) ? parsed : null;
}

function auditString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function auditCommandFromValue(value: unknown): string | null {
  if (Array.isArray(value)) {
    const parts = value.map((part) => String(part)).filter(Boolean);
    return parts.length > 0 ? parts.join(" ") : null;
  }
  return auditString(value);
}

function auditNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function auditShortId(value: string): string {
  return value.length > 12 ? value.slice(0, 8) : value;
}

function auditPreviewString(preview: string | null, key: string): string | null {
  if (!preview) return null;
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = preview.match(new RegExp(`['"]?${escaped}['"]?\\s*:\\s*['"]([^'"]+)['"]`));
  return match?.[1] ?? null;
}

function auditPreviewNumber(preview: string | null, key: string): number | null {
  if (!preview) return null;
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = preview.match(new RegExp(`['"]?${escaped}['"]?\\s*:\\s*(\\d+)`));
  return match?.[1] ? Number(match[1]) : null;
}

function auditPayloadPreview(payload: Record<string, unknown> | null): string | null {
  return auditString(payload?.["payload_preview"]);
}

function auditPayloadOrPreviewNumber(
  payload: Record<string, unknown> | null,
  key: string,
): number | null {
  return auditNumber(payload?.[key]) ?? auditPreviewNumber(auditPayloadPreview(payload), key);
}

function auditPayloadOrPreviewString(
  payload: Record<string, unknown> | null,
  key: string,
): string | null {
  return auditString(payload?.[key]) ?? auditPreviewString(auditPayloadPreview(payload), key);
}

function auditInputRecord(entry: AuditLog): Record<string, unknown> | null {
  return isRecord(entry.call_input) ? entry.call_input : null;
}

function auditPrimaryText(parsed: unknown, entry: AuditLog): string {
  const payload = auditPayloadRecord(parsed);
  const input = auditInputRecord(entry);
  const command =
    auditCommandFromValue(input?.["argv"]) ??
    auditCommandFromValue(input?.["command"]) ??
    auditCommandFromValue(payload?.["argv"]) ??
    auditCommandFromValue(payload?.["command"]) ??
    auditCommandFromValue(payload?.["cmd"]);
  if (command) return command;
  const summary = summarize(parsed, entry);
  if (summary) return summary;
  return entry.actor ?? entry.call_name ?? entry.category;
}

function auditOutputSnippet(value: unknown): string | null {
  const text = auditString(value);
  if (!text) return null;
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return null;
  return compact.length > 96 ? `${compact.slice(0, 96)}...` : compact;
}

function auditSecondaryText(
  parsed: unknown,
  entry: AuditLog,
  primary: string,
  t: AuditTranslate,
): string {
  const payload = auditPayloadRecord(parsed);
  const input = auditInputRecord(entry);
  const parts: string[] = [];
  const cwd = auditString(input?.["cwd"]) ?? auditString(payload?.["cwd"]);
  if (cwd) parts.push(cwd);
  const exitCode = auditNumber(input?.["exit_code"]) ?? auditNumber(payload?.["exit_code"]);
  if (exitCode != null) parts.push(t("auditLog.detail.exitCode", { code: exitCode }));
  const stderr = auditOutputSnippet(input?.["stderr"] ?? payload?.["stderr"]);
  const stdout = auditOutputSnippet(input?.["stdout"] ?? payload?.["stdout"]);
  if (stderr) parts.push(t("auditLog.detail.stderr", { text: stderr }));
  else if (stdout) parts.push(t("auditLog.detail.stdout", { text: stdout }));
  if (entry.role_label && entry.role_label !== "System") parts.push(entry.role_label);
  if (entry.actor && entry.actor !== primary && entry.actor !== entry.call_name) {
    parts.push(entry.actor);
  }
  const preview = auditString(payload?.["payload_preview"]);
  if (preview) parts.push(preview);
  if (entry.issue_id) parts.push(`issue ${entry.issue_id}`);
  if (entry.task_id) parts.push(`task ${entry.task_id}`);
  return parts.join(" · ");
}

function auditEventType(payload: Record<string, unknown> | null, entry: AuditLog): string | null {
  return auditString(payload?.["type"]) ?? (entry.category === "event" ? entry.actor : null);
}

function auditCountsTotal(payload: Record<string, unknown> | null): number | null {
  const counts = payload?.["counts"];
  if (isRecord(counts)) {
    const total = Object.values(counts).reduce<number>(
      (sum, value) => sum + (auditNumber(value) ?? 0),
      0,
    );
    return total > 0 ? total : 0;
  }
  const preview = auditPayloadPreview(payload);
  const countsMatch = preview?.match(/['"]?counts['"]?\s*:\s*\{([^}]*)\}/);
  if (!countsMatch?.[1]) return null;
  const values = [...countsMatch[1].matchAll(/:\s*(\d+)/g)].map((match) => Number(match[1]));
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0);
}

function auditProjectPrSweepText(
  payload: Record<string, unknown> | null,
  entry: AuditLog,
  t: AuditTranslate,
  projectNames: ProjectNameMap,
): { primary: string; secondary: string } {
  const issuesSeen = auditPayloadOrPreviewNumber(payload, "issues_seen");
  const issuesWithPr = auditPayloadOrPreviewNumber(payload, "issues_with_pr");
  const skippedNoPr = auditPayloadOrPreviewNumber(payload, "skipped_no_pr");
  const skippedMerged = auditPayloadOrPreviewNumber(payload, "skipped_merged");
  const checkedPrs = auditPayloadOrPreviewNumber(payload, "checked_prs");
  const preview = auditPayloadPreview(payload);
  const counts = payload?.["counts"];
  const countsEmpty =
    (isRecord(counts) && Object.keys(counts).length === 0) ||
    Boolean(preview?.match(/['"]?counts['"]?\s*:\s*\{\s*\}/));
  const checkedCount = checkedPrs ?? auditCountsTotal(payload) ?? 0;
  const primary =
    checkedCount === 0 || countsEmpty
      ? t("auditLog.event.prSweep.empty")
      : t("auditLog.event.prSweep.checked", { count: checkedCount });

  const parts: string[] = [];
  if (issuesSeen != null) parts.push(t("auditLog.event.prSweep.issuesSeen", { count: issuesSeen }));
  if (issuesWithPr != null) {
    parts.push(t("auditLog.event.prSweep.issuesWithPr", { count: issuesWithPr }));
  }
  if (skippedNoPr != null)
    parts.push(t("auditLog.event.prSweep.skippedNoPr", { count: skippedNoPr }));
  if (skippedMerged != null) {
    parts.push(t("auditLog.event.prSweep.skippedMerged", { count: skippedMerged }));
  }
  if (checkedPrs != null) parts.push(t("auditLog.event.prSweep.checkedPrs", { count: checkedPrs }));
  const projectId = auditPayloadOrPreviewString(payload, "project_id") ?? entry.correlation_id;
  if (projectId) {
    const projectLabel = projectNames.get(projectId) ?? auditShortId(projectId);
    parts.push(t("auditLog.detail.project", { id: projectLabel }));
  }
  return { primary, secondary: parts.join(" · ") };
}

function auditTaskStatusRoleLabel(role: string | null, entry: AuditLog, t: AuditTranslate): string {
  if (role === "operations_engineer") return t("auditLog.event.taskStatus.role.operationsEngineer");
  if (entry.role_label) return entry.role_label;
  if (role) return role;
  return t("auditLog.event.taskStatus.role.agent");
}

function auditTaskStatusKindLabel(kind: string | null, t: AuditTranslate): string {
  if (kind === "project_script_suggestion") {
    return t("auditLog.event.taskStatus.kind.projectScriptSuggestion");
  }
  if (kind) return kind;
  return t("auditLog.event.taskStatus.kind.task");
}

function auditTaskStatusText(
  payload: Record<string, unknown> | null,
  entry: AuditLog,
  t: AuditTranslate,
  projectNames: ProjectNameMap,
): { primary: string; secondary: string } {
  const role = auditPayloadOrPreviewString(payload, "role") ?? entry.role ?? entry.actor;
  const status = auditPayloadOrPreviewString(payload, "status") ?? entry.status;
  const taskKind = auditPayloadOrPreviewString(payload, "task_kind");
  const taskId = auditPayloadOrPreviewString(payload, "task_id") ?? entry.task_id;
  const executionProcessId =
    auditPayloadOrPreviewString(payload, "execution_process_id") ?? entry.execution_process_id;
  const projectId = auditPayloadOrPreviewString(payload, "project_id") ?? entry.correlation_id;
  const issueId = auditPayloadOrPreviewString(payload, "issue_id") ?? entry.issue_id;
  const roleLabel = auditTaskStatusRoleLabel(role, entry, t);
  const taskLabel = auditTaskStatusKindLabel(taskKind, t);
  const normalizedStatus = (status ?? "").toLowerCase();
  const primary =
    normalizedStatus === "running" || normalizedStatus === "responding"
      ? t("auditLog.event.taskStatus.running", { role: roleLabel, task: taskLabel })
      : normalizedStatus === "done" || normalizedStatus === "completed"
        ? t("auditLog.event.taskStatus.done", { role: roleLabel, task: taskLabel })
        : normalizedStatus === "failed" || normalizedStatus === "error"
          ? t("auditLog.event.taskStatus.failed", { role: roleLabel, task: taskLabel })
          : t("auditLog.event.taskStatus.changed", {
              role: roleLabel,
              task: taskLabel,
              status: status ?? "unknown",
            });

  const parts: string[] = [];
  if (projectId) {
    const projectLabel = projectNames.get(projectId) ?? auditShortId(projectId);
    parts.push(t("auditLog.detail.project", { id: projectLabel }));
  }
  if (issueId && issueId !== "None") parts.push(`issue ${auditShortId(issueId)}`);
  if (taskId) parts.push(t("auditLog.detail.task", { id: auditShortId(taskId) }));
  if (executionProcessId) {
    parts.push(t("auditLog.detail.execution", { id: auditShortId(executionProcessId) }));
  }
  return { primary, secondary: parts.join(" · ") };
}

function auditDisplayText(
  parsed: unknown,
  entry: AuditLog,
  t: AuditTranslate,
  projectNames: ProjectNameMap,
): { primary: string; secondary: string } {
  const payload = auditPayloadRecord(parsed);
  const eventType = auditEventType(payload, entry);
  if (eventType === "project_pr_followup_sweep") {
    return auditProjectPrSweepText(payload, entry, t, projectNames);
  }
  if (eventType === "task_status") {
    return auditTaskStatusText(payload, entry, t, projectNames);
  }
  const primary = auditPrimaryText(parsed, entry);
  return { primary, secondary: auditSecondaryText(parsed, entry, primary, t) };
}

interface ParsedPayload {
  ok: boolean;
  value: unknown;
  raw: string | null;
}

function parsePayload(raw: string | null): ParsedPayload {
  if (raw == null) return { ok: true, value: null, raw };
  const parsed = safeJsonParse(raw);
  return parsed === null ? { ok: false, value: null, raw } : { ok: true, value: parsed, raw };
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
  const [timelineOperations, setTimelineOperations] = useState<AgentTimelineOperation[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [timelineNextCursor, setTimelineNextCursor] = useState<string | null>(null);
  const [projectNames, setProjectNames] = useState<Map<string, string>>(() => new Map());
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>("flat");

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
      if (viewMode === "timeline") {
        const page = await getAgentTimeline({ ...filters, limit: PAGE_LIMIT });
        if (token !== requestToken.current) return;
        setTimelineOperations(page.items);
        setTimelineNextCursor(page.next_cursor);
      } else {
        const page = await getAuditLog({ ...filters, limit: PAGE_LIMIT });
        if (token !== requestToken.current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      }
      setExpanded(new Set());
    } catch (e) {
      if (token !== requestToken.current) return;
      setError(e instanceof Error ? e.message : String(e));
      if (viewMode === "timeline") {
        setTimelineOperations([]);
        setTimelineNextCursor(null);
      } else {
        setItems([]);
        setNextCursor(null);
      }
    } finally {
      if (token === requestToken.current) setLoading(false);
    }
  }, [filters, viewMode]);

  const loadProjectNames = useCallback(async () => {
    try {
      const projects = await listProjects();
      setProjectNames(
        new Map(projects.map((project) => [project.id, project.name || auditShortId(project.id)])),
      );
    } catch {
      setProjectNames(new Map());
    }
  }, []);

  const loadMore = useCallback(async () => {
    const cursor = viewMode === "timeline" ? timelineNextCursor : nextCursor;
    if (!cursor || loadingMore) return;
    const token = requestToken.current;
    setLoadingMore(true);
    try {
      if (viewMode === "timeline") {
        const page = await getAgentTimeline({ ...filters, cursor, limit: PAGE_LIMIT });
        if (token !== requestToken.current) return;
        setTimelineOperations((prev) => [...prev, ...page.items]);
        setTimelineNextCursor(page.next_cursor);
      } else {
        const page = await getAuditLog({ ...filters, cursor, limit: PAGE_LIMIT });
        if (token !== requestToken.current) return;
        setItems((prev) => [...prev, ...page.items]);
        setNextCursor(page.next_cursor);
      }
    } catch (e) {
      if (token !== requestToken.current) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (token === requestToken.current) setLoadingMore(false);
    }
  }, [timelineNextCursor, filters, loadingMore, nextCursor, viewMode]);

  // Debounced reload on filter change.
  useEffect(() => {
    const id = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(id);
  }, [load]);

  useEffect(() => {
    void loadProjectNames();
  }, [loadProjectNames]);

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
  const activeItemsLength = viewMode === "timeline" ? timelineOperations.length : items.length;
  const activeNextCursor = viewMode === "timeline" ? timelineNextCursor : nextCursor;

  return (
    <PageFrame
      eyebrow={t("auditLog.eyebrow")}
      title={t("auditLog.title")}
      description={t("auditLog.description")}
      actions={
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border border-border-subtle overflow-hidden">
            <button
              type="button"
              onClick={() => setViewMode("flat")}
              className={cn(
                "px-2.5 py-1 text-xs transition-colors",
                viewMode === "flat"
                  ? "bg-brand/15 text-brand font-semibold"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
            >
              {t("auditLog.view.flat")}
            </button>
            <button
              type="button"
              onClick={() => setViewMode("timeline")}
              className={cn(
                "px-2.5 py-1 text-xs border-l border-border-subtle transition-colors",
                viewMode === "timeline"
                  ? "bg-brand/15 text-brand font-semibold"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
            >
              {t("auditLog.view.chain")}
            </button>
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} className="gap-2">
            <RefreshCw size={14} />
            {t("auditLog.refresh")}
          </Button>
        </div>
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
            <Input
              value={issueId}
              onChange={(e) => setIssueId(e.target.value)}
              placeholder="issue id"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.taskId")}
            </span>
            <Input
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              placeholder="task id"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.since")}
            </span>
            <Input type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              {t("auditLog.filter.until")}
            </span>
            <Input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
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
        <div
          data-density="audit-log-tool-loading"
          className="motion-essential relative flex items-center gap-2 overflow-hidden rounded-2xl border border-border-subtle bg-surface-input/40 px-6 py-12 text-sm text-text-muted"
        >
          <span
            aria-hidden
            className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool/70 to-transparent"
          />
          <AgentThinkingIndicator phase="tool" size={15} />
          {t("auditLog.loading")}
        </div>
      ) : activeItemsLength === 0 ? (
        <div className="rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          {t("auditLog.empty")}
        </div>
      ) : (
        <>
          {viewMode === "timeline" ? (
            <AuditRoleChainView operations={timelineOperations} />
          ) : (
            <ul className="space-y-1.5">
              {items.map((entry) => (
                <AuditRow
                  key={entry.id}
                  entry={entry}
                  expanded={expanded.has(entry.id)}
                  projectNames={projectNames}
                  onToggle={() => toggleExpanded(entry.id)}
                />
              ))}
            </ul>
          )}

          {activeNextCursor && (
            <div className="flex justify-center pt-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void loadMore()}
                disabled={loadingMore}
                data-density={loadingMore ? "audit-log-load-more-tool" : "audit-log-load-more"}
                className={cn("gap-2", loadingMore && "motion-essential")}
              >
                {loadingMore && <AgentThinkingIndicator phase="tool" size={14} />}
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
  projectNames: ProjectNameMap;
  onToggle: () => void;
}

function AuditRow({ entry, expanded, projectNames, onToggle }: AuditRowProps) {
  const { t } = useI18n();
  const parsed = useMemo(() => parsePayload(entry.payload_json), [entry.payload_json]);
  const display = useMemo(
    () => auditDisplayText(parsed.value, entry, t, projectNames),
    [parsed.value, entry, projectNames, t],
  );
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
        className="grid w-full grid-cols-[auto_9.5rem_auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface-input/40"
      >
        <span className="shrink-0 text-text-muted">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="shrink-0 font-mono text-xs text-text-muted">
          {formatTimestamp(entry.created_at)}
        </span>
        <Badge
          variant="outline"
          className={cn("shrink-0 font-mono text-[10px] uppercase", categoryClass(entry.category))}
        >
          {t(`auditLog.category.${entry.category}` as never) || entry.category}
        </Badge>
        <span className="min-w-0">
          <span
            className="block truncate font-mono text-xs text-text-primary"
            title={display.primary}
          >
            {display.primary}
          </span>
          {display.secondary && (
            <span
              className="mt-0.5 block truncate text-[11px] text-text-muted"
              title={display.secondary}
            >
              {display.secondary}
            </span>
          )}
        </span>
        <span className="flex shrink-0 items-center justify-end gap-2">
          {entry.status && (
            <span
              className={cn(
                "rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                isError
                  ? "border-status-failed/30 text-status-failed"
                  : "border-status-done/30 text-status-done",
              )}
            >
              {entry.status}
            </span>
          )}
          {entry.duration_ms != null && (
            <span className="font-mono text-xs text-text-muted">{entry.duration_ms}ms</span>
          )}
        </span>
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
