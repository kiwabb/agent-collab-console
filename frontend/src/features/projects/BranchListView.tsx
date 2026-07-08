"use client";

import { useI18n } from "@/providers/I18nProvider";
import { Badge } from "@/components/ui/badge";
import type { GitBranch } from "@/lib/types";

interface Props {
  branches: GitBranch[];
  defaultBranch: string;
}

export function BranchListView({ branches, defaultBranch }: Props) {
  const { t } = useI18n();
  if (branches.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("projects.noBranches")}</p>;
  }
  return (
    <ul className="space-y-1 max-h-[420px] overflow-auto">
      {branches.map((b) => (
        <li
          key={b.name}
          className="flex items-center justify-between gap-2 px-2 py-1.5 rounded hover:bg-muted/60 text-sm"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className={b.name === defaultBranch ? "font-medium font-mono" : "font-mono"}>{b.name}</span>
            {b.is_current && <Badge variant="default">{t("projects.branchCurrent")}</Badge>}
            {b.is_remote && <Badge variant="secondary">{t("projects.branchRemote")}</Badge>}
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatDate(b.last_commit_date)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
