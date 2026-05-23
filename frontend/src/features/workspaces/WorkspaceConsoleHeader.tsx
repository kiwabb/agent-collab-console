"use client";

import { ArrowDownUp, Filter, Plus, RadioTower } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { CodexIssue, Project, Workspace } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";
import { formatWorkspaceConsoleRepoLabel } from "./workspaceConsoleState";
import { getIssueStatusBucket } from "./IssueRow";

export type IssueStatusFilter = "all" | "running" | "awaiting" | "queued" | "done" | "failed";
export type IssueSortMode = "updated" | "status" | "phase";

interface Props {
  workspace: Workspace | null;
  project: Project | null;
  issues: CodexIssue[];
  statusFilter: IssueStatusFilter;
  sortMode: IssueSortMode;
  onStatusFilterChange: (filter: IssueStatusFilter) => void;
  onSortModeChange: (mode: IssueSortMode) => void;
  onNewIssue: () => void;
}

const FILTERS: IssueStatusFilter[] = ["all", "running", "awaiting", "queued", "done", "failed"];
const SORTS: IssueSortMode[] = ["updated", "status", "phase"];

export function WorkspaceConsoleHeader({
  workspace,
  project,
  issues,
  statusFilter,
  sortMode,
  onStatusFilterChange,
  onSortModeChange,
  onNewIssue,
}: Props) {
  const { t } = useI18n();
  const counts = issues.reduce(
    (acc, issue) => {
      acc.total += 1;
      acc[getIssueStatusBucket(issue.status)] += 1;
      return acc;
    },
    { total: 0, running: 0, awaiting: 0, queued: 0, done: 0, failed: 0 },
  );
  const repoLabel = formatWorkspaceConsoleRepoLabel(project?.repo_path);

  return (
    <section className="rounded-[1.4rem] border border-border-subtle bg-surface/82 p-4 shadow-[0_24px_80px_rgba(2,6,23,0.12)] backdrop-blur md:p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-text-muted">
            <span className="inline-flex items-center gap-2">
              <RadioTower size={13} className="text-brand" />
              {t("workspace.console.titleFallback")}
            </span>
            <span className="text-border-strong">/</span>
            <span className="truncate">{repoLabel}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-3">
            <h1 className="text-2xl font-black tracking-[-0.04em] text-foreground md:text-3xl">
              {workspace?.title ?? t("workspace.console.emptyTitle")}
            </h1>
            <p className="pb-1 text-sm text-text-muted">
              {counts.running} running · {counts.awaiting} awaiting · {counts.total} total
            </p>
          </div>
        </div>
        <Button
          size="sm"
          onClick={onNewIssue}
          className="h-10 gap-2 rounded-full bg-brand px-5 font-bold text-black shadow-[0_12px_30px_rgba(34,211,238,0.22)] hover:bg-brand-strong"
        >
          <Plus size={15} /> {t("workspace.console.newIssue")}
        </Button>
      </div>

      <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-muted">
            <Filter size={12} /> {t("workspace.console.filter")}
          </span>
          {FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => onStatusFilterChange(filter)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === filter
                  ? "border-brand bg-brand/15 text-foreground"
                  : "border-border-subtle bg-surface-raised/70 text-text-muted hover:text-foreground",
              )}
            >
              {t(`workspace.console.filter.${filter}`)} · {filter === "all" ? counts.total : counts[filter]}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-muted">
            <ArrowDownUp size={12} /> {t("workspace.console.sort")}
          </span>
          {SORTS.map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onSortModeChange(mode)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-semibold capitalize transition-colors",
                sortMode === mode
                  ? "border-foreground bg-foreground text-background"
                  : "border-border-subtle bg-surface-raised/70 text-text-muted hover:text-foreground",
              )}
            >
              {t(`workspace.console.sort.${mode}`)}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
