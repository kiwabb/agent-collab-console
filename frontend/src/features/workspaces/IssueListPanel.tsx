"use client";

import { useState } from "react";
import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Loader } from "@/components/ui/loader";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { CodexIssue, CodexTask, Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { IssueRow } from "./IssueRow";

interface Props {
  issues: CodexIssue[];
  allIssueCount: number;
  tasks: CodexTask[];
  project: Project | null;
  isLoading: boolean;
  onOpenIssue: (issueId: string) => void;
  onClearFilter: () => void;
  onDelete?: (issueId: string) => Promise<void>;
}

export function IssueListPanel({
  issues,
  allIssueCount,
  tasks,
  project,
  isLoading,
  onOpenIssue,
  onClearFilter,
  onDelete,
}: Props) {
  const { t } = useI18n();
  const [deleteTarget, setDeleteTarget] = useState<CodexIssue | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const tasksByIssue = new Map<string, CodexTask[]>();
  for (const task of tasks) {
    if (!task.issue_id) continue;
    const bucket = tasksByIssue.get(task.issue_id) ?? [];
    bucket.push(task);
    tasksByIssue.set(task.issue_id, bucket);
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget || !onDelete) return;
    setIsDeleting(true);
    try {
      await onDelete(deleteTarget.id);
      setDeleteTarget(null);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section data-density="operations-queue" className="min-h-0 flex-1 overflow-hidden rounded-lg border border-border-subtle bg-surface/90">
      <div className="grid grid-cols-[minmax(0,1fr)_128px_156px_84px] gap-3 border-b border-border-subtle px-4 py-2.5 text-[10px] uppercase tracking-wider text-text-muted max-lg:hidden">
        <div>{t("workspace.console.table.task")}</div>
        <div>{t("workspace.console.table.status")}</div>
        <div>{t("workspace.console.table.agent")}</div>
        <div className="text-right">{t("workspace.console.table.run")}</div>
      </div>

      <div className="h-full min-h-0 overflow-auto">
        {isLoading && (
          <Loader variant="card" label={t("workspace.console.loading")} className="border-0 bg-transparent rounded-none h-48 min-h-0" />
        )}


        {!isLoading && issues.length === 0 && (
          <div className="m-3 flex h-64 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border-subtle bg-surface-input/40 px-6 text-center">
            <Inbox size={28} className="text-text-muted" />
            <div>
              <p className="font-semibold text-foreground">
                {allIssueCount === 0 ? t("workspace.console.emptyTitle") : t("workspace.console.emptyFilteredTitle")}
              </p>
              <p className="mt-1 text-sm text-text-muted">
                {allIssueCount === 0 ? t("workspace.console.emptyBody") : t("workspace.console.emptyFilteredBody")}
              </p>
            </div>
            {allIssueCount > 0 && (
              <Button variant="outline" size="sm" onClick={onClearFilter}>
                {t("workspace.console.clearFilter")}
              </Button>
            )}
          </div>
        )}

        {!isLoading && issues.length > 0 && (
          <div className="divide-y divide-border-subtle/70">
            {issues.map((issue) => (
              <IssueRow
                key={issue.id}
                issue={issue}
                tasks={tasksByIssue.get(issue.id) ?? []}
                project={project}
                onOpen={() => onOpenIssue(issue.id)}
                onDelete={onDelete ? () => setDeleteTarget(issue) : undefined}
              />
            ))}
          </div>
        )}
      </div>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("issue.delete")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-text-secondary">{t("issue.deleteConfirmBody")}</p>
          {deleteTarget && <p className="text-sm font-semibold text-foreground">{deleteTarget.title}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={isDeleting}>
              {t("issue.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDeleteConfirm()}
              disabled={isDeleting}
            >
              {isDeleting ? t("issue.deleting") : t("issue.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
