"use client";

import { useEffect, useMemo, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { createIssueAndInitialTask } from "@/features/workbench/workbenchActions";
import { autoStartIssueGraph, createCodexIssue } from "@/lib/api";
import type { CodexIssue, Project, RuntimeCatalog } from "@/lib/types";
import { formatWorkspaceConsoleRepoLabel } from "./workspaceConsoleState";

interface Props {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  workspaceId: string;
  project: Project | null;
  catalog: RuntimeCatalog | null;
  onCreated: (issue: CodexIssue) => void;
}

export function NewIssueDialog({ open, onOpenChange, workspaceId, project, catalog, onCreated }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [executor, setExecutor] = useState("codex");
  const [model, setModel] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const enabledExecutors = useMemo(
    () => (catalog?.executors ?? []).filter((entry) => entry.enabled),
    [catalog],
  );
  const selectedExecutor = useMemo(
    () => enabledExecutors.find((entry) => entry.id === executor) ?? enabledExecutors[0] ?? null,
    [enabledExecutors, executor],
  );
  const modelOptions = useMemo(() => {
    if (!selectedExecutor) return [] as string[];
    const seen = new Set<string>();
    const options: string[] = [];
    const push = (value: string | null | undefined) => {
      if (!value || seen.has(value)) return;
      seen.add(value);
      options.push(value);
    };
    push(selectedExecutor.default_model);
    for (const provider of selectedExecutor.providers ?? []) {
      if (!provider.enabled) continue;
      push(provider.default_model_id);
      for (const item of provider.models ?? []) {
        if (item.enabled) push(item.id);
      }
    }
    return options;
  }, [selectedExecutor]);

  const defaultModel = selectedExecutor?.default_model ?? modelOptions[0] ?? null;
  const repoLabel = formatWorkspaceConsoleRepoLabel(project?.repo_path);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    const fallbackExecutor = enabledExecutors[0]?.id ?? "codex";
    const fallbackModel = enabledExecutors[0]?.default_model ?? null;
    setExecutor(fallbackExecutor);
    setModel(fallbackModel);
    setSubmitting(false);
  }, [open, enabledExecutors]);

  useEffect(() => {
    if (!open) return;
    if (!selectedExecutor) return;
    if (!model || !modelOptions.includes(model)) {
      setModel(defaultModel);
    }
  }, [open, selectedExecutor, model, modelOptions, defaultModel]);

  const canSubmit = title.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const { issue } = await createIssueAndInitialTask({
        workspaceId,
        title: title.trim(),
        description: description.trim(),
        executor,
        issueTitle: title.trim(),
        createCodexIssue,
        autoStartIssueGraph,
        model,
      });
      onCreated(issue);
      onOpenChange(false);
      addToast({ type: "success", title: t("issue.toast.created") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("issue.toast.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("workspace.console.newIssue")}</DialogTitle>
          <DialogDescription>
            {t("workspace.console.newIssueDesc")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-border-subtle bg-surface-input/40 px-4 py-3 text-[12px] text-text-secondary leading-relaxed">
            {t("workspace.console.planFirstNotice")}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-text-muted">
                {t("workspace.console.issueTitle")}
              </span>
              <Input
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t("workspace.console.issueTitlePlaceholder")}
                className="mt-1 bg-surface-input border-border-subtle"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-text-muted">
                {t("workspace.console.repo")}
              </span>
              <Input
                value={repoLabel}
                readOnly
                className="mt-1 bg-surface-input border-border-subtle font-mono text-[12px] text-text-muted"
              />
            </label>
          </div>

          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-text-muted">
              {t("workspace.console.issueDescription")}
            </span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              placeholder={t("workspace.console.issueDescriptionPlaceholder")}
              className="mt-1 w-full rounded-md border border-border-subtle bg-surface-input px-3 py-2 text-sm outline-none resize-y focus:ring-2 focus:ring-brand/50"
            />
          </label>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-text-muted">
                {t("workspace.console.executor")}
              </span>
              <select
                value={executor}
                onChange={(e) => setExecutor(e.target.value)}
                className="mt-1 w-full rounded-md border border-border-subtle bg-surface-input px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/50"
              >
                {(enabledExecutors.length > 0 ? enabledExecutors : [{ id: "codex", label: "Codex" } as const]).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-text-muted">
                {t("workspace.console.model")}
              </span>
              <select
                value={model ?? ""}
                onChange={(e) => setModel(e.target.value || null)}
                className="mt-1 w-full rounded-md border border-border-subtle bg-surface-input px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand/50"
              >
                {modelOptions.length === 0 ? (
                  <option value="">{t("workspace.console.modelFallback")}</option>
                ) : (
                  modelOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))
                )}
              </select>
            </label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("issue.cancel")}
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className="bg-brand hover:bg-brand-strong text-black font-semibold"
          >
            {submitting ? t("workspace.console.creating") : t("workspace.console.createAndStart")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
