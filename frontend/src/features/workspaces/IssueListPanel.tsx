"use client";

import { Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
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
}

export function IssueListPanel({
  issues,
  allIssueCount,
  tasks,
  project,
  isLoading,
  onOpenIssue,
  onClearFilter,
}: Props) {
  const { t } = useI18n();
  const tasksByIssue = new Map<string, CodexTask[]>();
  for (const task of tasks) {
    if (!task.issue_id) continue;
    const bucket = tasksByIssue.get(task.issue_id) ?? [];
    bucket.push(task);
    tasksByIssue.set(task.issue_id, bucket);
  }

  return (
    <section className="min-h-0 flex-1 overflow-hidden rounded-[1.4rem] border border-border-subtle bg-surface/88 shadow-[0_24px_80px_rgba(2,6,23,0.10)] backdrop-blur">
      <div className="grid grid-cols-[minmax(0,1fr)_150px_180px_92px] gap-4 border-b border-border-subtle px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-text-muted max-lg:hidden">
        <div>{t("workspace.console.table.task")}</div>
        <div>{t("workspace.console.table.status")}</div>
        <div>{t("workspace.console.table.agent")}</div>
        <div className="text-right">{t("workspace.console.table.run")}</div>
      </div>

      <div className="h-full min-h-0 overflow-auto p-3">
        {isLoading && (
          <div className="flex h-48 items-center justify-center text-sm text-text-muted">
            {t("workspace.console.loading")}
          </div>
        )}

        {!isLoading && issues.length === 0 && (
          <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 text-center">
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
          <div className="space-y-2">
            {issues.map((issue) => (
              <IssueRow
                key={issue.id}
                issue={issue}
                tasks={tasksByIssue.get(issue.id) ?? []}
                project={project}
                onOpen={() => onOpenIssue(issue.id)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
