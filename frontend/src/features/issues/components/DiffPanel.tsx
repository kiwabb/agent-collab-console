"use client";

import { useState, useMemo } from "react";
import { useI18n } from "@/providers/I18nProvider";
import { Button } from "@/components/ui/button";
import { parseUnifiedDiff, displayPath } from "@/lib/diffParser";
import { FileDiffCard } from "./FileDiffCard";
import type { DiffStat } from "@/lib/types";

const GENERATED_PATTERNS = [
  /\.tsbuildinfo$/,
  /package-lock\.json$/,
  /pnpm-lock\.yaml$/,
  /yarn\.lock$/,
  /bun\.lockb$/,
  /Cargo\.lock$/,
  /composer\.lock$/,
  /Gemfile\.lock$/,
  /poetry\.lock$/,
];

function isGenerated(path: string): boolean {
  return GENERATED_PATTERNS.some((re) => re.test(path));
}

function formatFileCount(count: number, t: (key: string, params?: Record<string, string | number>) => string): string {
  const key = count === 1 ? "task.diff.fileCountOne" : "task.diff.fileCount";
  return t(key).replace("{count}", String(count));
}

function shortDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString([], {
      year: undefined,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

interface Props {
  diff: string;
  baseBranch?: string | null;
  branch?: string | null;
  stat?: DiffStat | null;
  /** C3: when supplied, render an attribution banner above the file list
   * showing which agent + run produced these changes. Engineer is the
   * only role that touches code in this system, so a single banner is
   * accurate; per-file attribution would be misleading complexity. */
  attribution?: {
    agentName: string;
    runId?: string | null;
    timestamp?: string | null;
  } | null;
}

export function DiffPanel({ diff, baseBranch, branch, stat, attribution }: Props) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"unified" | "split">("unified");
  // null = each file decides for itself; true/false = force all
  const [forcedExpanded, setForcedExpanded] = useState<boolean | null>(null);
  const [showGenerated, setShowGenerated] = useState(false);

  const allFiles = useMemo(() => parseUnifiedDiff(diff), [diff]);
  const files = useMemo(
    () => showGenerated ? allFiles : allFiles.filter((f) => !isGenerated(displayPath(f))),
    [allFiles, showGenerated],
  );
  const hiddenCount = allFiles.length - files.length;

  const totalAdd = stat?.insertions ?? allFiles.reduce((s, f) => s + f.additions, 0);
  const totalDel = stat?.deletions ?? allFiles.reduce((s, f) => s + f.deletions, 0);

  if (!diff || !diff.trim() || allFiles.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">{t("task.diffEmpty")}</p>;
  }

  return (
    <div>
      {/* Sticky header — sticks to top of the parent scroll container */}
      <div className="sticky top-0 z-20 bg-background border-b border-border">
        {/* Branch context */}
        {(baseBranch || branch) && (
          <div className="px-3 py-1.5 text-xs text-muted-foreground font-mono border-b border-border bg-muted/20">
            {baseBranch && <span><span className="text-foreground/50">{t("task.base")}:</span> {baseBranch}</span>}
            {baseBranch && branch && <span className="mx-2 text-muted-foreground/40">→</span>}
            {branch && <span><span className="text-foreground/50">{t("task.branch")}:</span> {branch}</span>}
          </div>
        )}

        {/* Toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 flex-wrap text-xs">
          <span className="font-mono text-muted-foreground">
            {totalAdd > 0 && <span className="text-success">+{totalAdd}</span>}
            {totalAdd > 0 && totalDel > 0 && " "}
            {totalDel > 0 && <span className="text-error">−{totalDel}</span>}
            {(totalAdd > 0 || totalDel > 0) && " · "}
            {formatFileCount(files.length, t)}
            {hiddenCount > 0 && (
              <button
                className="ml-2 text-muted-foreground/60 underline hover:text-foreground"
                onClick={() => setShowGenerated((v) => !v)}
              >
                {showGenerated ? t("task.diff.hideGenerated").replace("{count}", String(hiddenCount)) : t("task.diff.showGenerated").replace("{count}", String(hiddenCount))}
              </button>
            )}
          </span>
          <div className="flex-1" />
          <div className="flex rounded-md border border-border overflow-hidden">
            <button
              className={`px-2 py-1 ${mode === "unified" ? "bg-primary text-primary-foreground" : "hover:bg-muted/50"}`}
              onClick={() => setMode("unified")}
            >
              {t("task.diff.viewUnified")}
            </button>
            <button
              className={`px-2 py-1 border-l border-border ${mode === "split" ? "bg-primary text-primary-foreground" : "hover:bg-muted/50"}`}
              onClick={() => setMode("split")}
            >
              {t("task.diff.viewSplit")}
            </button>
          </div>
          <Button size="sm" variant="ghost" className="h-6 px-2"
            onClick={() => setForcedExpanded(true)}>
            {t("task.diff.expandAll")}
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2"
            onClick={() => setForcedExpanded(false)}>
            {t("task.diff.collapseAll")}
          </Button>
        </div>
      </div>

      {/* C3: attribution banner — single source of truth, since only the
          Engineer role touches code in this system. */}
      {attribution && (
        <div className="px-3 py-2 text-[11px] text-muted-foreground bg-muted/10 border-b border-border flex items-center gap-2 flex-wrap">
          <span className="text-foreground/60">{t("task.diffMerge.changesBy")}</span>
          <span className="font-semibold text-foreground">{attribution.agentName}</span>
          {attribution.runId && (
            <>
              <span className="text-foreground/40">·</span>
              <span className="font-mono">{t("task.diffMerge.runLabel", { run: attribution.runId.slice(0, 8) })}</span>
            </>
          )}
          {attribution.timestamp && (
            <>
              <span className="text-foreground/40">·</span>
              <span className="tabular-nums">{shortDateTime(attribution.timestamp)}</span>
            </>
          )}
        </div>
      )}

      {/* File list — scrolled by parent container */}
      {files.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">{t("task.diffEmpty")}</p>
      ) : (
        files.map((file, i) => (
          <FileDiffCard
            key={file.header + i}
            file={file}
            mode={mode}
            defaultExpanded={file.lines.length <= 100}
            forcedExpanded={forcedExpanded}
          />
        ))
      )}
    </div>
  );
}
