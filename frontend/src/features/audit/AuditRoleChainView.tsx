"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, GitBranch, ListTree, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/providers/I18nProvider";
import { normalizeLogs } from "@/lib/codexLogNormalizer";
import {
  getBestAuditTrace,
  type AuditLog,
  type AuditLogChainOperation,
  type AuditTraceCollection,
  type AuditTraceDetail,
  type AuditTraceItem,
} from "@/lib/api/audit";
import { cn, isRecord, safeJsonRecord } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MessageMarkdown } from "@/features/runs/MessageMarkdown";
import { ToolBlock } from "@/features/runs/toolBlocks/ToolBlocks";
import type { LogEvent, NormalizedEntry } from "@/lib/types";

interface Props {
  operations: AuditLogChainOperation[];
}

function hasValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (isRecord(value)) return Object.keys(value).length > 0;
  return true;
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function DetailBlock({ label, value }: { label: string; value: unknown }) {
  if (!hasValue(value)) return null;
  return (
    <div className="space-y-1">
      <div className="text-text-faint text-[10px] font-bold tracking-wider uppercase">{label}</div>
      <pre className="border-border-subtle bg-surface-input/40 text-text-secondary max-h-64 overflow-auto rounded-lg border p-2 font-mono text-[10px] leading-relaxed break-words whitespace-pre-wrap">
        {formatValue(value)}
      </pre>
    </div>
  );
}

function TraceValueBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="space-y-1">
      <div className="text-text-faint text-[10px] font-bold tracking-wider uppercase">{label}</div>
      <pre className="border-border-subtle bg-surface-raised/60 text-text-secondary max-h-96 overflow-auto rounded-lg border p-2 font-mono text-[10px] leading-relaxed break-words whitespace-pre-wrap">
        {formatValue(value)}
      </pre>
    </div>
  );
}

function traceItemsFromDetail(detail: AuditTraceDetail | AuditTraceCollection): AuditTraceItem[] {
  if ("items" in detail) return detail.items;
  return detail.available ? [detail] : [];
}

interface TraceRuntimeRows {
  messages: Record<string, unknown>[];
  logs: Record<string, unknown>[];
}

function isString(value: string | null): value is string {
  return value !== null;
}

function parsePayload(value: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function previewString(payload: Record<string, unknown> | null, key: string): string | null {
  const preview = payload?.["payload_preview"];
  if (typeof preview !== "string") return null;
  const match = preview.match(new RegExp(`['"]${key}['"]\\s*:\\s*['"]([^'"]+)['"]`));
  return match?.[1] ?? null;
}

function payloadString(payload: Record<string, unknown> | null, key: string): string | null {
  const value = payload?.[key];
  return typeof value === "string" && value.length > 0 ? value : previewString(payload, key);
}

function shortId(value: string | null): string | null {
  if (!value || value === "None") return null;
  return value.length > 8 ? value.slice(0, 8) : value;
}

function roleLabel(role: string | null, fallback: string | null, t: ReturnType<typeof useI18n>["t"]): string {
  if (
    role === "operations_engineer" ||
    fallback === "operations_engineer" ||
    fallback === "Operations Engineer"
  ) {
    return t("auditLog.event.taskStatus.role.operationsEngineer");
  }
  return fallback || role || t("auditLog.event.taskStatus.role.agent");
}

function taskKindLabel(kind: string | null, t: ReturnType<typeof useI18n>["t"]): string {
  if (kind === "project_script_suggestion") {
    return t("auditLog.event.taskStatus.kind.projectScriptSuggestion");
  }
  return kind || t("auditLog.event.taskStatus.kind.task");
}

function taskStatusParts(
  entry: AuditLog,
  t: ReturnType<typeof useI18n>["t"],
): { role: string; task: string; status: string | null } | null {
  const payload = parsePayload(entry.payload_json);
  const eventType = payloadString(payload, "type") ?? (entry.category === "event" ? entry.actor : null);
  if (eventType !== "task_status") return null;
  const role = payloadString(payload, "role") ?? entry.role ?? entry.actor;
  const status = payloadString(payload, "status") ?? entry.status;
  const kind = payloadString(payload, "task_kind");
  return {
    role: roleLabel(role, entry.role_label ?? null, t),
    task: taskKindLabel(kind, t),
    status,
  };
}

function taskStatusSummary(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  const parts = taskStatusParts(entry, t);
  if (!parts) return null;
  const status = parts.status;
  const normalizedStatus = (status ?? "").toLowerCase();
  if (normalizedStatus === "running") {
    return t("auditLog.event.taskStatus.running", { role: parts.role, task: parts.task });
  }
  if (normalizedStatus === "responding") {
    return t("auditLog.event.taskStatus.responding", { role: parts.role, task: parts.task });
  }
  if (normalizedStatus === "done" || normalizedStatus === "completed") {
    return t("auditLog.event.taskStatus.done", { role: parts.role, task: parts.task });
  }
  if (normalizedStatus === "failed" || normalizedStatus === "error") {
    return t("auditLog.event.taskStatus.failed", { role: parts.role, task: parts.task });
  }
  return t("auditLog.event.taskStatus.changed", {
    role: parts.role,
    task: parts.task,
    status: status ?? "unknown",
  });
}

function taskStatusCompact(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  const parts = taskStatusParts(entry, t);
  if (!parts) return null;
  const normalizedStatus = (parts.status ?? "").toLowerCase();
  if (normalizedStatus === "running") {
    return t("auditLog.event.taskStatus.step.running");
  }
  if (normalizedStatus === "responding") {
    return t("auditLog.event.taskStatus.step.responding");
  }
  if (normalizedStatus === "done" || normalizedStatus === "completed") {
    return t("auditLog.event.taskStatus.step.done");
  }
  if (normalizedStatus === "failed" || normalizedStatus === "error") {
    return t("auditLog.event.taskStatus.step.failed");
  }
  return t("auditLog.event.taskStatus.step.changed", { status: parts.status ?? "unknown" });
}

function taskStatusMeta(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  const payload = parsePayload(entry.payload_json);
  const eventType = payloadString(payload, "type") ?? (entry.category === "event" ? entry.actor : null);
  if (eventType !== "task_status") return null;
  const taskId = shortId(payloadString(payload, "task_id") ?? entry.task_id);
  const executionId = shortId(payloadString(payload, "execution_process_id") ?? entry.execution_process_id);
  const taskTitle = entry.task_title;
  const parts = [
    taskTitle
      ? t("auditLog.detail.task", { id: taskTitle })
      : taskId
        ? t("auditLog.detail.task", { id: taskId })
        : null,
    executionId ? t("auditLog.detail.execution", { id: executionId }) : null,
  ].filter(isString);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function eventType(entry: AuditLog): string | null {
  const payload = parsePayload(entry.payload_json);
  return payloadString(payload, "type") ?? (entry.category === "event" ? entry.actor : null);
}

function readableEventSummary(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  const type = eventType(entry);
  if (type === "project_script_updated") return t("auditLog.event.projectScriptUpdated");
  return null;
}

function cliSpawnSummary(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  if (entry.category !== "cli_spawn") return null;
  const payload = parsePayload(entry.payload_json);
  const executor = payloadString(payload, "executor") ?? entry.actor ?? "CLI";
  if (executor === "claude") return t("auditLog.event.cliSpawn.claude");
  if (executor === "codex") return t("auditLog.event.cliSpawn.codex");
  return t("auditLog.event.cliSpawn.generic", { executor });
}

function cliSpawnMeta(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  if (entry.category !== "cli_spawn") return null;
  const payload = parsePayload(entry.payload_json);
  const model = payloadString(payload, "model");
  const cwd = payloadString(payload, "cwd");
  const pidValue = payload?.["pid"];
  const pid = typeof pidValue === "number" ? String(pidValue) : payloadString(payload, "pid");
  const parts = [
    model ? t("auditLog.detail.model", { id: model }) : null,
    cwd ? t("auditLog.detail.cwd", { path: cwd }) : null,
    pid ? t("auditLog.detail.pid", { id: pid }) : null,
  ].filter(isString);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function projectScriptMeta(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string | null {
  if (eventType(entry) !== "project_script_updated") return null;
  const payload = parsePayload(entry.payload_json);
  const runCommand = payloadString(payload, "run_command");
  const setupScript = payloadString(payload, "setup_script");
  const parts = [
    runCommand ? t("auditLog.detail.runCommand", { command: runCommand }) : null,
    setupScript ? t("auditLog.detail.setupScript", { command: setupScript }) : null,
  ].filter(isString);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function shouldHideRawPayload(entry: AuditLog): boolean {
  const type = eventType(entry);
  return type === "task_status" || type === "project_script_updated" || entry.category === "cli_spawn";
}

function shouldShowStepTrace(entry: AuditLog): boolean {
  const type = eventType(entry);
  return entry.category === "cli_spawn" || type === "project_script_updated";
}

function taskStatusDedupeKey(entry: AuditLog): string | null {
  if (eventType(entry) !== "task_status") return null;
  const payload = parsePayload(entry.payload_json);
  const taskId = payloadString(payload, "task_id") ?? entry.task_id ?? "";
  const executionId =
    payloadString(payload, "execution_process_id") ?? entry.execution_process_id ?? "";
  const status = payloadString(payload, "status") ?? entry.status ?? "";
  return `task_status:${taskId}:${executionId}:${status}`;
}

function dedupeOperationEntries(entries: AuditLog[]): AuditLog[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    const key = taskStatusDedupeKey(entry);
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function AuditRoleChainView({ operations }: Props) {
  const { t } = useI18n();
  const visibleOperations = useMemo(
    () => operations.filter((operation) => operation.role !== "system"),
    [operations],
  );

  if (visibleOperations.length === 0) return null;

  return (
    <section data-density="audit-role-chain" className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-text-primary flex items-center gap-2 text-sm font-semibold">
            <GitBranch size={15} className="text-brand" />
            {t("auditLog.roleChain.title")}
          </div>
          <p className="text-text-muted mt-1 text-xs">{t("auditLog.roleChain.description")}</p>
        </div>
        <Badge variant="outline" className="border-brand/30 bg-brand/10 text-brand shrink-0">
          {t("auditLog.roleChain.groupCount", { count: visibleOperations.length })}
        </Badge>
      </div>

      <div className="space-y-2.5">
        {visibleOperations.map((operation) => (
          <OperationCard key={operation.id} operation={operation} />
        ))}
      </div>
    </section>
  );
}

function entrySummary(entry: AuditLog, t: ReturnType<typeof useI18n>["t"]): string {
  return taskStatusSummary(entry, t) || readableEventSummary(entry, t) || cliSpawnSummary(entry, t) || entry.call_summary || entry.error || entry.call_name || entry.actor || entry.category;
}

function entryMachineName(entry: AuditLog): string | null {
  const type = eventType(entry);
  if (type === "task_status" || type === "project_script_updated" || entry.category === "cli_spawn") {
    return null;
  }
  return entry.call_name ?? null;
}

function operationTitle(operation: AuditLogChainOperation, t: ReturnType<typeof useI18n>["t"]): string {
  if (operation.timeline_kind === "agent_execution" && operation.title) return operation.title;
  if (operation.entry_count > 1 && operation.task_title) return operation.task_title;
  const firstTaskStatus = operation.entries.map((entry) => taskStatusParts(entry, t)).find(Boolean);
  if (firstTaskStatus) return `${firstTaskStatus.role} · ${firstTaskStatus.task}`;
  const firstReadable = operation.entries
    .map((entry) => cliSpawnSummary(entry, t) || readableEventSummary(entry, t))
    .find(isString);
  if (firstReadable) return firstReadable;
  return operation.title;
}

function operationSummary(operation: AuditLogChainOperation, t: ReturnType<typeof useI18n>["t"]): string {
  if (isRecord(operation.result)) {
    const runCommand = operation.result["run_command"];
    if (typeof runCommand === "string" && runCommand.length > 0) {
      return t("auditLog.detail.runCommand", { command: runCommand });
    }
    const setupScript = operation.result["setup_script"];
    if (typeof setupScript === "string" && setupScript.length > 0) {
      return t("auditLog.detail.setupScript", { command: setupScript });
    }
  }
  const taskStatuses = dedupeOperationEntries(operation.entries)
    .map((entry) => taskStatusParts(entry, t)?.status?.toLowerCase() ?? null)
    .filter(isString);
  if (taskStatuses.some((status) => status === "failed" || status === "error")) {
    return t("auditLog.roleChain.summary.failed");
  }
  if (taskStatuses.some((status) => status === "done" || status === "completed")) {
    return t("auditLog.roleChain.summary.success");
  }
  if (taskStatuses.some((status) => status === "running" || status === "responding")) {
    return t("auditLog.roleChain.summary.running");
  }
  if (operation.summary === operation.title || operation.summary === operation.role_label) {
    return operation.task_title || operation.operation_task_id || operation.summary;
  }
  return operation.summary;
}

function operationResultMeta(
  operation: AuditLogChainOperation,
  t: ReturnType<typeof useI18n>["t"],
): string | null {
  if (!isRecord(operation.result)) return null;
  const runCommand = operation.result["run_command"];
  const setupScript = operation.result["setup_script"];
  const parts = [
    typeof runCommand === "string" && runCommand.length > 0
      ? t("auditLog.detail.runCommand", { command: runCommand })
      : null,
    typeof setupScript === "string" && setupScript.length > 0
      ? t("auditLog.detail.setupScript", { command: setupScript })
      : null,
  ].filter(isString);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function operationStatusLabel(
  status: string | null,
  t: ReturnType<typeof useI18n>["t"],
): string | null {
  const normalized = (status ?? "").toLowerCase();
  if (!normalized) return null;
  if (
    normalized === "failed" ||
    normalized === "error" ||
    normalized === "cancelled" ||
    normalized === "canceled" ||
    normalized === "killed" ||
    normalized === "timeout" ||
    normalized === "protocol_error" ||
    normalized === "timed_out"
  ) {
    return t("auditLog.roleChain.summary.failed");
  }
  if (
    normalized === "done" ||
    normalized === "completed" ||
    normalized === "success" ||
    normalized === "ok"
  ) {
    return t("auditLog.roleChain.summary.success");
  }
  if (
    normalized === "running" ||
    normalized === "responding" ||
    normalized === "starting" ||
    normalized === "queued" ||
    normalized === "pending"
  ) {
    return t("auditLog.roleChain.summary.running");
  }
  return status;
}

function operationStatusClass(status: string | null, hasError: boolean): string {
  if (hasError) return "border-status-failed/30 text-status-failed";
  const normalized = (status ?? "").toLowerCase();
  if (
    normalized === "running" ||
    normalized === "responding" ||
    normalized === "starting" ||
    normalized === "queued" ||
    normalized === "pending"
  ) {
    return "border-status-awaiting/30 text-status-awaiting";
  }
  if (
    normalized === "done" ||
    normalized === "completed" ||
    normalized === "success" ||
    normalized === "ok"
  ) {
    return "border-status-done/30 text-status-done";
  }
  return "border-border-subtle text-text-muted";
}

function OperationCard({ operation }: { operation: AuditLogChainOperation }) {
  const { t } = useI18n();
  const entries = dedupeOperationEntries(operation.entries);
  const normalizedOperationStatus = (operation.status ?? "").toLowerCase();
  const isError =
    normalizedOperationStatus === "error" ||
    normalizedOperationStatus === "failed" ||
    normalizedOperationStatus === "cancelled" ||
    normalizedOperationStatus === "canceled" ||
    normalizedOperationStatus === "killed" ||
    normalizedOperationStatus === "timeout" ||
    normalizedOperationStatus === "protocol_error" ||
    normalizedOperationStatus === "timed_out" ||
    entries.some((entry) => entry.error);
  const title = operationTitle(operation, t);
  const summary = operationSummary(operation, t);
  const resultMeta = operationResultMeta(operation, t);
  const statusLabel = operationStatusLabel(operation.status, t);
  const badgeLabel = roleLabel(operation.role, operation.role_label, t);
  const meta = [
    operation.task_title
      ? t("auditLog.detail.task", { id: operation.task_title })
      : operation.operation_task_id
        ? t("auditLog.detail.task", { id: shortId(operation.operation_task_id) ?? operation.operation_task_id })
        : null,
    operation.execution_process_id
      ? t("auditLog.detail.execution", {
          id: shortId(operation.execution_process_id) ?? operation.execution_process_id,
        })
      : null,
    operation.conductor_task_id ? `conductor ${operation.conductor_task_id}` : null,
    operation.turn_index != null
      ? t("auditLog.roleChain.turn", { turn: operation.turn_index + 1 })
      : t("auditLog.roleChain.unscoped"),
    operation.duration_ms != null ? `${operation.duration_ms}ms` : null,
  ].filter(isString);

  return (
    <details className="border-border-subtle bg-surface-raised/70 rounded-xl border">
      <summary className="block cursor-pointer list-none px-3 py-3 [&::-webkit-details-marker]:hidden">
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3">
          <Badge
            variant="outline"
            className="border-brand/30 bg-brand/10 text-brand mt-0.5 shrink-0 text-[10px]"
          >
            {badgeLabel}
          </Badge>
          <div className="min-w-0">
            <div className="text-text-primary truncate text-sm font-semibold" title={title}>
              {title}
            </div>
            <div className="text-text-secondary mt-1 truncate text-xs" title={summary}>
              {summary}
            </div>
            <div className="text-text-faint mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px]">
              <span>{formatTimestamp(operation.started_at)}</span>
              {meta.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {statusLabel && (
              <span
                className={cn(
                  "rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                  operationStatusClass(operation.status, isError),
                )}
              >
                {statusLabel}
              </span>
            )}
            <span className="border-border-subtle text-text-muted rounded-full border px-2 py-0.5 text-[10px]">
              {t("auditLog.roleChain.entryCount", { count: operation.entry_count })}
            </span>
            <span className="text-text-faint hover:text-text-muted whitespace-nowrap text-right text-[10px] select-none">
              {t("auditLog.roleChain.details")}
            </span>
          </div>
        </div>
      </summary>

      <div className="border-border-subtle space-y-3 border-t px-3 py-3">
        <div className="text-text-muted flex items-center gap-2 text-[11px] font-semibold">
          <ListTree size={13} className="text-text-faint" />
          <span>{t("auditLog.roleChain.description")}</span>
        </div>
        {resultMeta && (
          <div className="border-status-done/20 bg-status-done/10 text-text-secondary rounded-lg border px-3 py-2 text-xs">
            {resultMeta}
          </div>
        )}
        <ol className="space-y-1.5">
          {entries.map((entry) => {
            const hasInput = hasValue(entry.call_input);
            const hasOutput = hasValue(entry.call_output);
            const machineName = entryMachineName(entry);
            const fullSummary = entrySummary(entry, t);
            const compactSummary =
              fullSummary === summary ? taskStatusCompact(entry, t) ?? fullSummary : fullSummary;
            const readableMeta =
              taskStatusMeta(entry, t) ?? cliSpawnMeta(entry, t) ?? projectScriptMeta(entry, t);
            const hideRawPayload = shouldHideRawPayload(entry);
            const entryStatusLabel = operationStatusLabel(entry.status, t);
            const normalizedEntryStatus = (entry.status ?? "").toLowerCase();
            const entryIsError =
              normalizedEntryStatus === "error" ||
              normalizedEntryStatus === "failed" ||
              normalizedEntryStatus === "cancelled" ||
              normalizedEntryStatus === "canceled" ||
              normalizedEntryStatus === "killed" ||
              normalizedEntryStatus === "timeout" ||
              normalizedEntryStatus === "protocol_error" ||
              normalizedEntryStatus === "timed_out" ||
              Boolean(entry.error);
            return (
              <li
                key={entry.id}
                data-density="audit-role-chain-entry"
                className="border-border-subtle bg-surface-input/30 rounded-lg border px-3 py-2"
              >
                <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3">
                  <Badge
                    variant="outline"
                    className="border-border-subtle bg-surface-raised text-text-muted mt-0.5 shrink-0 text-[10px] uppercase"
                  >
                    {t(`auditLog.category.${entry.category}` as never) || entry.category}
                  </Badge>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      {machineName && (
                        <span className="text-text-faint min-w-0 truncate font-mono text-[11px]">
                          {machineName}
                        </span>
                      )}
                      {entryStatusLabel && (
                        <span
                          className={cn(
                            "shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-bold uppercase",
                            operationStatusClass(entry.status, entryIsError),
                          )}
                        >
                          {entryStatusLabel}
                        </span>
                      )}
                    </div>
                    <div className="text-text-secondary mt-1 text-xs" title={fullSummary}>
                      {compactSummary}
                    </div>
                    {readableMeta && (
                      <div className="text-text-muted mt-1 truncate text-[11px]" title={readableMeta}>
                        {readableMeta}
                      </div>
                    )}
                    <div className="text-text-faint mt-1 font-mono text-[10px]">
                      {formatTimestamp(entry.created_at)}
                    </div>
                  </div>
                  <span className="text-text-faint justify-self-end font-mono text-[10px]">
                    #{entry.sub_index ?? "—"}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-2">
                  <DetailBlock label={t("auditLog.roleChain.input")} value={entry.call_input} />
                  <DetailBlock label={t("auditLog.roleChain.output")} value={entry.call_output} />
                  {!hideRawPayload && !hasInput && !hasOutput && (
                    <DetailBlock label={t("auditLog.roleChain.raw")} value={entry.payload_json} />
                  )}
                </div>
                {shouldShowStepTrace(entry) && <TraceDetailPanel entry={entry} />}
              </li>
            );
          })}
        </ol>
      </div>
    </details>
  );
}

function traceRecordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord);
}

function traceRuntimeRows(response: unknown): TraceRuntimeRows | null {
  if (!isRecord(response)) return null;
  const messages = traceRecordArray(response["messages"]);
  const logs = traceRecordArray(response["logs"]);
  if (messages.length === 0 && logs.length === 0) return null;
  return { messages, logs };
}

function traceText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return value.length > 0 ? value : null;
}

function traceLogEvents(logs: Record<string, unknown>[]): LogEvent[] {
  return logs.map((log, index) => ({
    id: traceText(log["id"]) ?? `trace-log-${index}`,
    session_id: traceText(log["session_id"]) ?? "",
    stream: traceText(log["stream"]) ?? "stdout",
    content: traceText(log["content"]) ?? formatValue(log),
    task_id: traceText(log["task_id"]),
    execution_process_id: traceText(log["execution_process_id"]),
    created_at: traceText(log["created_at"]),
  }));
}

function TraceThinkingBlock({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const preview = content.length > 80 ? `${content.slice(0, 80)}...` : content;
  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {open ? (
          <ChevronDown size={14} className="shrink-0 text-amber-500" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-amber-500" />
        )}
        <Sparkles
          size={12}
          className="motion-essential animate-neural-pulse shrink-0 text-amber-500"
        />
        <span className="text-[10px] font-black tracking-[0.16em] text-amber-500 uppercase">
          {t("agentLive.thinking")}
        </span>
        {!open && <span className="text-text-muted truncate text-[11px] italic">{preview}</span>}
      </button>
      {open && (
        <div className="px-3 pb-3 pl-9">
          <div className="text-text-secondary font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap">
            {content}
          </div>
        </div>
      )}
    </div>
  );
}

function TraceRuntimeEntryBlock({ entry }: { entry: NormalizedEntry }) {
  if (entry.type === "tool") return <ToolBlock entry={entry} />;
  if (entry.type === "thinking") return <TraceThinkingBlock content={entry.content || ""} />;
  return (
    <div
      className={cn(
        "flex gap-3 rounded-xl border px-3 py-2",
        entry.type === "error"
          ? "border-error/20 bg-error/10"
          : entry.type === "assistant"
            ? "border-brand/20 bg-brand/5"
            : entry.type === "help"
              ? "border-warning/20 bg-warning/10"
              : "border-border-subtle bg-surface/30",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="mb-1">
          <span
            className={cn(
              "text-[9px] font-black tracking-[0.16em] uppercase",
              entry.type === "error" ? "text-error" : "text-text-muted",
            )}
          >
            {entry.label}
          </span>
        </div>
        {entry.type === "assistant" && entry.content ? (
          <MessageMarkdown content={entry.content} />
        ) : entry.content ? (
          <p className="text-text-secondary font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap">
            {entry.content}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function isRetryStatusEntry(entry: NormalizedEntry): boolean {
  return (
    entry.type === "status" &&
    entry.label.toLowerCase() === "retrying" &&
    (entry.content ?? "").includes("Retry")
  );
}

function isApiFailureEntry(entry: NormalizedEntry): boolean {
  const text = `${entry.label}\n${entry.content ?? ""}`.toLowerCase();
  return (
    text.includes("failed to authenticate") ||
    text.includes("api error: 401") ||
    text.includes("invalid token") ||
    text.includes("无效的令牌") ||
    text.includes("authentication failed")
  );
}

function isMisleadingDoneAfterFailure(entry: NormalizedEntry): boolean {
  return (
    entry.type === "status" &&
    entry.label.toLowerCase() === "done" &&
    (entry.content ?? "").toLowerCase() === "turn completed"
  );
}

function compactTraceRuntimeEntries(entries: NormalizedEntry[]): NormalizedEntry[] {
  const compacted: NormalizedEntry[] = [];
  let retrySummary: NormalizedEntry | null = null;
  let retryStartId: string | null = null;
  const flushRetrySummary = () => {
    if (!retrySummary) return;
    compacted.push({
      ...retrySummary,
      id: retryStartId ? `${retryStartId}-retry-summary` : `${retrySummary.id}-summary`,
    });
    retrySummary = null;
    retryStartId = null;
  };

  for (const entry of entries) {
    if (isRetryStatusEntry(entry)) {
      retryStartId = retryStartId ?? entry.id;
      retrySummary = entry;
      continue;
    }
    flushRetrySummary();
    compacted.push(entry);
  }
  flushRetrySummary();

  const deduped = dedupeTraceRuntimeAssistantEntries(compacted);
  const hasApiFailure = deduped.some(isApiFailureEntry);
  if (!hasApiFailure) return deduped;
  return deduped
    .map((entry): NormalizedEntry => {
      if (!isApiFailureEntry(entry)) return entry;
      return { ...entry, type: "error", label: "Error" };
    })
    .filter((entry) => !isMisleadingDoneAfterFailure(entry));
}

function traceMessageContent(message: Record<string, unknown>): string {
  return traceText(message["content"]) ?? formatValue(message);
}

function traceDedupeText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function traceStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function traceAssistantBusinessDedupeKey(content: string): string {
  const record = safeJsonRecord(content.trim());
  if (record) {
    const setupScript = traceText(record["setup_script"]);
    const runCommand = traceText(record["run_command"]);
    if (setupScript || runCommand) {
      const accessUrl = traceText(record["access_url"]) ?? "";
      const notes = traceStringArray(record["notes"]).map(traceDedupeText).join("\n");
      return ["startup-script", setupScript ?? "", runCommand ?? "", accessUrl, notes].join("\u0000");
    }
  }
  return `text${"\u0000"}${traceDedupeText(content)}`;
}

function dedupeTraceRuntimeAssistantEntries(entries: NormalizedEntry[]): NormalizedEntry[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    if (entry.type !== "assistant" || !entry.content) return true;
    const key = traceAssistantBusinessDedupeKey(entry.content);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isDuplicateTraceAssistantMessage(
  message: Record<string, unknown>,
  entries: NormalizedEntry[],
): boolean {
  const role = traceText(message["role"]) ?? "message";
  if (role.toLowerCase() !== "assistant") return false;
  const content = traceMessageContent(message);
  if (!traceDedupeText(content)) return false;
  const dedupeKey = traceAssistantBusinessDedupeKey(content);
  return entries.some((entry) => {
    if (entry.type !== "assistant" || !entry.content) return false;
    return traceAssistantBusinessDedupeKey(entry.content) === dedupeKey;
  });
}

function TraceMessageBlock({
  message,
  fallbackId,
}: {
  message: Record<string, unknown>;
  fallbackId: string;
}) {
  const role = traceText(message["role"]) ?? "message";
  const content = traceMessageContent(message);
  const createdAt = traceText(message["created_at"]);
  const isAssistant = role.toLowerCase() === "assistant";
  return (
    <div className="border-border-subtle bg-surface/30 rounded-xl border px-3 py-2">
      <div className="text-text-faint mb-1 flex flex-wrap gap-2 font-mono text-[10px]">
        <span>{role}</span>
        {createdAt && <span>{formatTimestamp(createdAt)}</span>}
        <span>{fallbackId}</span>
      </div>
      {isAssistant ? (
        <MessageMarkdown content={content} />
      ) : (
        <p className="text-text-secondary font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap">
          {content}
        </p>
      )}
    </div>
  );
}

function TraceRawRuntimeLogs({ logs }: { logs: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <div className="space-y-1.5">
      <div className="text-text-muted text-[11px] font-semibold">
        {t("auditLog.trace.logs", { count: logs.length })}
      </div>
      {logs.map((log, index) => {
        const stream = traceText(log["stream"]) ?? "log";
        const content = traceText(log["content"]) ?? formatValue(log);
        const createdAt = traceText(log["created_at"]);
        return (
          <div
            key={`${stream}-${index}`}
            className="border-border-subtle bg-surface-input/30 rounded-md border px-2 py-1.5"
          >
            <div className="text-text-faint mb-1 flex flex-wrap gap-2 font-mono text-[10px]">
              <span>{stream}</span>
              {createdAt && <span>{formatTimestamp(createdAt)}</span>}
            </div>
            <pre className="text-text-secondary max-h-40 overflow-auto text-[11px] leading-relaxed break-words whitespace-pre-wrap">
              {content}
            </pre>
          </div>
        );
      })}
    </div>
  );
}

function TraceRawRuntimeContent({ rows }: { rows: TraceRuntimeRows }) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      {rows.messages.length > 0 && (
        <TraceValueBlock
          label={t("auditLog.trace.messages", { count: rows.messages.length })}
          value={rows.messages}
        />
      )}
      {rows.logs.length > 0 && <TraceRawRuntimeLogs logs={rows.logs} />}
    </div>
  );
}

function TraceRuntimeBlock({ rows }: { rows: TraceRuntimeRows }) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<"semantic" | "raw">("semantic");
  const logEvents = useMemo(() => traceLogEvents(rows.logs), [rows.logs]);
  const runtimeEntries = useMemo<NormalizedEntry[]>(() => normalizeLogs(logEvents), [logEvents]);
  const displayEntries = useMemo(
    () => compactTraceRuntimeEntries(runtimeEntries),
    [runtimeEntries],
  );
  const displayMessages = useMemo(
    () => rows.messages.filter((message) => !isDuplicateTraceAssistantMessage(message, displayEntries)),
    [rows.messages, displayEntries],
  );
  return (
    <div className="border-border-subtle bg-surface-raised/40 space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-text-faint text-[10px] font-bold tracking-wider uppercase">
          {t("auditLog.trace.runtime")}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="text-text-muted text-[11px]">
            {t("auditLog.trace.messages", { count: rows.messages.length })} ·{" "}
            {t("auditLog.trace.logs", { count: rows.logs.length })}
          </div>
          <div className="border-border-subtle bg-surface-input/40 inline-flex rounded-lg border p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("semantic")}
              aria-pressed={viewMode === "semantic"}
              className={cn(
                "rounded-md px-2 py-1 text-[10px] font-semibold transition-colors",
                viewMode === "semantic"
                  ? "bg-brand/15 text-brand"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              {t("auditLog.trace.semanticView")}
            </button>
            <button
              type="button"
              onClick={() => setViewMode("raw")}
              aria-pressed={viewMode === "raw"}
              className={cn(
                "rounded-md px-2 py-1 text-[10px] font-semibold transition-colors",
                viewMode === "raw"
                  ? "bg-brand/15 text-brand"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              {t("auditLog.trace.rawView")}
            </button>
          </div>
        </div>
      </div>
      {viewMode === "raw" ? (
        <TraceRawRuntimeContent rows={rows} />
      ) : (
        <>
          {displayEntries.length > 0 ? (
            <div className="space-y-2">
              {displayEntries.map((entry, index) => (
                <TraceRuntimeEntryBlock key={entry.id || index} entry={entry} />
              ))}
            </div>
          ) : rows.logs.length > 0 ? (
            <TraceRawRuntimeLogs logs={rows.logs} />
          ) : null}
          {displayMessages.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-text-muted text-[11px] font-semibold">
                {t("auditLog.trace.messages", { count: displayMessages.length })}
              </div>
              {displayMessages.map((message, index) => (
                <TraceMessageBlock
                  key={traceText(message["id"]) ?? `message-${index}`}
                  message={message}
                  fallbackId={`#${index + 1}`}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TraceDetailPanel({ entry }: { entry: AuditLog }) {
  const { t } = useI18n();
  const [detail, setDetail] = useState<AuditTraceDetail | AuditTraceCollection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const loadTrace = async () => {
    if (loading) return;
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (detail || error) {
      setExpanded(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = await getBestAuditTrace(entry);
      setDetail(next);
      setExpanded(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setExpanded(true);
    } finally {
      setLoading(false);
    }
  };

  const items = detail ? traceItemsFromDetail(detail) : [];
  const unavailable =
    detail && !detail.available
      ? detail.reason
      : detail && "items" in detail && detail.items.length === 0
        ? detail.reason ?? "trace_not_recorded"
        : null;

  return (
    <div className="mt-2 space-y-2">
      <Button size="sm" variant="outline" onClick={() => void loadTrace()} disabled={loading}>
        {loading
          ? t("auditLog.trace.loading")
          : expanded
            ? t("auditLog.trace.collapse")
            : entry.category === "cli_spawn"
              ? t("auditLog.trace.viewRuntime")
              : t("auditLog.trace.viewFull")}
      </Button>
      {expanded && error && (
        <div className="border-status-failed/30 bg-status-failed/10 text-status-failed rounded-lg border px-3 py-2 text-xs">
          {error}
        </div>
      )}
      {expanded && unavailable && (
        <div className="border-border-subtle bg-surface-input/30 text-text-muted rounded-lg border px-3 py-2 text-xs">
          {t("auditLog.trace.unavailable", { reason: unavailable })}
        </div>
      )}
      {expanded && items.map((item) => {
        const runtimeRows = traceRuntimeRows(item.response);
        return (
          <div
            key={item.id}
            className="border-border-subtle bg-surface-input/20 space-y-2 rounded-lg border p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className="border-brand/30 bg-brand/10 text-brand text-[10px]"
              >
                {item.kind}
              </Badge>
              {item.title && <span className="text-text-secondary text-xs">{item.title}</span>}
              {item.is_truncated && (
                <span className="text-status-awaiting text-[11px]">
                  {t("auditLog.trace.truncated")}
                </span>
              )}
            </div>
            {runtimeRows ? (
              <>
                <TraceRuntimeBlock rows={runtimeRows} />
                <details className="border-border-subtle rounded-lg border bg-surface/20">
                  <summary className="text-text-muted cursor-pointer px-3 py-2 text-[11px] font-semibold">
                    {t("auditLog.trace.metadata")}
                  </summary>
                  <div className="grid grid-cols-1 gap-2 px-3 pb-3 xl:grid-cols-2">
                    <TraceValueBlock label={t("auditLog.trace.request")} value={item.request} />
                    <TraceValueBlock label={t("auditLog.trace.metadata")} value={item.metadata} />
                  </div>
                </details>
              </>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                  <TraceValueBlock label={t("auditLog.trace.request")} value={item.request} />
                  <TraceValueBlock label={t("auditLog.trace.response")} value={item.response} />
                </div>
                <TraceValueBlock label={t("auditLog.trace.metadata")} value={item.metadata} />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
