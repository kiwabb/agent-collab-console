"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
} from "lucide-react";

import {
  createWorkspace,
  deleteWorkspace,
  getCodexIssues,
  getProject,
  getWorkspaces,
  updateWorkspace,
} from "@/lib/api";
import type { CodexIssue, Project, Workspace } from "@/lib/types";
import { Button } from "@/components/ui/button";
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
import { cn } from "@/lib/utils";
import { emitDataEvent } from "@/lib/dataEvents";
import { workspaceLabel } from "@/lib/workspaceLabel";
import { useI18n } from "@/providers/I18nProvider";
import { ProjectShell } from "@/features/projects/ProjectShell";
import { Loader } from "@/components/ui/loader";

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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [proj, ws] = await Promise.all([
        getProject(projectId),
        getWorkspaces(projectId),
      ]);
      setProject(proj);
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
  }, [projectId, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter((w) =>
      (w.title || w.id).toLowerCase().includes(q) || (w.cwd || "").toLowerCase().includes(q),
    );
  }, [workspaces, query]);

  const totalIssues = useMemo(
    () => Object.values(issuesByWs).reduce((acc, list) => acc + list.length, 0),
    [issuesByWs],
  );
  const activeWorkspaces = useMemo(
    () =>
      workspaces.filter(
        (w) => w.status === "running" || w.status === "responding",
      ).length,
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
          <Kpi
            icon={<CheckCircle2 size={14} />}
            label={t("workspace.projectPage.kpiBranch")}
            valueText={project?.default_branch ?? "—"}
            tint="done"
            loading={loading}
          />
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
            onClick={() => setCreateOpen(true)}
            size="sm"
            className="gap-1 bg-brand hover:bg-brand-strong text-black font-semibold ml-auto"
          >
            <Plus size={14} /> {t("workspace.projectPage.new")}
          </Button>
        </div>

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
            <Loader variant="card" label={t("workspace.loading")} className="border-0 bg-transparent rounded-none min-h-[200px]" />
          ) :
 filtered.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-sm text-text-muted">
                {query
                  ? t("workspace.emptyFiltered")
                  : t("workspace.emptyCreatePrompt")}
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
          planFirstPm: editing?.settings.plan_first_pm ?? true,
        }}
        defaultCwdHint={project?.repo_path ?? ""}
        onSubmit={({ title, cwd, planFirstPm }) => {
          if (editing) return handleUpdate(editing.id, title, cwd, planFirstPm);
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
  return (
    <li className="grid grid-cols-[1fr_120px_90px_1.6fr_120px_70px] gap-3 px-4 py-3 items-center group hover:bg-surface-hover transition-colors">
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex items-center gap-2 text-left"
      >
        <span className="size-1.5 rounded-full bg-brand/70 shrink-0" />
        <span className="text-[13px] font-medium truncate group-hover:text-brand transition-colors">
          {workspaceLabel(ws)}
        </span>
        <ChevronRight
          size={12}
          className="text-text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
        />
      </button>
      <div>
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
          <DialogDescription>
            {t("workspace.dialog.description")}
          </DialogDescription>
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
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
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
            {saving ? t("workspace.saving") : (submitLabel || t("workspace.create"))}
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
  hint?: string;
  tone?: "muted" | "warning";
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-text-muted">
        {label}
      </span>
      <div className="mt-1">{children}</div>
      {hint && (
        <p className={cn(
          "mt-1 text-[11px]",
          tone === "warning" ? "text-status-awaiting" : "text-text-muted",
        )}>
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
    <div className="relative overflow-hidden rounded-xl border border-border-subtle bg-surface-raised p-3 hover:border-border-strong transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span
          className={cn(
            "size-7 rounded-md inline-flex items-center justify-center",
            t.iconBg,
          )}
        >
          {icon}
        </span>
        {pulse && (
          <span className="relative inline-flex">
            <span className={cn("size-1.5 rounded-full", t.dot)} />
            <span className={cn("absolute inset-0 rounded-full animate-ping opacity-60", t.dot)} />
          </span>
        )}
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
        <div className="text-2xl font-bold tabular-nums mt-0.5 truncate">
          {loading ? "—" : valueText ?? value ?? 0}
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
