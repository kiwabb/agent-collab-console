"use client";

import { useMemo, useState, useCallback } from "react";
import {
  Terminal,
  FileText,
  FilePlus,
  FileEdit,
  Search,
  Globe,
  ListChecks,
  Wrench,
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import type { NormalizedEntry, ToolCategory } from "@/lib/types";
import { cleanShellWrapper, getFileName, truncateText, asRecord } from "@/lib/toolConstants";

interface ToolBlockProps {
  entry: NormalizedEntry;
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      } catch {
        // ignore
      }
    },
    [text],
  );
  return (
    <button
      type="button"
      onClick={onCopy}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-widest text-text-muted hover:text-foreground hover:bg-surface-hover transition-colors"
      title={copied ? t("tools.copied") : t("tools.copy")}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />}
      <span>{copied ? t("tools.copied") : t("tools.copy")}</span>
    </button>
  );
}

function StatusDot({ status, isError }: { status?: "running" | "success" | "failed"; isError?: boolean }) {
  if (status === "failed" || isError) {
    return <span className="size-1.5 rounded-full bg-error shadow-[0_0_6px_rgba(239,68,68,0.6)]" />;
  }
  if (status === "success") {
    return <span className="size-1.5 rounded-full bg-success shadow-[0_0_6px_rgba(34,197,94,0.5)]" />;
  }
  return (
    <span className="size-1.5 rounded-full bg-brand animate-pulse shadow-[0_0_6px_rgba(122,157,204,0.7)]" />
  );
}

function StatusLabel({
  entry,
}: {
  entry: NormalizedEntry;
}) {
  const { t } = useI18n();
  const parts: string[] = [];
  if (entry.status === "running") parts.push(t("tools.runningEllipsis"));
  else if (entry.status === "failed") parts.push(t("tools.failed"));
  else parts.push(t("tools.completed"));
  if (typeof entry.exitCode === "number" && entry.exitCode !== 0) {
    parts.push(t("tools.exitCode", { code: String(entry.exitCode) }));
  }
  if (typeof entry.durationMs === "number") {
    parts.push(t("tools.duration", { ms: String(entry.durationMs) }));
  }
  return (
    <span
      className={cn(
        "text-[9px] font-black uppercase tracking-[0.16em]",
        entry.status === "failed" ? "text-error" : entry.status === "running" ? "text-brand" : "text-success",
      )}
    >
      {parts.join(" · ")}
    </span>
  );
}

function categoryIcon(category: ToolCategory | undefined, className: string) {
  const c = category || "other";
  if (c === "bash") return <Terminal size={13} className={className} />;
  if (c === "read") return <FileText size={13} className={className} />;
  if (c === "edit" || c === "fileChange") return <FileEdit size={13} className={className} />;
  if (c === "search") return <Search size={13} className={className} />;
  if (c === "web") return <Globe size={13} className={className} />;
  if (c === "todo") return <ListChecks size={13} className={className} />;
  if (c === "mcp") return <Wrench size={13} className={className} />;
  return <FilePlus size={13} className={className} />;
}

function ToolHeader({
  entry,
  title,
  summary,
  isOpen,
  onToggle,
  rightSlot,
}: {
  entry: NormalizedEntry;
  title: string;
  summary?: string;
  isOpen: boolean;
  onToggle: () => void;
  rightSlot?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2 text-left rounded-xl transition-colors",
        "hover:bg-surface-hover/60",
      )}
    >
      <span className="shrink-0 text-text-muted">
        {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </span>
      <span className="shrink-0 inline-flex items-center justify-center size-6 rounded-md bg-surface-raised border border-border-subtle">
        {categoryIcon(entry.category, "text-text-secondary")}
      </span>
      <span className="text-[10px] font-black uppercase tracking-[0.18em] text-text-secondary">{title}</span>
      {summary ? (
        <span
          className="flex-1 truncate text-[12px] font-mono text-foreground/80"
          title={summary}
        >
          {summary}
        </span>
      ) : (
        <span className="flex-1" />
      )}
      <span className="shrink-0 flex items-center gap-2">
        {rightSlot}
        <StatusLabel entry={entry} />
        <StatusDot status={entry.status} isError={entry.isError} />
      </span>
    </button>
  );
}

function preBlock(content: string) {
  return (
    <pre className="m-0 px-3 py-2 max-h-[320px] overflow-auto rounded-lg bg-background/60 border border-border-subtle font-mono text-[11.5px] leading-relaxed text-text-secondary whitespace-pre-wrap break-words">
      {content}
    </pre>
  );
}

function BashBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const command = useMemo(() => cleanShellWrapper(entry.command || ""), [entry.command]);
  const [open, setOpen] = useState(entry.status !== "success");
  const summary = command ? truncateText(command, 96) : t("tools.runCommand");
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.runCommand")}
        summary={summary}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {command && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">$</span>
                <CopyButton text={command} />
              </div>
              {preBlock(command)}
            </div>
          )}
          {entry.output && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">stdout</span>
                <CopyButton text={entry.output} />
              </div>
              {preBlock(entry.output)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReadBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const fileName = getFileName(entry.filePath || "");
  const summary = entry.filePath || fileName || "";
  const lineCount = useMemo(() => (entry.output ? entry.output.split(/\r?\n/).length : 0), [entry.output]);
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.readFile")}
        summary={truncateText(summary, 96)}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
        rightSlot={
          lineCount ? (
            <span className="text-[9px] font-mono text-text-muted">
              {t("tools.lines", { count: String(lineCount) })}
            </span>
          ) : undefined
        }
      />
      {open && entry.output && (
        <div className="px-3 pb-3 space-y-1">
          <div className="flex items-center justify-end">
            <CopyButton text={entry.output} />
          </div>
          {preBlock(entry.output)}
        </div>
      )}
    </div>
  );
}

function EditBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const fileName = getFileName(entry.filePath || "");
  const summary = entry.filePath || fileName || "";
  const args = entry.args || {};
  const oldStr = (args.old_string as string) || (args.oldString as string) || "";
  const newStr = (args.new_string as string) || (args.newString as string) || (args.content as string) || "";
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.editFile")}
        summary={truncateText(summary, 96)}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {oldStr && (
            <div>
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-error">- removed</span>
                <CopyButton text={oldStr} />
              </div>
              <pre className="m-0 px-3 py-2 max-h-[200px] overflow-auto rounded-lg bg-error/5 border border-error/20 font-mono text-[11.5px] leading-relaxed text-error/90 whitespace-pre-wrap break-words">
                {oldStr}
              </pre>
            </div>
          )}
          {newStr && (
            <div>
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-success">+ added</span>
                <CopyButton text={newStr} />
              </div>
              <pre className="m-0 px-3 py-2 max-h-[200px] overflow-auto rounded-lg bg-success/5 border border-success/20 font-mono text-[11.5px] leading-relaxed text-success/90 whitespace-pre-wrap break-words">
                {newStr}
              </pre>
            </div>
          )}
          {!oldStr && !newStr && entry.output && preBlock(entry.output)}
        </div>
      )}
    </div>
  );
}

function SearchBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const args = entry.args || {};
  const pattern = (args.pattern as string) || (args.query as string) || (args.regex as string) || "";
  const pathHint = (args.path as string) || (args.glob as string) || "";
  const summary = [pattern, pathHint].filter(Boolean).join("  in  ");
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.search")}
        summary={truncateText(summary, 96) || t("tools.search")}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && entry.output && (
        <div className="px-3 pb-3 space-y-1">
          <div className="flex items-center justify-end">
            <CopyButton text={entry.output} />
          </div>
          {preBlock(entry.output)}
        </div>
      )}
    </div>
  );
}

function TodoBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(true);
  const items = useMemo(() => {
    const args = entry.args || {};
    const raw = (args.todos as unknown) || (args.items as unknown) || (args.list as unknown);
    if (!Array.isArray(raw)) return [];
    return raw
      .map((it) => {
        const r = asRecord(it);
        if (!r) return null;
        return {
          content: (r.content as string) || (r.title as string) || (r.text as string) || "",
          status: String(r.status || r.state || "pending").toLowerCase(),
        };
      })
      .filter((it): it is { content: string; status: string } => !!it);
  }, [entry.args]);
  const summary = items.length ? `${items.filter((i) => i.status === "completed" || i.status === "done").length} / ${items.length}` : "";
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.todoList")}
        summary={summary}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && items.length > 0 && (
        <ul className="px-4 pb-3 pt-1 space-y-1.5">
          {items.map((it, i) => {
            const done = it.status === "completed" || it.status === "done";
            const inProgress = it.status === "in_progress" || it.status === "running";
            return (
              <li key={i} className="flex items-start gap-2 text-[12px] leading-relaxed">
                <span
                  className={cn(
                    "mt-1 size-3 shrink-0 rounded-sm border",
                    done
                      ? "bg-success/30 border-success"
                      : inProgress
                        ? "border-brand bg-brand/20"
                        : "border-border-strong",
                  )}
                >
                  {done && <Check size={9} className="text-success" />}
                </span>
                <span
                  className={cn(
                    "min-w-0 flex-1",
                    done ? "line-through text-text-muted" : "text-text-secondary",
                  )}
                >
                  {it.content || "—"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function McpBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const argsJson = useMemo(() => {
    const args = entry.args || {};
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return "";
    }
  }, [entry.args]);
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={t("tools.mcpCall")}
        summary={entry.toolName || ""}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {argsJson && argsJson !== "{}" && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">args</span>
                <CopyButton text={argsJson} />
              </div>
              {preBlock(argsJson)}
            </div>
          )}
          {entry.output && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">{t("tools.result")}</span>
                <CopyButton text={entry.output} />
              </div>
              {preBlock(entry.output)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function GenericBlock({ entry }: ToolBlockProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const argsJson = useMemo(() => {
    const args = entry.args || {};
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return "";
    }
  }, [entry.args]);
  const title = entry.toolName || t("tools.result");
  return (
    <div className="rounded-xl border border-border-subtle bg-surface/40">
      <ToolHeader
        entry={entry}
        title={title}
        summary={entry.filePath || entry.command || ""}
        isOpen={open}
        onToggle={() => setOpen((v) => !v)}
      />
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {argsJson && argsJson !== "{}" && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">args</span>
                <CopyButton text={argsJson} />
              </div>
              {preBlock(argsJson)}
            </div>
          )}
          {entry.output && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-text-muted">{t("tools.result")}</span>
                <CopyButton text={entry.output} />
              </div>
              {preBlock(entry.output)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolBlock({ entry }: ToolBlockProps) {
  const category = entry.category ?? "other";
  if (category === "bash") return <BashBlock entry={entry} />;
  if (category === "read") return <ReadBlock entry={entry} />;
  if (category === "edit" || category === "fileChange") return <EditBlock entry={entry} />;
  if (category === "search") return <SearchBlock entry={entry} />;
  if (category === "todo") return <TodoBlock entry={entry} />;
  if (category === "mcp") return <McpBlock entry={entry} />;
  return <GenericBlock entry={entry} />;
}

export function ToolBlockEmpty() {
  const { t } = useI18n();
  return (
    <div className="py-12 flex flex-col items-center justify-center text-text-muted gap-2">
      <Loader2 size={20} className="opacity-30 animate-spin" />
      <span className="text-[10px] uppercase font-bold tracking-widest">{t("run.toolEmpty")}</span>
    </div>
  );
}

export function ToolErrorChip({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-error/20 bg-error/10 px-3 py-2 text-[12px] text-error/90">
      <AlertCircle size={13} className="mt-0.5 shrink-0" />
      <span className="whitespace-pre-wrap break-words">{message}</span>
    </div>
  );
}
