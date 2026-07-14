"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Search,
  Edit3,
  Trash2,
  ChevronRight,
  Layers,
  GitBranch,
  Inbox,
  CheckCircle2,
  Activity,
  RefreshCw,
  DownloadCloud,
  Play,
  Square,
  AlertTriangle,
  ExternalLink,
  X,
} from "lucide-react";

import { getCodexIssues } from "@/lib/api/issues";
import {
  createWorkspace,
  deleteWorkspace,
  getWorkspaces,
  updateWorkspace,
} from "@/lib/api/workspaces";
import {
  getProject,
  getProjectRemoteStatus,
  getProjectRunLogs,
  getProjectRunStatus,
  isProjectRunStartError,
  pullProject,
  startProjectRun,
  stopProjectRun,
} from "@/lib/api/projects";
import type {
  CodexIssue,
  Project,
  ProjectRemoteStatus,
  ProjectRunLogLine,
  ProjectRunStatus,
  Workspace,
} from "@/lib/types";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { cn } from "@/lib/utils";
import { emitDataEvent } from "@/lib/dataEvents";
import { workspaceLabel } from "@/lib/workspaceLabel";
import { useI18n } from "@/providers/I18nProvider";
import { ProjectShell } from "@/features/projects/ProjectShell";
import { RemoteUpdateBadge } from "./RemoteUpdateBadge";
import { describePullResult } from "./projectRemoteStatus";
import {
  selectProjectRunRefreshError,
  shouldPollProjectServiceStatus,
  updateProjectRunRefreshError,
} from "./projectStartupConfig";
import type { ProjectRunRefreshErrors } from "./projectStartupConfig";

// How often to silently re-check the selected project against its remote.
const REMOTE_POLL_MS = 5 * 60_000;

// How often to poll for new lines from a running project process.
const RUN_LOG_POLL_MS = 2_000;
const SERVICE_STATUS_POLL_MS = 5_000;

interface Props {
  projectId: string;
}

/**
 * Project → Workspace CRUD console.
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │  [📂 icon]  <Project name>  /  Workspaces                        │
 *   │  description line — # workspaces · # issues · last activity …    │
 *   │                                                                  │
 *   │  [ 🔍 search …………]                            [+ New workspace]  │
 *   │  ┌──────────────────────────────────────────────────────────┐   │
 *   │  │ title                  status   issues  cwd       updated│   │
 *   │  │ row …                                            [edit][x]│  │
 *   │  └──────────────────────────────────────────────────────────┘   │
 *   └──────────────────────────────────────────────────────────────────┘
 */
export function ProjectWorkspacesPage({ projectId }: Props) {
  const { t } = useI18n();
  const router = useRouter();
  const { addToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [issuesByWs, setIssuesByWs] = useState<Record<string, CodexIssue[]>>({});
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Workspace | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Workspace | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Guards the auto-create-default-workspace path so it fires at most once per
  // mount (React strict-mode double effects / re-loads won't spawn duplicates).
  const autoCreatedRef = useRef(false);

  // Remote-update detection. `null` status = not yet loaded → badge shows
  // "checking…".
  const [remoteStatus, setRemoteStatus] = useState<ProjectRemoteStatus | null>(null);
  const [remoteChecking, setRemoteChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);

  // One-click project run (dev server). `runStatus` mirrors the backend
  // in-memory process; `runLogs` accumulates streamed lines (polled while
  // running). `lastSeqRef` tracks the highest seq we've appended so we only
  // request the delta.
  const [runStatus, setRunStatus] = useState<ProjectRunStatus | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [runLogs, setRunLogs] = useState<ProjectRunLogLine[]>([]);
  const [runRefreshErrors, setRunRefreshErrors] = useState<ProjectRunRefreshErrors>({
    status: null,
    logs: null,
  });
  const [logsOpen, setLogsOpen] = useState(false);
  const lastSeqRef = useRef(0);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const reportRunRefreshFailure = useCallback(
    (
      source: keyof ProjectRunRefreshErrors,
      context: "status load" | "service status poll" | "log poll" | "status resync",
      err: unknown,
    ) => {
      console.error(`project run ${context} failed:`, err);
      const message = err instanceof Error ? err.message : String(err);
      setRunRefreshErrors((current) => updateProjectRunRefreshError(current, source, message));
    },
    [],
  );
  const runLoadError = selectProjectRunRefreshError(runRefreshErrors);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [proj, ws] = await Promise.all([getProject(projectId), getWorkspaces(projectId)]);
      setProject(proj);
      // Default workspace: never force the user to hand-create one. If a project
      // has no workspace yet, auto-create a default and drop straight into it.
      if (ws.length === 0 && !autoCreatedRef.current) {
        autoCreatedRef.current = true;
        try {
          const name = proj.name.trim().length >= 3 ? proj.name.trim() : t("workspace.defaultName");
          const created = await createWorkspace(name, projectId, proj.repo_path ?? "");
          emitDataEvent("workspaces:changed");
          router.replace(`/workspaces/${created.id}`);
          return;
        } catch (err) {
          // Fall through to the normal (empty) list so the user can retry by hand.
          addToast({
            type: "error",
            title: t("workspace.toast.createFailed"),
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
      setWorkspaces(ws);
      // Load issues per workspace in parallel for the count column.
      const entries = await Promise.all(
        ws.map(async (w) => [w.id, await getCodexIssues(w.id).catch(() => [])] as const),
      );
      setIssuesByWs(Object.fromEntries(entries));
    } catch (err) {
      addToast({
        type: "error",
        title: t("workspace.toast.loadFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [projectId, addToast, t, router]);

  useEffect(() => {
    void load();
  }, [load]);

  // Fetch the project's remote status: immediately on mount / projectId change
  // (with a real `git fetch`), then poll on an interval. Failures stay silent —
  // the next poll (or a manual check) retries.
  const loadRemoteStatus = useCallback(async (id: string, opts: { fetch: boolean }) => {
    setRemoteChecking(true);
    try {
      return await getProjectRemoteStatus(id, { fetch: opts.fetch });
    } finally {
      setRemoteChecking(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRemoteStatus(null);
    const run = async () => {
      try {
        const status = await loadRemoteStatus(projectId, { fetch: true });
        if (!cancelled) setRemoteStatus(status);
      } catch {
        // Network/transient error — leave the badge checking; the next poll
        // (or a manual "check for updates") will retry.
      }
    };
    void run();
    const id = setInterval(run, REMOTE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [projectId, loadRemoteStatus]);

  const handleCheckUpdate = useCallback(async () => {
    try {
      const status = await loadRemoteStatus(projectId, { fetch: true });
      setRemoteStatus(status);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.syncFailedOffline");
      addToast({ type: "error", title: msg });
    }
  }, [projectId, loadRemoteStatus, addToast, t]);

  const handleSync = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const result = await pullProject(projectId);
      const toast = describePullResult(result, t);
      addToast({ type: toast.type, title: toast.title });
      // Refresh status (cheap, no fetch) so the badge reflects the new HEAD.
      const status = await loadRemoteStatus(projectId, { fetch: false });
      setRemoteStatus(status);
      // Refresh the workspaces list so any branch-derived fields stay current.
      if (result.success) void load();
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.syncFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setSyncing(false);
    }
  }, [projectId, syncing, loadRemoteStatus, load, addToast, t]);

  // Fetch the project's run status once on mount / projectId change. Reset the
  // log buffer when switching projects.
  useEffect(() => {
    let cancelled = false;
    setRunStatus(null);
    setRunLogs([]);
    setRunRefreshErrors({ status: null, logs: null });
    setLogsOpen(false);
    lastSeqRef.current = 0;
    void (async () => {
      try {
        const status = await getProjectRunStatus(projectId);
        if (!cancelled) {
          setRunStatus(status);
          setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", null));
          if (status.running) setLogsOpen(true);
        }
      } catch (err) {
        if (cancelled) return;
        reportRunRefreshFailure("status", "status load", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, reportRunRefreshFailure]);

  // While the process is running, poll for new log lines (~2s). The `running` /
  // `exit_code` from each response keep `runStatus` fresh; once the process
  // stops, `running` flips false and the effect tears down the interval.
  const running = runStatus?.running ?? false;
  const externalServiceReachable = !running && runStatus?.service.state === "reachable";
  const pollServiceStatus = shouldPollProjectServiceStatus(runStatus);
  useEffect(() => {
    if (!pollServiceStatus) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getProjectRunStatus(projectId);
        if (cancelled) return;
        setRunStatus(status);
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", null));
      } catch (err) {
        if (cancelled) return;
        reportRunRefreshFailure("status", "service status poll", err);
      }
    };
    const id = setInterval(tick, SERVICE_STATUS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollServiceStatus, projectId, reportRunRefreshFailure]);

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await getProjectRunLogs(projectId, lastSeqRef.current);
        if (cancelled) return;
        if (res.lines.length > 0) {
          lastSeqRef.current = res.last_seq;
          setRunLogs((prev) => [...prev, ...res.lines]);
        }
        setRunStatus((prev) =>
          prev ? { ...prev, running: res.running, exit_code: res.exit_code } : prev,
        );
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "logs", null));
      } catch (err) {
        if (cancelled) return;
        reportRunRefreshFailure("logs", "log poll", err);
      }
    };
    void tick();
    const id = setInterval(tick, RUN_LOG_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [running, projectId, reportRunRefreshFailure]);

  // Keep the log panel scrolled to the newest line.
  useEffect(() => {
    if (logsOpen) logEndRef.current?.scrollIntoView({ block: "end" });
  }, [runLogs, logsOpen]);

  const handleStartRun = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      const result = await startProjectRun(projectId);
      if (isProjectRunStartError(result)) {
        if (result.error === "already_running" || result.error === "service_already_reachable") {
          // Re-sync with the live status rather than show a hard error.
          try {
            const status = await getProjectRunStatus(projectId);
            setRunStatus(status);
            setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", null));
          } catch (err) {
            reportRunRefreshFailure("status", "status resync", err);
          }
          addToast({
            type: "info",
            title:
              result.error === "service_already_reachable"
                ? t("startupConfig.serviceAlreadyReachable")
                : t("projects.runAlreadyRunning"),
          });
        } else if (result.error === "no_run_command") {
          addToast({ type: "error", title: t("projects.runNoCommand") });
        } else {
          // refused
          addToast({
            type: "error",
            title: t("projects.runRefused"),
            message: result.pattern ?? undefined,
          });
        }
        return;
      }
      // Success: reset the log buffer for the fresh process and start polling.
      lastSeqRef.current = 0;
      setRunLogs([]);
      setRunStatus(result);
      setRunRefreshErrors({ status: null, logs: null });
      setLogsOpen(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.runStartFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, runBusy, reportRunRefreshFailure, addToast, t]);

  const handleStopRun = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      const status = await stopProjectRun(projectId);
      setRunStatus(status);
      setRunRefreshErrors({ status: null, logs: null });
      addToast({ type: "success", title: t("projects.runStopped") });
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.runStopFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, runBusy, addToast, t]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter(
      (w) => (w.title || w.id).toLowerCase().includes(q) || (w.cwd || "").toLowerCase().includes(q),
    );
  }, [workspaces, query]);

  const totalIssues = useMemo(
    () => Object.values(issuesByWs).reduce((acc, list) => acc + list.length, 0),
    [issuesByWs],
  );
  const activeWorkspaces = useMemo(
    () => workspaces.filter((w) => w.status === "running" || w.status === "responding").length,
    [workspaces],
  );

  const handleCreate = useCallback(
    async (title: string, cwd: string) => {
      try {
        const ws = await createWorkspace(title, projectId, cwd);
        setWorkspaces((prev) => [ws, ...prev]);
        setIssuesByWs((prev) => ({ ...prev, [ws.id]: [] }));
        emitDataEvent("workspaces:changed");
        addToast({ type: "success", title: t("workspace.toast.created") });
        setCreateOpen(false);
      } catch (err) {
        addToast({
          type: "error",
          title: t("workspace.toast.createFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [projectId, addToast, t],
  );

  const handleUpdate = useCallback(
    async (id: string, title: string, cwd: string, planFirstPm: boolean) => {
      try {
        const next = await updateWorkspace(id, { title, cwd, plan_first_pm: planFirstPm });
        setWorkspaces((prev) => prev.map((w) => (w.id === id ? next : w)));
        emitDataEvent("workspaces:changed");
        addToast({ type: "success", title: t("workspace.toast.updated") });
        setEditing(null);
      } catch (err) {
        addToast({
          type: "error",
          title: t("workspace.toast.updateFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [addToast, t],
  );

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteWorkspace(pendingDelete.id);
      setWorkspaces((prev) => prev.filter((w) => w.id !== pendingDelete.id));
      setIssuesByWs((prev) => {
        const next = { ...prev };
        delete next[pendingDelete.id];
        return next;
      });
      emitDataEvent("workspaces:changed");
      addToast({ type: "success", title: t("workspace.toast.deleted") });
      setPendingDelete(null);
    } catch (err) {
      addToast({
        type: "error",
        title: t("workspace.toast.deleteFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  }, [pendingDelete, addToast, t]);

  return (
    <ProjectShell projectId={projectId} project={project}>
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi
          icon={<Layers size={14} />}
          label={t("sidebar.workspaces")}
          value={workspaces.length}
          tint="brand"
          loading={loading}
        />
        <Kpi
          icon={<Activity size={14} />}
          label={t("workspace.projectPage.kpiActive")}
          value={activeWorkspaces}
          tint="running"
          pulse={activeWorkspaces > 0}
          loading={loading}
        />
        <Kpi
          icon={<Inbox size={14} />}
          label={t("workspace.projectPage.kpiIssues")}
          value={totalIssues}
          tint="info"
          loading={loading}
        />
        <div className="relative">
          <Kpi
            icon={<CheckCircle2 size={14} />}
            label={t("workspace.projectPage.kpiBranch")}
            valueText={project?.default_branch ?? "—"}
            tint="done"
            loading={loading}
          />
          <div className="absolute right-3 bottom-3">
            <RemoteUpdateBadge
              status={remoteStatus}
              checking={remoteChecking && remoteStatus === null}
            />
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("workspace.projectPage.searchPlaceholder")}
            className="pl-8 bg-surface-input border-border-subtle h-8 text-[13px]"
          />
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={handleCheckUpdate}
          disabled={remoteChecking}
          aria-label={t("projects.checkUpdate")}
          title={t("projects.checkUpdate")}
          className="gap-1 ml-auto"
        >
          <RefreshCw size={14} className={cn(remoteChecking && "animate-spin")} />
          {remoteChecking ? t("projects.checking") : t("projects.checkUpdate")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={handleSync}
          disabled={syncing || !remoteStatus?.can_fast_forward}
          aria-label={t("projects.sync")}
          title={t("projects.sync")}
          className="gap-1"
        >
          <DownloadCloud size={14} className={cn(syncing && "animate-pulse")} />
          {syncing ? t("projects.syncing") : t("projects.sync")}
        </Button>
        {running ? (
          <Button
            size="sm"
            variant="outline"
            onClick={handleStopRun}
            disabled={runBusy}
            aria-label={t("projects.runStop")}
            title={t("projects.runStop")}
            className="gap-1"
          >
            <span
              aria-hidden
              className="inline-block size-2 rounded-full bg-status-running animate-pulse"
            />
            <Square size={14} />
            {runBusy ? t("projects.runStopping") : t("projects.runStop")}
          </Button>
        ) : externalServiceReachable && runStatus?.service.url ? (
          <a
            href={runStatus.service.url}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-1")}
          >
            <ExternalLink size={14} />
            {t("startupConfig.openService")}
          </a>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={handleStartRun}
            disabled={runBusy || !project?.run_command}
            aria-label={t("projects.runStart")}
            title={project?.run_command ? t("projects.runStart") : t("projects.runNoCommand")}
            className="gap-1"
          >
            <Play size={14} />
            {runBusy ? t("projects.runStarting") : t("projects.runStart")}
          </Button>
        )}
        <Button
          onClick={() => setCreateOpen(true)}
          size="sm"
          className="gap-1 bg-brand hover:bg-brand-strong text-black font-semibold"
        >
          <Plus size={14} /> {t("workspace.projectPage.new")}
        </Button>
      </div>

      {runLoadError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-status-failed/40 bg-status-failed/10 px-3 py-2 text-[12px]"
        >
          <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-status-failed" />
          <div className="min-w-0">
            <p className="font-medium text-status-failed">{t("projects.runRefreshFailed")}</p>
            <p className="break-words text-text-secondary">{runLoadError}</p>
          </div>
        </div>
      )}

      {/* Run log panel */}
      {logsOpen && runLogs.length > 0 && (
        <section className="rounded-xl border border-border-subtle bg-black/90 overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border-subtle bg-surface text-[12px]">
            <span
              aria-hidden
              className={cn(
                "inline-block size-2 rounded-full",
                running ? "bg-status-running animate-pulse" : "bg-text-muted",
              )}
            />
            <span className="font-semibold">{t("projects.runLogsTitle")}</span>
            <span className="text-text-muted">
              {running ? t("projects.runRunning") : t("projects.runStopped")}
              {runStatus?.pid != null && running ? ` · pid ${runStatus.pid}` : ""}
              {!running && runStatus?.exit_code != null
                ? ` · ${t("projects.runExitCode", { code: runStatus.exit_code })}`
                : ""}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  setRunLogs([]);
                  lastSeqRef.current = runStatus?.running ? lastSeqRef.current : 0;
                }}
                className="rounded-md px-2 py-1 text-text-muted hover:bg-surface-input hover:text-foreground transition-colors"
              >
                {t("projects.runClearLogs")}
              </button>
              <button
                type="button"
                onClick={() => setLogsOpen(false)}
                aria-label={t("workspace.cancel")}
                className="size-7 rounded-md text-text-muted hover:bg-surface-input hover:text-foreground flex items-center justify-center transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          </div>
          <div className="max-h-72 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed">
            {runLogs.map((l) => (
              <div
                key={l.seq}
                className={cn(
                  "whitespace-pre-wrap break-all",
                  l.stream === "stderr" ? "text-status-failed" : "text-text-secondary",
                )}
              >
                {l.line}
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        </section>
      )}

      {/* Table */}
      <section className="rounded-xl border border-border-subtle bg-surface-raised overflow-hidden">
        <div className="grid grid-cols-[1fr_120px_90px_1.6fr_120px_70px] gap-3 px-4 py-2.5 text-[10px] uppercase tracking-wider text-text-muted border-b border-border-subtle bg-surface">
          <div>{t("workspace.table.title")}</div>
          <div>{t("workspace.table.status")}</div>
          <div className="text-right">{t("workspace.table.issues")}</div>
          <div>{t("workspace.table.workingDir")}</div>
          <div>{t("workspace.table.updated")}</div>
          <div className="text-right">{t("workspace.table.actions")}</div>
        </div>
        {loading ? (
          <div
            data-density="project-workspaces-dispatch-loading"
            className="motion-essential relative flex min-h-[200px] items-center justify-center gap-2 overflow-hidden px-4 py-10 text-sm font-semibold text-text-muted"
          >
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-running/70 to-transparent"
            />
            <AgentThinkingIndicator phase="dispatching" size={16} />
            {t("workspace.loading")}
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-text-muted">
              {query ? t("workspace.emptyFiltered") : t("workspace.emptyCreatePrompt")}
            </p>
            {!query && (
              <Button
                onClick={() => setCreateOpen(true)}
                size="sm"
                className="mt-3 gap-1 bg-brand hover:bg-brand-strong text-black font-semibold"
              >
                <Plus size={14} /> {t("workspace.createFirst")}
              </Button>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {filtered.map((ws) => (
              <WorkspaceRow
                key={ws.id}
                ws={ws}
                issueCount={issuesByWs[ws.id]?.length ?? 0}
                onOpen={() => router.push(`/workspaces/${ws.id}`)}
                onEdit={() => setEditing(ws)}
                onDelete={() => setPendingDelete(ws)}
              />
            ))}
          </ul>
        )}
      </section>

      <WorkspaceFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title={t("workspace.dialog.newTitle")}
        initial={{ title: "", cwd: project?.repo_path ?? "" }}
        defaultCwdHint={project?.repo_path ?? ""}
        onSubmit={({ title, cwd }) => handleCreate(title, cwd)}
        showPlanFirstPm={false}
      />

      <WorkspaceFormDialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        title={t("workspace.dialog.editTitle")}
        initial={{
          title: editing?.title ?? "",
          cwd: editing?.cwd ?? "",
          planFirstPm: editing?.settings?.plan_first_pm ?? true,
        }}
        defaultCwdHint={project?.repo_path ?? ""}
        onSubmit={({ title, cwd, planFirstPm }) => {
          if (editing) return handleUpdate(editing.id, title, cwd, planFirstPm);
          return undefined;
        }}
        submitLabel={t("workspace.dialog.submitSave")}
        showPlanFirstPm
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={t("workspace.dialog.deleteTitle")}
        description={
          pendingDelete
            ? t("workspace.dialog.deleteDescription", {
                name: pendingDelete.title || pendingDelete.id.slice(0, 8),
              })
            : ""
        }
        confirmText={t("workspace.action.delete")}
        cancelText={t("workspace.cancel")}
        onConfirm={handleDelete}
        isLoading={deleting}
        variant="destructive"
      />
    </ProjectShell>
  );
}

// ============================================================================
// Row
// ============================================================================

function WorkspaceRow({
  ws,
  issueCount,
  onOpen,
  onEdit,
  onDelete,
}: {
  ws: Workspace;
  issueCount: number;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const kind = inferStatusKind(ws.status);
  const isWorkspaceActive = ws.status === "running" || ws.status === "responding";
  return (
    <li
      data-density={isWorkspaceActive ? "project-workspaces-active-row" : "project-workspaces-row"}
      className={cn(
        "relative grid grid-cols-[1fr_120px_90px_1.6fr_120px_70px] gap-3 px-4 py-3 items-center overflow-hidden group hover:bg-surface-hover transition-colors",
        isWorkspaceActive && "motion-essential",
        isWorkspaceActive && "bg-status-running/5",
      )}
    >
      {isWorkspaceActive && (
        <span
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-running/70 to-transparent"
        />
      )}
      <button type="button" onClick={onOpen} className="min-w-0 flex items-center gap-2 text-left">
        <span className="size-1.5 rounded-full bg-brand/70 shrink-0" />
        <span className="text-[13px] font-medium truncate group-hover:text-brand transition-colors">
          {workspaceLabel(ws)}
        </span>
        <ChevronRight
          size={12}
          className="text-text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
        />
      </button>
      <div className="flex items-center gap-1.5">
        {isWorkspaceActive && (
          <AgentThinkingIndicator phase="dispatching" size={12} className="shrink-0" />
        )}
        <StatusBadge kind={kind} label={humanStatus(t, ws.status)} />
      </div>
      <div className="text-right text-[13px] tabular-nums">
        {issueCount === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span className="font-medium">{issueCount}</span>
        )}
      </div>
      <div className="font-mono text-[12px] text-text-muted truncate flex items-center gap-1.5">
        <GitBranch size={11} />
        {ws.cwd || "—"}
      </div>
      <div className="text-[11px] font-mono text-text-muted">
        {ws.last_active_at ? relTime(t, ws.last_active_at) : "—"}
      </div>
      <div className="flex items-center gap-1 justify-end">
        <button
          type="button"
          onClick={onEdit}
          aria-label={t("workspace.action.edit")}
          className="size-7 rounded-md hover:bg-surface-input text-text-muted hover:text-foreground flex items-center justify-center transition-colors"
        >
          <Edit3 size={13} />
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label={t("workspace.action.delete")}
          className="size-7 rounded-md hover:bg-status-failed/10 text-text-muted hover:text-status-failed flex items-center justify-center transition-colors"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </li>
  );
}

// ============================================================================
// Create / edit dialog
// ============================================================================

function WorkspaceFormDialog({
  open,
  onOpenChange,
  title,
  initial,
  defaultCwdHint,
  onSubmit,
  submitLabel,
  showPlanFirstPm = false,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  title: string;
  initial: { title: string; cwd: string; planFirstPm?: boolean };
  defaultCwdHint: string;
  onSubmit: (values: { title: string; cwd: string; planFirstPm: boolean }) => void | Promise<void>;
  submitLabel?: string;
  showPlanFirstPm?: boolean;
}) {
  const { t } = useI18n();
  const [titleDraft, setTitleDraft] = useState(initial.title);
  const [cwdDraft, setCwdDraft] = useState(initial.cwd);
  const [planFirstPm, setPlanFirstPm] = useState(initial.planFirstPm ?? true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setTitleDraft(initial.title);
      setCwdDraft(initial.cwd);
      setPlanFirstPm(initial.planFirstPm ?? true);
      setSaving(false);
    }
  }, [open, initial.title, initial.cwd, initial.planFirstPm]);

  const trimmedTitleLength = titleDraft.trim().length;
  const showTitleMinLengthHint = trimmedTitleLength > 0 && trimmedTitleLength < 3;
  const canSubmit = trimmedTitleLength >= 3 && !saving;

  const submit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      await onSubmit({ title: titleDraft.trim(), cwd: cwdDraft.trim(), planFirstPm });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{t("workspace.dialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field
            label={t("workspace.field.title")}
            hint={showTitleMinLengthHint ? t("workspace.field.titleMinLengthHint") : undefined}
            tone={showTitleMinLengthHint ? "warning" : "muted"}
          >
            <Input
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              placeholder={t("workspace.field.titlePlaceholder")}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit();
                }
              }}
              className="bg-surface-input border-border-subtle"
            />
          </Field>
          <Field
            label={t("workspace.field.workingDir")}
            hint={
              cwdDraft.trim().length === 0
                ? t("workspace.field.defaultCwdHint", {
                    path: defaultCwdHint || t("workspace.field.defaultCwdFallback"),
                  })
                : undefined
            }
          >
            <Input
              value={cwdDraft}
              onChange={(e) => setCwdDraft(e.target.value)}
              placeholder={defaultCwdHint || t("workspace.field.workingDirPlaceholder")}
              className="bg-surface-input border-border-subtle font-mono text-[12px]"
            />
          </Field>
          {showPlanFirstPm && (
            <label className="flex items-start gap-2 rounded-lg border border-border-subtle bg-surface-input/40 px-3 py-2">
              <input
                type="checkbox"
                checked={planFirstPm}
                onChange={(e) => setPlanFirstPm(e.target.checked)}
                className="mt-0.5 size-4 rounded border-border-subtle"
              />
              <span className="min-w-0">
                <span className="block text-[11px] uppercase tracking-wider text-text-muted">
                  {t("workspace.dialog.planFirstPm")}
                </span>
                <span className="block text-[12px] text-text-secondary mt-0.5">
                  {t("workspace.dialog.planFirstPmHint")}
                </span>
              </span>
            </label>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {t("workspace.cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={!canSubmit}
            className={cn(
              "bg-brand hover:bg-brand-strong text-black font-semibold",
              !canSubmit && "opacity-50",
            )}
          >
            {saving ? t("workspace.saving") : submitLabel || t("workspace.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  hint,
  tone = "muted",
  children,
}: {
  label: string;
  hint?: string | undefined;
  tone?: "muted" | "warning" | undefined;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-text-muted">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && (
        <p
          className={cn(
            "mt-1 text-[11px]",
            tone === "warning" ? "text-status-awaiting" : "text-text-muted",
          )}
        >
          {hint}
        </p>
      )}
    </label>
  );
}

// ============================================================================
// KPI tile
// ============================================================================

type Tint = "brand" | "running" | "info" | "done" | "failed";

const TINT_TO_CSS: Record<Tint, { dot: string; iconBg: string }> = {
  brand: { dot: "bg-brand", iconBg: "bg-brand/15 text-brand" },
  running: { dot: "bg-status-running", iconBg: "bg-status-running/15 text-status-running" },
  info: { dot: "bg-status-info", iconBg: "bg-status-info/15 text-status-info" },
  done: { dot: "bg-status-done", iconBg: "bg-status-done/15 text-status-done" },
  failed: { dot: "bg-status-failed", iconBg: "bg-status-failed/15 text-status-failed" },
};

function Kpi({
  icon,
  label,
  value,
  valueText,
  tint,
  pulse,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  value?: number;
  valueText?: string;
  tint: Tint;
  pulse?: boolean;
  loading?: boolean;
}) {
  const t = TINT_TO_CSS[tint];
  return (
    <div
      data-density={pulse ? "project-workspaces-active-kpi" : "project-workspaces-kpi"}
      className={cn(
        "relative overflow-hidden rounded-xl border border-border-subtle bg-surface-raised p-3 hover:border-border-strong transition-colors",
        pulse && "motion-essential",
        pulse && "border-status-running/35 bg-status-running/5",
      )}
    >
      {pulse && (
        <span
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-running/70 to-transparent"
        />
      )}
      <div className="flex items-center justify-between mb-2">
        <span className={cn("size-7 rounded-md inline-flex items-center justify-center", t.iconBg)}>
          {pulse ? <AgentThinkingIndicator phase="dispatching" size={14} /> : icon}
        </span>
        {pulse && (
          <span className="motion-essential relative inline-flex">
            <span className={cn("size-1.5 rounded-full", t.dot)} />
          </span>
        )}
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
        <div className="text-2xl font-bold tabular-nums mt-0.5 truncate">
          {loading ? "—" : (valueText ?? value ?? 0)}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Helpers
// ============================================================================

function humanStatus(
  t: (key: string, params?: Record<string, string | number>) => string,
  s: string | null | undefined,
): string {
  if (!s) return t("workspace.status.idle");
  if (s === "running") return t("workspace.status.running");
  if (s === "responding") return t("workspace.status.responding");
  if (s === "idle") return t("workspace.status.idle");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function relTime(
  t: (key: string, params?: Record<string, string | number>) => string,
  iso: string,
): string {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "—";
  const diff = Date.now() - timestamp;
  if (diff < 60_000) return t("workspace.time.now");
  if (diff < 3_600_000) return t("workspace.time.minutes", { count: Math.floor(diff / 60_000) });
  if (diff < 86_400_000) return t("workspace.time.hours", { count: Math.floor(diff / 3_600_000) });
  return t("workspace.time.days", { count: Math.floor(diff / 86_400_000) });
}
