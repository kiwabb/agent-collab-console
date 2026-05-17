"use client";

import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X, Loader2 } from "lucide-react";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import {
  createAgent,
  deleteAgent,
  listAgents,
  updateAgent,
} from "@/lib/api";
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "@/lib/types";
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
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

/**
 * Agent library — CRUD UI for the agents table. Built-in agents
 * (PM/Architect/Engineer/QA) are seeded by the backend and cannot be
 * deleted; their prompt template is also intentionally read-only since
 * they have framework hooks tied to role_key.
 *
 * Adding a custom agent (e.g. SecurityReviewer / DBA / DocWriter)
 * registers a new role_key that workflow templates and the orchestrator
 * can reference.
 */
export function AgentLibraryPage() {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Agent | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const rows = await listAgents();
      setAgents(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) return;
    setBusy(true);
    try {
      await deleteAgent(confirmDelete.id);
      addToast({ type: "success", title: "Agent deleted" });
      setConfirmDelete(null);
      await reload();
    } catch (err) {
      addToast({
        type: "error",
        title: "Delete failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }, [confirmDelete, addToast, reload]);

  return (
    <WorkbenchShell breadcrumbs={[{ label: t("agents.pageTitle") }]}>
      <div className="px-8 py-6 max-w-[1280px] mx-auto space-y-4">
        <div className="flex items-end justify-between gap-3 border-b border-border-subtle pb-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("agents.pageTitle")}</h1>
            <p className="text-[12px] text-text-muted mt-1">
              {t("agents.pageSubtitle")}
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
            className="gap-1 bg-brand hover:bg-brand-strong text-black font-semibold"
          >
            <Plus size={14} /> New agent
          </Button>
        </div>

        {loading && <div className="text-sm text-text-muted">Loading…</div>}
        {error && (
          <div className="rounded-md border border-error/40 bg-error/10 text-error text-sm p-3">
            {error}
          </div>
        )}

        {!loading && !error && (
          <ul className="rounded-xl border border-border-subtle bg-surface-raised divide-y divide-border-subtle overflow-hidden">
            {agents.length === 0 && (
              <li className="py-10 text-center text-sm text-text-muted">
                No agents yet — built-in roles will be seeded on backend startup.
              </li>
            )}
            {agents.map((a) => (
              <li
                key={a.id}
                className="grid grid-cols-[1fr_120px_160px_160px_90px] gap-3 px-4 py-3 items-center group hover:bg-surface-hover transition-colors"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold truncate">{a.name}</span>
                    {a.is_builtin && (
                      <span className="text-[9px] uppercase tracking-wider bg-brand/15 text-brand rounded px-1 py-0.5">
                        built-in
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-text-muted truncate font-mono">
                    {a.role_key}
                  </div>
                </div>
                <div className="text-[11px] text-text-muted truncate font-mono">
                  {a.default_executor ?? "—"}
                </div>
                <div className="text-[11px] text-text-muted truncate">
                  {a.artifact_subdir ?? "—"}
                </div>
                <div className="text-[11px] text-text-muted flex flex-col gap-0.5">
                  <span>{a.triggers_replan_on_done ? "✓ replan-done" : ""}</span>
                  <span>{a.triggers_replan_on_fail ? "✓ replan-fail" : ""}</span>
                </div>
                <div className="flex items-center gap-1 justify-end">
                  <button
                    type="button"
                    aria-label="Edit"
                    onClick={() => {
                      setEditing(a);
                      setEditorOpen(true);
                    }}
                    className="size-7 rounded-md hover:bg-surface-input text-text-muted hover:text-foreground flex items-center justify-center transition-colors"
                  >
                    <Pencil size={13} />
                  </button>
                  {!a.is_builtin && (
                    <button
                      type="button"
                      aria-label="Delete"
                      onClick={() => setConfirmDelete(a)}
                      className="size-7 rounded-md hover:bg-status-failed/10 text-text-muted hover:text-status-failed flex items-center justify-center transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <AgentEditorDialog
          open={editorOpen}
          onClose={() => setEditorOpen(false)}
          editing={editing}
          onSaved={() => {
            setEditorOpen(false);
            void reload();
          }}
        />

        <ConfirmDialog
          open={confirmDelete !== null}
          onOpenChange={(o) => !o && setConfirmDelete(null)}
          title="Delete agent?"
          description={
            confirmDelete
              ? `"${confirmDelete.name}" will be removed. Issues that reference it via DAG node will fall back to the heuristic.`
              : ""
          }
          confirmText="Delete"
          variant="destructive"
          isLoading={busy}
          onConfirm={() => void handleDelete()}
        />
      </div>
    </WorkbenchShell>
  );
}

interface AgentEditorDialogProps {
  open: boolean;
  onClose: () => void;
  editing: Agent | null;
  onSaved: () => void;
}

function AgentEditorDialog({ open, onClose, editing, onSaved }: AgentEditorDialogProps) {
  const { addToast } = useToast();
  const [name, setName] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [description, setDescription] = useState("");
  const [systemPromptTemplate, setSystemPromptTemplate] = useState("");
  const [defaultExecutor, setDefaultExecutor] = useState<string>("claude");
  const [artifactSubdir, setArtifactSubdir] = useState("");
  const [replanOnDone, setReplanOnDone] = useState(false);
  const [replanOnFail, setReplanOnFail] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? "");
    setRoleKey(editing?.role_key ?? "");
    setDescription(editing?.description ?? "");
    setSystemPromptTemplate(editing?.system_prompt_template ?? "");
    setDefaultExecutor(editing?.default_executor ?? "claude");
    setArtifactSubdir(editing?.artifact_subdir ?? "");
    setReplanOnDone(editing?.triggers_replan_on_done ?? false);
    setReplanOnFail(editing?.triggers_replan_on_fail ?? false);
    setSaving(false);
  }, [open, editing]);

  const isBuiltin = editing?.is_builtin ?? false;
  const canSubmit = name.trim().length > 0 && roleKey.trim().length > 0 && systemPromptTemplate.trim().length > 0;

  const handleSave = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      if (editing) {
        const patch: UpdateAgentRequest = {
          name: name.trim(),
          description: description.trim() || null,
          default_executor: defaultExecutor || null,
          artifact_subdir: artifactSubdir.trim() || null,
          triggers_replan_on_done: replanOnDone,
          triggers_replan_on_fail: replanOnFail,
        };
        // Don't try to overwrite a builtin's prompt template — backend
        // will reject and the framework relies on the `[builtin:...]`
        // placeholder being intact.
        if (!isBuiltin) patch.system_prompt_template = systemPromptTemplate;
        await updateAgent(editing.id, patch);
        addToast({ type: "success", title: "Agent updated" });
      } else {
        const payload: CreateAgentRequest = {
          name: name.trim(),
          role_key: roleKey.trim(),
          description: description.trim() || null,
          system_prompt_template: systemPromptTemplate,
          default_executor: defaultExecutor || null,
          artifact_subdir: artifactSubdir.trim() || null,
          triggers_replan_on_done: replanOnDone,
          triggers_replan_on_fail: replanOnFail,
        };
        await createAgent(payload);
        addToast({ type: "success", title: "Agent created" });
      }
      onSaved();
    } catch (err) {
      addToast({
        type: "error",
        title: editing ? "Update failed" : "Create failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-auto">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit agent" : "New agent"}</DialogTitle>
          <DialogDescription>
            {isBuiltin
              ? "This is a built-in agent. Only the surface fields can be edited; the system prompt template is owned by the framework."
              : "Custom roles get their own slot in the agents registry. Reference them via workflow templates or have the orchestrator suggest them."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Security Reviewer"
                autoFocus
                className="bg-surface-input border-border-subtle"
              />
            </Field>
            <Field label="role_key" hint={editing ? "Immutable after creation" : "Lowercase snake_case identifier"}>
              <Input
                value={roleKey}
                onChange={(e) => setRoleKey(e.target.value.replace(/[^a-z0-9_]/g, "").toLowerCase())}
                placeholder="security_reviewer"
                disabled={!!editing}
                className="bg-surface-input border-border-subtle font-mono text-[12px]"
              />
            </Field>
          </div>
          <Field label="Description">
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="One-line summary shown in the agent library"
              className="bg-surface-input border-border-subtle"
            />
          </Field>
          <Field
            label="System prompt template"
            hint={
              isBuiltin
                ? "Read-only — built-in template references framework hooks."
                : "Plain text. The framework substitutes {issue_title}, {issue_description}, {role_key}, {node_key} at dispatch time."
            }
          >
            <textarea
              value={systemPromptTemplate}
              onChange={(e) => setSystemPromptTemplate(e.target.value)}
              rows={10}
              disabled={isBuiltin}
              placeholder="You are acting as Security Reviewer. Inspect the engineer report and flag…"
              className={cn(
                "w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-[12px] font-mono",
                "focus:outline-none focus:ring-2 focus:ring-brand/50",
                isBuiltin && "opacity-60",
              )}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Default executor">
              <select
                value={defaultExecutor}
                onChange={(e) => setDefaultExecutor(e.target.value)}
                className="w-full h-9 rounded-md border border-border-subtle bg-surface-input px-2 text-[12px]"
              >
                <option value="claude">claude</option>
                <option value="codex">codex</option>
              </select>
            </Field>
            <Field label="Artifact subdir" hint="Where this role's outputs land in issue/<id>/<subdir>/">
              <Input
                value={artifactSubdir}
                onChange={(e) => setArtifactSubdir(e.target.value)}
                placeholder="security"
                className="bg-surface-input border-border-subtle font-mono text-[12px]"
              />
            </Field>
          </div>
          <div className="flex gap-4 pt-1">
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input
                type="checkbox"
                checked={replanOnDone}
                onChange={(e) => setReplanOnDone(e.target.checked)}
              />
              Trigger replan on done
            </label>
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input
                type="checkbox"
                checked={replanOnFail}
                onChange={(e) => setReplanOnFail(e.target.checked)}
              />
              Trigger replan on fail
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            <X size={12} className="mr-1" /> Cancel
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={!canSubmit || saving}
            className="bg-brand hover:bg-brand-strong text-black font-semibold"
          >
            {saving ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> Saving…
              </span>
            ) : editing ? "Save changes" : "Create agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider text-text-muted">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <p className="text-[10px] text-text-muted mt-1 leading-snug">{hint}</p>}
    </label>
  );
}
