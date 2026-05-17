"use client";

import { useEffect, useMemo, useState, useCallback, useRef, type RefObject } from "react";
import { useRouter } from "next/navigation";
import { Filter, ArrowDownUp, Plus, GitBranch, Trash2 } from "lucide-react";
import {
  autoStartIssueGraph,
  chatCodexTask,
  createCodexIssue,
  deleteCodexIssue,
  getCodexIssues,
  getCodexTasks,
  getProject,
  getRuntimeCatalog,
  getWorkspace,
} from "@/lib/api";
import type { CodexIssue, CodexTask, Project, RuntimeCatalog, Workspace } from "@/lib/types";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { LogRow } from "@/components/ui/log-row";
import { ApprovalCard } from "@/components/ui/approval-card";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { createIssueAndInitialTask } from "@/features/workbench/workbenchActions";
import { NewIssueDialog } from "./NewIssueDialog";
import {
  deriveWorkspaceConsoleDefaultRuntime,
  deriveWorkspaceConsoleMode,
  formatWorkspaceConsoleRepoLabel,
  getWorkspaceConsoleRoleLabel,
  pickActiveIssueTask,
  type WorkspaceConsoleMode,
} from "./workspaceConsoleState";

interface Props {
  workspaceId: string;
}

/**
 * Console v2 master-detail layout.
 *
 *   ┌─────────────────────── Issue list ───────────────────────┐ ┌── Run detail ──┐
 *   │ Workspace v2 · development  [Filter] [Sort] [+ New task] │ │ Running run·… │
 *   │                                                          │ │ Title         │
 *   │ ○ Plan auth module with JWT…     Done    feat/auth-plan… │ │ tabs          │
 *   │ ◉ Design SessionService → Adapt  Running feat/adapter-w…│ │ log rows      │
 *   │ ...                                                      │ │ approval card │
 *   │ [codex exec --json   continuation #4923] ──── [Run task↵]│ │               │
 *   └──────────────────────────────────────────────────────────┘ └───────────────┘
 */
export default function WorkspaceConsole({ workspaceId }: Props) {
  const router = useRouter();
  const { addToast } = useToast();
  const { t } = useI18n();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hasInitializedSelection, setHasInitializedSelection] = useState(false);
  const [selectedIssueTasks, setSelectedIssueTasks] = useState<CodexTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [createCommand, setCreateCommand] = useState("");
  const [chatCommand, setChatCommand] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newIssueOpen, setNewIssueOpen] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const ws = await getWorkspace(workspaceId);
      setWorkspace(ws);
      const [proj, all, runtimeCatalog] = await Promise.all([
        ws.project_id ? getProject(ws.project_id) : Promise.resolve(null),
        getCodexIssues(workspaceId),
        getRuntimeCatalog().catch(() => null),
      ]);
      setProject(proj);
      setCatalog(runtimeCatalog);
      setIssues(all);
    } catch (err) {
      addToast({ type: "error", title: t("workspace.toast.loadFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!hasInitializedSelection) {
      setSelectedId(issues[0]?.id ?? null);
      setHasInitializedSelection(true);
      return;
    }
    if (selectedId && !issues.some((issue) => issue.id === selectedId)) {
      setSelectedId(null);
    }
  }, [hasInitializedSelection, issues, selectedId]);

  const selected = useMemo(
    () => issues.find((i) => i.id === selectedId) ?? null,
    [issues, selectedId],
  );

  useEffect(() => {
    if (!selectedId) {
      setSelectedIssueTasks([]);
      return;
    }
    let cancelled = false;
    void getCodexTasks(null, selectedId)
      .then((tasks) => {
        if (!cancelled) setSelectedIssueTasks(tasks);
      })
      .catch(() => {
        if (!cancelled) setSelectedIssueTasks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const mode = deriveWorkspaceConsoleMode(selectedId);
  const defaultRuntime = useMemo(
    () => deriveWorkspaceConsoleDefaultRuntime(catalog),
    [catalog],
  );
  const repoLabel = useMemo(
    () => formatWorkspaceConsoleRepoLabel(project?.repo_path),
    [project?.repo_path],
  );
  const activeTask = useMemo(
    () => pickActiveIssueTask(selected, selectedIssueTasks),
    [selected, selectedIssueTasks],
  );
  const activeRoleLabel = useMemo(
    () => getWorkspaceConsoleRoleLabel(activeTask?.role),
    [activeTask?.role],
  );

  const handleSubmitCommand = async () => {
    const content = (mode === "create" ? createCommand : chatCommand).trim();
    if (!content || isSubmitting) return;
    if (mode === "chat" && !activeTask) return;

    setIsSubmitting(true);
    try {
      if (mode === "create") {
        const title = content.slice(0, 60);
        const { issue } = await createIssueAndInitialTask({
          workspaceId,
          title,
          description: content,
          createCodexIssue,
          autoStartIssueGraph,
        });
        setIssues((prev) => [issue, ...prev]);
        setSelectedId(issue.id);
        setSelectedIssueTasks([]);
        setCreateCommand("");
        addToast({ type: "success", title: t("issue.toast.created") });
      } else {
        await chatCodexTask(activeTask!.id, content);
        setChatCommand("");
        addToast({ type: "success", title: t("workspace.console.chatSent") });
        const refreshedTasks = await getCodexTasks(null, selectedId);
        setSelectedIssueTasks(refreshedTasks);
        void load();
      }
    } catch (err) {
      addToast({
        type: "error",
        title: mode === "create" ? t("issue.toast.createFailed") : t("workspace.console.chatFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteCodexIssue(id);
        setIssues((prev) => prev.filter((i) => i.id !== id));
        if (selectedId === id) setSelectedId(null);
      } catch (err) {
        addToast({ type: "error", title: "Failed to delete", message: err instanceof Error ? err.message : String(err) });
      }
    },
    [addToast, selectedId],
  );

  return (
    <div className="h-full flex min-h-0">
      <IssueListColumn
        workspace={workspace}
        project={project}
        issues={issues}
        mode={mode}
        selectedId={selectedId}
        activeTask={activeTask}
        activeRoleLabel={activeRoleLabel}
        repoLabel={repoLabel}
        defaultExecutor={defaultRuntime.executor}
        command={mode === "create" ? createCommand : chatCommand}
        composerRef={composerRef}
        onSelect={(id) => setSelectedId((current) => (current === id ? null : id))}
        onNewIssue={() => setNewIssueOpen(true)}
        onOpen={(id) => router.push(`/issues/${id}`)}
        onDelete={handleDelete}
        isLoading={isLoading}
        selectedIssue={selected}
        onCommandChange={(value) => {
          if (mode === "create") setCreateCommand(value);
          else setChatCommand(value);
        }}
        onSubmitCommand={handleSubmitCommand}
        isCreating={isSubmitting}
      />
      <RunDetailColumn issue={selected} project={project} />
      <NewIssueDialog
        open={newIssueOpen}
        onOpenChange={setNewIssueOpen}
        workspaceId={workspaceId}
        project={project}
        catalog={catalog}
        onCreated={(issue) => {
          setIssues((prev) => [issue, ...prev.filter((item) => item.id !== issue.id)]);
          setSelectedId(issue.id);
          setSelectedIssueTasks([]);
        }}
      />
    </div>
  );
}

// ============================================================================
// Middle column — issue table + bottom command input
// ============================================================================

interface ListColumnProps {
  workspace: Workspace | null;
  project: Project | null;
  issues: CodexIssue[];
  mode: WorkspaceConsoleMode;
  selectedId: string | null;
  selectedIssue: CodexIssue | null;
  activeTask: CodexTask | null;
  activeRoleLabel: string;
  repoLabel: string;
  defaultExecutor: string;
  composerRef: RefObject<HTMLTextAreaElement>;
  onSelect: (id: string) => void;
  onNewIssue: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  isLoading: boolean;
  command: string;
  onCommandChange: (s: string) => void;
  onSubmitCommand: () => void;
  isCreating: boolean;
}

function IssueListColumn({
  workspace,
  project,
  issues,
  mode,
  selectedId,
  selectedIssue,
  activeTask,
  activeRoleLabel,
  repoLabel,
  defaultExecutor,
  composerRef,
  onSelect,
  onNewIssue,
  onOpen,
  onDelete,
  isLoading,
  command,
  onCommandChange,
  onSubmitCommand,
  isCreating,
}: ListColumnProps) {
  const { t } = useI18n();
  const bannerText =
    mode === "create"
      ? t("workspace.console.createBanner", { project: repoLabel, executor: defaultExecutor })
      : activeTask && selectedIssue
        ? t("workspace.console.chatBanner", {
            issueId: selectedIssue.id.slice(0, 4),
            role: activeRoleLabel,
          })
        : t("workspace.console.noActiveTaskBanner", {
            issueId: selectedIssue?.id.slice(0, 4) ?? "—",
          });
  const placeholder =
    mode === "create"
      ? t("workspace.console.commandPlaceholder")
      : t("workspace.console.chatPlaceholder");
  const submitLabel =
    mode === "create"
      ? t("workspace.console.runIssue")
      : t("workspace.console.chatSend");
  const isSubmitDisabled =
    isCreating
    || !command.trim()
    || (mode === "chat" && !activeTask);

  return (
    <div className="flex-1 min-w-0 flex flex-col border-r border-border-subtle">
      {/* Header */}
      <div className="px-6 py-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-text-muted">
            {workspace?.title ?? t("workspace.console.titleFallback")}
            {issues[0]?.current_phase && (
              <>
                {" · "}
                {issues[0].current_phase}
              </>
            )}
          </div>
          <h1 className="text-xl font-bold tracking-tight mt-1 truncate">
            {issues[0]?.title ?? t("workspace.console.emptyTitle")}
          </h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" className="gap-1">
            <Filter size={12} /> {t("workspace.console.filter")}
          </Button>
          <Button variant="outline" size="sm" className="gap-1">
            <ArrowDownUp size={12} /> {t("workspace.console.sort")}
          </Button>
          <Button
            size="sm"
            onClick={onNewIssue}
            className="gap-1 bg-brand hover:bg-brand-strong text-black font-semibold"
          >
            <Plus size={12} /> {t("workspace.console.newIssue")}
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <div className="px-6">
          <div className="grid grid-cols-[1fr_140px_180px_120px_60px] gap-4 py-2 text-[10px] uppercase tracking-wider text-text-muted border-b border-border-subtle">
            <div>{t("workspace.console.table.task")}</div>
            <div>{t("workspace.console.table.status")}</div>
            <div>{t("workspace.console.table.branch")}</div>
            <div>{t("workspace.console.table.agent")}</div>
            <div className="text-right">{t("workspace.console.table.run")}</div>
          </div>
          {isLoading && (
            <div className="px-3 py-10 text-center text-text-muted text-sm">{t("workspace.console.loading")}</div>
          )}
          {!isLoading && issues.length === 0 && (
            <div className="px-3 py-10 text-center text-text-muted text-sm">
              {t("workspace.console.emptyBody")}
            </div>
          )}
          {issues.map((issue) => (
            <IssueRow
              key={issue.id}
              issue={issue}
              project={project}
              selected={issue.id === selectedId}
              onSelect={() => onSelect(issue.id)}
              onOpen={() => onOpen(issue.id)}
              onDelete={() => onDelete(issue.id)}
            />
          ))}
        </div>
      </div>

      {/* Bottom command input */}
      <div className="px-6 py-4 border-t border-border-subtle">
        <div className="rounded-md border border-border-subtle bg-surface-input">
          <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-text-muted border-b border-border-subtle">
            <span className="truncate">{bannerText}</span>
          </div>
          <textarea
            ref={composerRef}
            value={command}
            onChange={(e) => onCommandChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmitCommand();
              }
            }}
            placeholder={placeholder}
            rows={2}
            className="w-full bg-transparent border-none outline-none resize-none px-3 py-2 text-sm placeholder:text-text-muted"
          />
          <div className="flex items-center justify-between px-3 py-2 border-t border-border-subtle text-[11px] text-text-muted">
            <span>
              <kbd className="px-1.5 py-0.5 rounded bg-surface-raised border border-border-subtle font-mono text-[10px]">↵</kbd>{" "}
              {t("workspace.console.send")} ·{" "}
              <kbd className="px-1.5 py-0.5 rounded bg-surface-raised border border-border-subtle font-mono text-[10px]">⇧↵</kbd>{" "}
              {t("workspace.console.newline")}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm">{t("workspace.console.mention")}</Button>
              <Button
                size="sm"
                onClick={onSubmitCommand}
                disabled={isSubmitDisabled}
                className="bg-brand hover:bg-brand-strong text-black font-semibold"
              >
                {submitLabel}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function IssueRow({
  issue,
  project,
  selected,
  onSelect,
  onOpen,
  onDelete,
}: {
  issue: CodexIssue;
  project: Project | null;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const kind = inferStatusKind(issue.status);
  const label =
    issue.status === "in_progress" ? t("workspace.console.status.running")
    : issue.status === "completed" ? t("workspace.console.status.done")
    : issue.status === "failed" ? t("workspace.console.status.failed")
    : issue.status === "awaiting_approval" ? t("workspace.console.status.awaitingApproval")
    : issue.status === "open" ? t("workspace.console.status.queued")
    : issue.status || t("workspace.console.status.queued");

  return (
    <div
      className={cn(
        "group w-full grid grid-cols-[1fr_140px_180px_120px_60px] gap-4 py-2.5 px-1 -mx-1 rounded items-center text-sm transition-colors",
        selected ? "bg-brand/[0.08] text-foreground" : "hover:bg-surface-hover",
      )}
    >
      <button type="button" onClick={onSelect} onDoubleClick={onOpen} className="min-w-0 flex items-center gap-2 text-left">
        <span
          className={cn(
            "size-1.5 rounded-full shrink-0",
            selected ? "bg-brand" : "bg-text-muted/40",
          )}
        />
        <span className="truncate">{issue.title}</span>
      </button>
      <div>
        <StatusBadge kind={kind} label={label} />
      </div>
      <div className="font-mono text-[12px] text-text-muted truncate flex items-center gap-1.5">
        <GitBranch size={11} />
        {issue.git_branch || project?.default_branch || "main"}
      </div>
      <div className="text-[12px] text-text-secondary flex items-center gap-1.5">
        <span className="size-4 rounded-sm bg-surface-raised border border-border-subtle inline-flex items-center justify-center text-[9px] font-bold text-brand">
          C
        </span>
        Codex
      </div>
      <div className="flex items-center justify-end gap-1">
        <span className="text-[11px] font-mono text-text-muted group-hover:hidden">
          {issue.updated_at ? relTime(issue.updated_at) : "—"}
        </span>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="hidden group-hover:flex items-center justify-center size-6 rounded hover:bg-red-500/10 hover:text-red-500 text-text-muted transition-colors"
          title="删除需求"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

function relTime(iso: string): string {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "—";
  const diff = Date.now() - timestamp;
  if (diff < 60_000) return "now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h`;
  return `${Math.floor(diff / 86_400_000)}d`;
}

// ============================================================================
// Right column — selected issue's run detail
// ============================================================================

type DetailTab = "logs" | "messages" | "result" | "artifacts" | "approvals";

function RunDetailColumn({ issue, project }: { issue: CodexIssue | null; project: Project | null }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<DetailTab>("logs");

  if (!issue) {
    return (
      <div className="w-[440px] shrink-0 flex items-center justify-center text-text-muted text-sm">
        {t("workspace.console.selectIssueHint")}
      </div>
    );
  }

  const kind = inferStatusKind(issue.status);
  const statusLabel =
    issue.status === "in_progress" ? t("workspace.console.status.running")
    : issue.status === "completed" ? t("workspace.console.status.done")
    : issue.status === "failed" ? t("workspace.console.status.failed")
    : issue.status === "awaiting_approval" ? t("workspace.console.status.awaitingApproval")
    : t("workspace.console.status.queued");

  return (
    <aside className="w-[440px] shrink-0 flex flex-col bg-background">
      {/* Header */}
      <div className="px-5 py-4 border-b border-border-subtle">
        <div className="flex items-center justify-between text-[11px] font-mono text-text-muted mb-2">
          <StatusBadge kind={kind} label={statusLabel} />
          <span className="truncate">
            run · {issue.id.slice(0, 4)} · pid {Math.floor(Math.random() * 90000) + 10000}
          </span>
        </div>
        <h2 className="text-base font-bold tracking-tight">{issue.title}</h2>
        <p className="text-[11px] text-text-muted mt-1">
          Codex agent · phase {issue.current_phase ?? "—"} · {project?.name ?? "—"}
        </p>
      </div>

      {/* Tabs */}
      <div className="px-5 border-b border-border-subtle flex items-center gap-4 text-[12px]">
        <TabButton active={tab === "logs"} onClick={() => setTab("logs")} label={t("console.logs")} />
        <TabButton active={tab === "messages"} onClick={() => setTab("messages")} label={t("console.messages")} />
        <TabButton active={tab === "result"} onClick={() => setTab("result")} label={t("console.result")} />
        <TabButton active={tab === "artifacts"} onClick={() => setTab("artifacts")} label={t("console.artifacts")} />
        <TabButton active={tab === "approvals"} onClick={() => setTab("approvals")} label={t("console.approvals")} count={1} />
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-auto px-5 py-3">
        {tab === "logs" && <LogPanelDemo issue={issue} />}
        {tab !== "logs" && (
          <div className="text-text-muted text-xs italic py-8 text-center">
            {t("workspace.console.runViewHint", { tab })}
          </div>
        )}
      </div>

      {/* Approval card pinned to bottom when relevant */}
      {issue.status === "awaiting_approval" && (
        <div className="px-5 pb-5">
          <ApprovalCard
            meta="step ?/?"
            body={
              <span>
                {t("workspace.console.awaitingApproval")}
              </span>
            }
          />
        </div>
      )}
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "py-2.5 -mb-px border-b-2 transition-colors flex items-center gap-1.5",
        active
          ? "border-foreground text-foreground font-medium"
          : "border-transparent text-text-muted hover:text-foreground",
      )}
    >
      {label}
      {count !== undefined && (
        <span
          className={cn(
            "text-[10px] px-1 rounded",
            active ? "bg-brand text-black" : "bg-surface-raised text-text-muted",
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}

/**
 * Placeholder log feed. Real WebSocket wiring lives in IssueDetailPage tabs.
 * Here we just show enough to convey the visual style.
 */
function LogPanelDemo({ issue }: { issue: CodexIssue }) {
  const phase = issue.current_phase ?? "planning";
  return (
    <div className="font-mono text-[12px]">
      <LogRow timestamp="00:00.0" kind="sys">
        codex exec --json --thread {issue.id.slice(0, 8)} &apos;{issue.title}&apos;
      </LogRow>
      <LogRow timestamp="00:00.2" kind="tool">
        {phase} · scan repository structure
      </LogRow>
      <LogRow timestamp="00:00.4" kind="out">
        <span className="text-text-secondary">Live logs stream from the issue&apos;s execution process —{" "}</span>
        <button
          type="button"
          onClick={() => {
            window.location.href = `/issues/${issue.id}?tab=tasks`;
          }}
          className="text-brand hover:underline"
        >
          open detail page
        </button>
      </LogRow>
      <LogRow timestamp="00:00.5" kind="ok">
        ✓ ready
      </LogRow>
    </div>
  );
}
