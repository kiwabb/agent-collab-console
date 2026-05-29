"use client";

import { useMemo, useState } from "react";
import { parseUnifiedDiff, displayPath, type DiffFile, type DiffLine } from "@/lib/diffParser";
import { cn } from "@/lib/utils";

interface Props {
  diff: string;
}

/**
 * Two-column diff viewer mirroring the design handoff's diff-wrap:
 *   [ 300px file list  |  1fr unified diff view ]
 *
 * - Left: per-file row with path, +N/−M, and a 5-cell stat strip.
 * - Right: hunk headers + line-level grid (oldLn / newLn / marker / code)
 *   with add/rm tinting.
 */
export function DiffSplitView({ diff }: Props) {
  const files = useMemo(() => parseUnifiedDiff(diff), [diff]);
  const [activeIdx, setActiveIdx] = useState(0);
  const active = files[activeIdx] ?? null;

  if (files.length === 0) {
    return (
      <div className="p-4 text-sm text-text-muted">No file changes.</div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)] grid-rows-[160px_minmax(0,1fr)] md:grid-rows-1 flex-1 min-h-0 border-t border-border-subtle">
      <div className="border-b md:border-b-0 md:border-r border-border-subtle overflow-y-auto py-1.5 bg-surface">
        {files.map((f, i) => (
          <FileRow
            key={f.header + i}
            file={f}
            active={i === activeIdx}
            onClick={() => setActiveIdx(i)}
          />
        ))}
      </div>
      <div className="flex flex-col min-w-0 min-h-0 bg-[#0a0a0b]">
        <DiffHead file={active} />
        <DiffCode lines={active?.lines ?? []} />
      </div>
    </div>
  );
}

function FileRow({
  file,
  active,
  onClick,
}: {
  file: DiffFile;
  active: boolean;
  onClick: () => void;
}) {
  const path = displayPath(file);
  const { dir, base } = splitPath(path);
  const total = file.additions + file.deletions;
  // 5-slot mini stat-bar (a/r/n) matching the design handoff
  const addCells = total > 0 ? Math.round((file.additions / total) * 5) : 0;
  const rmCells = total > 0 ? 5 - addCells : 0;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3.5 py-2 text-left border-l-2 transition-colors hover:bg-surface-hover",
        active ? "bg-surface-hover border-brand" : "border-transparent",
      )}
    >
      <div className="font-mono text-[11.5px] text-text-secondary truncate min-w-0 leading-tight">
        {dir && <span className="text-text-faint">{dir}/</span>}
        <span>{base}</span>
        {file.isNew && (
          <span
            className="ml-1.5 inline-block text-[9px] uppercase tracking-wider px-1 rounded align-[1px]"
            style={{
              color: "var(--color-status-done)",
              background: "var(--color-done-bg)",
              border: "1px solid var(--color-done-ring)",
            }}
          >
            new
          </span>
        )}
      </div>
      <div className="font-mono text-[10.5px] flex items-center gap-1.5 whitespace-nowrap">
        {file.additions > 0 && (
          <span style={{ color: "var(--color-status-done)" }}>
            +{file.additions}
          </span>
        )}
        {file.deletions > 0 && (
          <span style={{ color: "var(--color-status-failed)" }}>
            −{file.deletions}
          </span>
        )}
        <span className="inline-flex gap-px ml-1">
          {Array.from({ length: 5 }, (_, i) => (
            <i
              key={i}
              className="inline-block size-1.5 rounded-[1px]"
              style={{
                background:
                  i < addCells
                    ? "var(--color-status-done)"
                    : i < addCells + rmCells
                      ? "var(--color-status-failed)"
                      : "var(--color-border-muted)",
              }}
            />
          ))}
        </span>
      </div>
    </button>
  );
}

function DiffHead({ file }: { file: DiffFile | null }) {
  if (!file) return null;
  const path = displayPath(file);
  const { dir, base } = splitPath(path);
  return (
    <div className="flex items-center justify-between gap-2.5 px-4 py-2.5 border-b border-border-subtle bg-surface">
      <div className="font-mono text-[12.5px] text-foreground truncate">
        {dir && <span className="text-text-faint">{dir}/</span>}
        {base}
      </div>
      <div className="font-mono text-[11px] text-text-muted whitespace-nowrap">
        <span style={{ color: "var(--color-status-done)" }}>
          +{file.additions}
        </span>{" "}
        <span style={{ color: "var(--color-status-failed)" }}>
          −{file.deletions}
        </span>{" "}
        · viewing <span className="text-text-secondary">unified</span>
      </div>
    </div>
  );
}

function DiffCode({ lines }: { lines: DiffLine[] }) {
  if (lines.length === 0) {
    return (
      <div className="flex-1 grid place-items-center text-[12px] text-text-muted">
        Pick a file on the left to view its diff.
      </div>
    );
  }
  return (
    <div className="flex-1 overflow-auto py-1.5 font-mono text-[12px] leading-relaxed">
      {lines.map((line, i) => {
        if (line.type === "hunk") {
          return (
            <div
              key={i}
              className="px-4 py-1 my-1.5 font-mono text-[11px]"
              style={{
                background: "var(--color-info-bg)",
                color: "var(--color-status-info)",
                borderTop: "1px solid var(--color-border-subtle)",
                borderBottom: "1px solid var(--color-border-subtle)",
              }}
            >
              {line.text}
            </div>
          );
        }
        const tone =
          line.type === "add"
            ? "bg-status-done/[0.06] text-status-done"
            : line.type === "del"
              ? "bg-status-failed/[0.05] text-status-failed"
              : line.type === "meta"
                ? "text-text-faint"
                : "text-text-secondary";
        return (
          <div
            key={i}
            className={cn(
              "grid grid-cols-[40px_40px_18px_minmax(0,1fr)] gap-0 px-2 items-center",
              tone,
            )}
          >
            <span className="text-text-faint text-right pr-2 select-none text-[11px]">
              {line.oldLine ?? ""}
            </span>
            <span className="text-text-faint text-right pr-2 select-none text-[11px]">
              {line.newLine ?? ""}
            </span>
            <span className="text-center text-text-faint select-none">
              {line.type === "add" ? "+" : line.type === "del" ? "−" : ""}
            </span>
            <span className="whitespace-pre overflow-x-auto">{line.text}</span>
          </div>
        );
      })}
    </div>
  );
}

function splitPath(path: string): { dir: string; base: string } {
  const i = path.lastIndexOf("/");
  if (i < 0) return { dir: "", base: path };
  return { dir: path.slice(0, i), base: path.slice(i + 1) };
}
