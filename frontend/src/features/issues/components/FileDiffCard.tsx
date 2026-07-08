"use client";

import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Copy, Check, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/providers/I18nProvider";
import { type DiffFile, type DiffLine, displayPath } from "@/lib/diffParser";

interface Props {
  file: DiffFile;
  mode: "unified" | "split";
  defaultExpanded?: boolean;
  forcedExpanded?: boolean | null;
}

export function FileDiffCard({ file, mode, defaultExpanded = true, forcedExpanded = null }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);

  // Sync with parent's expand-all / collapse-all
  useEffect(() => {
    if (forcedExpanded !== null) setExpanded(forcedExpanded);
  }, [forcedExpanded]);

  const path = displayPath(file);

  async function copyPatch() {
    try {
      await navigator.clipboard.writeText(file.rawPatch);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="border-b border-border last:border-b-0">
      {/* Sticky header */}
      <div
        className="sticky top-0 z-10 flex items-center gap-2 px-3 py-2 bg-muted/80 backdrop-blur-sm cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="shrink-0 text-muted-foreground">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <FileText size={13} className="shrink-0 text-muted-foreground" />
        <span className="font-mono text-xs truncate flex-1">{path}</span>

        {file.isNew && (
          <Badge
            variant="outline"
            className="text-success border-success/50 text-[10px] px-1.5 py-0 shrink-0"
          >
            {t("task.diff.fileNew")}
          </Badge>
        )}
        {file.isDeleted && (
          <Badge
            variant="outline"
            className="text-error border-error/50 text-[10px] px-1.5 py-0 shrink-0"
          >
            {t("task.diff.fileDeleted")}
          </Badge>
        )}
        {file.isBinary && (
          <Badge
            variant="outline"
            className="text-muted-foreground text-[10px] px-1.5 py-0 shrink-0"
          >
            {t("task.diff.fileBinary")}
          </Badge>
        )}

        {(file.additions > 0 || file.deletions > 0) && (
          <span className="font-mono text-xs shrink-0">
            {file.additions > 0 && <span className="text-success">+{file.additions}</span>}
            {file.additions > 0 && file.deletions > 0 && " "}
            {file.deletions > 0 && <span className="text-error">−{file.deletions}</span>}
          </span>
        )}

        <Button
          size="sm"
          variant="ghost"
          className="h-5 w-5 p-0 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            copyPatch();
          }}
          title={t("task.diff.copyPatch")}
        >
          {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
        </Button>
      </div>

      {/* Diff body — horizontal scroll per-file, vertical scroll on parent */}
      {expanded && !file.isBinary && (
        <div className="overflow-x-auto w-full">
          {mode === "split" ? <SplitView lines={file.lines} /> : <UnifiedView lines={file.lines} />}
        </div>
      )}
    </div>
  );
}

/* ── Unified view ── */

function UnifiedView({ lines }: { lines: DiffLine[] }) {
  return (
    <table className="w-full border-collapse font-mono text-xs leading-5">
      <tbody>
        {lines.map((line, i) => (
          <UnifiedRow key={i} line={line} />
        ))}
      </tbody>
    </table>
  );
}

function UnifiedRow({ line }: { line: DiffLine }) {
  if (line.type === "hunk") {
    return (
      <tr className="bg-brand/5">
        <td className="w-10 text-right pr-2 pl-1 text-muted-foreground select-none" />
        <td className="w-10 text-right pr-2 text-muted-foreground select-none" />
        <td className="pl-2 text-brand/80 whitespace-pre-wrap break-all">{line.text}</td>
      </tr>
    );
  }
  if (line.type === "meta") {
    return (
      <tr className="bg-muted/30">
        <td className="w-10" colSpan={3} />
      </tr>
    );
  }

  const rowCls = line.type === "add" ? "bg-success/10" : line.type === "del" ? "bg-error/10" : "";
  const marker =
    line.type === "add" ? (
      <span className="text-success">+</span>
    ) : line.type === "del" ? (
      <span className="text-error">−</span>
    ) : (
      <span className="text-muted-foreground/50"> </span>
    );
  const textCls =
    line.type === "add"
      ? "text-success/90"
      : line.type === "del"
        ? "text-error/90"
        : "text-foreground/80";

  return (
    <tr className={rowCls}>
      <td className="w-10 text-right pr-2 pl-1 text-muted-foreground/60 select-none">
        {line.oldLine ?? ""}
      </td>
      <td className="w-10 text-right pr-2 text-muted-foreground/60 select-none">
        {line.newLine ?? ""}
      </td>
      <td className={`pl-1 whitespace-pre-wrap break-all ${textCls}`}>
        {marker}
        {line.text}
      </td>
    </tr>
  );
}

/* ── Split view ── */

type SplitRow =
  { kind: "hunk"; text: string } | { kind: "pair"; left: DiffLine | null; right: DiffLine | null };

function buildSplitRows(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line) break;
    if (line.type === "hunk" || line.type === "meta") {
      rows.push({ kind: "hunk", text: line.text });
      i++;
      continue;
    }
    if (line.type === "context") {
      rows.push({ kind: "pair", left: line, right: line });
      i++;
      continue;
    }

    const dels: DiffLine[] = [];
    const adds: DiffLine[] = [];
    while (i < lines.length) {
      const deletion = lines[i];
      if (!deletion || deletion.type !== "del") break;
      dels.push(deletion);
      i++;
    }
    while (i < lines.length) {
      const addition = lines[i];
      if (!addition || addition.type !== "add") break;
      adds.push(addition);
      i++;
    }

    const max = Math.max(dels.length, adds.length);
    for (let k = 0; k < max; k++) {
      rows.push({ kind: "pair", left: dels[k] ?? null, right: adds[k] ?? null });
    }
  }
  return rows;
}

function SplitView({ lines }: { lines: DiffLine[] }) {
  const rows = buildSplitRows(lines);
  return (
    <table className="w-full border-collapse font-mono text-xs leading-5">
      <tbody>
        {rows.map((row, i) => {
          if (row.kind === "hunk") {
            return (
              <tr key={i} className="bg-brand/5">
                <td className="w-10 select-none" />
                <td className="pl-2 text-brand/80 whitespace-pre-wrap break-all" colSpan={3}>
                  {row.text}
                </td>
              </tr>
            );
          }
          return (
            <tr key={i}>
              <SplitCell line={row.left} side="left" />
              <SplitCell line={row.right} side="right" />
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SplitCell({ line, side }: { line: DiffLine | null; side: "left" | "right" }) {
  if (!line) {
    return (
      <>
        <td className="w-10 bg-muted/30 select-none" />
        <td className="bg-muted/10 border-r border-border" />
      </>
    );
  }

  const isAdd = line.type === "add";
  const isDel = line.type === "del";
  const bgCls = isAdd ? "bg-success/10" : isDel ? "bg-error/10" : "";
  const textCls = isAdd ? "text-success/90" : isDel ? "text-error/90" : "text-foreground/80";
  const lineNum = side === "left" ? (line.oldLine ?? line.newLine) : (line.newLine ?? line.oldLine);
  const marker = isAdd ? (
    <span className="text-success">+</span>
  ) : isDel ? (
    <span className="text-error">−</span>
  ) : (
    <span className="text-muted-foreground/50"> </span>
  );

  return (
    <>
      <td className={`w-10 text-right pr-2 pl-1 text-muted-foreground/60 select-none ${bgCls}`}>
        {lineNum ?? ""}
      </td>
      <td
        className={`pl-1 whitespace-pre-wrap break-all border-r border-border ${bgCls} ${textCls}`}
      >
        {marker}
        {line.text}
      </td>
    </>
  );
}
