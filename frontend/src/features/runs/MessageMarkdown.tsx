"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";
import { useI18n } from "@/providers/I18nProvider";
import { cn, safeJsonRecord } from "@/lib/utils";

const components: Components = {
  p: ({ node, ...props }) => (
    <p {...props} className="my-2 leading-relaxed text-[13.5px] text-foreground/90" />
  ),
  ul: ({ node, ...props }) => (
    <ul {...props} className="my-2 pl-5 list-disc space-y-1 text-[13.5px] text-foreground/90" />
  ),
  ol: ({ node, ...props }) => (
    <ol {...props} className="my-2 pl-5 list-decimal space-y-1 text-[13.5px] text-foreground/90" />
  ),
  li: ({ node, ...props }) => <li {...props} className="leading-relaxed" />,
  h1: ({ node, ...props }) => (
    <h1 {...props} className="mt-4 mb-2 text-base font-black tracking-tight" />
  ),
  h2: ({ node, ...props }) => (
    <h2 {...props} className="mt-4 mb-2 text-[15px] font-black tracking-tight" />
  ),
  h3: ({ node, ...props }) => (
    <h3 {...props} className="mt-3 mb-2 text-[14px] font-bold tracking-tight" />
  ),
  h4: ({ node, ...props }) => (
    <h4 {...props} className="mt-2 mb-1 text-[13px] font-bold tracking-tight" />
  ),
  hr: () => <hr className="my-4 border-border-subtle" />,
  blockquote: ({ node, ...props }) => (
    <blockquote
      {...props}
      className="my-2 pl-3 border-l-2 border-brand/40 text-text-secondary italic"
    />
  ),
  a: ({ node, ...props }) => (
    <a
      {...props}
      target="_blank"
      rel="noreferrer noopener"
      className="text-brand underline-offset-2 hover:underline"
    />
  ),
  table: ({ node, ...props }) => (
    <div className="my-2 overflow-auto rounded-lg border border-border-subtle">
      <table {...props} className="w-full text-[12px] text-text-secondary" />
    </div>
  ),
  thead: ({ node, ...props }) => <thead {...props} className="bg-surface-raised/60" />,
  th: ({ node, ...props }) => (
    <th
      {...props}
      className="px-3 py-1.5 text-left font-bold uppercase tracking-widest text-[10px]"
    />
  ),
  td: ({ node, ...props }) => (
    <td {...props} className="px-3 py-1.5 border-t border-border-subtle align-top" />
  ),
  code: ({ node, className, children, ...props }) => {
    const isInline = !(className && /language-/.test(className));
    if (isInline) {
      return (
        <code
          {...props}
          className="px-1 py-0.5 rounded bg-surface-raised border border-border-subtle font-mono text-[12px]"
        >
          {children}
        </code>
      );
    }
    return (
      <code className={cn(className, "font-mono text-[12px] leading-relaxed")} {...props}>
        {children}
      </code>
    );
  },
  pre: ({ node, ...props }) => (
    <pre
      {...props}
      className="my-2 px-3 py-2 overflow-auto rounded-lg bg-background/70 border border-border-subtle"
    />
  ),
};

interface Props {
  content: string;
  className?: string;
}

interface StartupScriptResult {
  setupScript: string | null;
  runCommand: string | null;
  accessUrl: string | null;
  notes: string[];
}

function readStringField(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readStringListField(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseStartupScriptResult(content: string): StartupScriptResult | null {
  const record = safeJsonRecord(content.trim());
  if (!record) return null;
  const setupScript = readStringField(record, "setup_script");
  const runCommand = readStringField(record, "run_command");
  const accessUrl = readStringField(record, "access_url");
  const notes = readStringListField(record, "notes");
  if (!setupScript && !runCommand && !accessUrl && notes.length === 0) return null;
  if (!("setup_script" in record || "run_command" in record || "access_url" in record)) {
    return null;
  }
  return { setupScript, runCommand, accessUrl, notes };
}

function CommandLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
        {label}
      </div>
      <div className="rounded-lg border border-border-subtle bg-background/70 px-3 py-2 font-mono text-[12px] leading-relaxed text-foreground">
        {value}
      </div>
    </div>
  );
}

function StartupScriptResultCard({ result }: { result: StartupScriptResult }) {
  const { t } = useI18n();
  const accessUrlIsLink =
    result.accessUrl?.startsWith("http://") || result.accessUrl?.startsWith("https://");
  return (
    <section className="my-2 overflow-hidden rounded-xl border border-status-done/30 bg-status-done/5">
      <div className="border-b border-status-done/20 bg-status-done/10 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-black text-foreground">
            {t("message.startupScript.title")}
          </span>
          <span className="rounded-full border border-status-done/30 bg-status-done/10 px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.16em] text-status-done">
            {t("message.startupScript.success")}
          </span>
        </div>
      </div>
      <div className="space-y-3 px-3 py-3">
        {result.setupScript && (
          <CommandLine label={t("message.startupScript.setup")} value={result.setupScript} />
        )}
        {result.runCommand && (
          <CommandLine label={t("message.startupScript.run")} value={result.runCommand} />
        )}
        {result.accessUrl && (
          <div className="space-y-1">
            <div className="text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
              {t("message.startupScript.accessUrl")}
            </div>
            {accessUrlIsLink ? (
              <a
                href={result.accessUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex max-w-full items-center rounded-lg border border-brand/30 bg-brand/10 px-3 py-2 font-mono text-[12px] font-semibold text-brand underline-offset-2 hover:underline"
              >
                <span className="truncate">{result.accessUrl}</span>
              </a>
            ) : (
              <div className="rounded-lg border border-border-subtle bg-background/70 px-3 py-2 font-mono text-[12px] leading-relaxed text-foreground">
                {result.accessUrl}
              </div>
            )}
          </div>
        )}
        {result.notes.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
              {t("message.startupScript.notes")}
            </div>
            <ul className="space-y-1.5">
              {result.notes.map((note, index) => (
                <li
                  key={`${index}-${note}`}
                  className="flex gap-2 rounded-lg border border-border-subtle bg-surface/60 px-3 py-2 text-[12px] leading-relaxed text-text-secondary"
                >
                  <span className="mt-0.5 font-mono text-[10px] font-black text-status-done">
                    {index + 1}
                  </span>
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

export const MessageMarkdown = memo(function MessageMarkdown({ content, className }: Props) {
  const startupScriptResult = parseStartupScriptResult(content);
  if (startupScriptResult) {
    return (
      <div className={cn("max-w-none break-words", className)}>
        <StartupScriptResultCard result={startupScriptResult} />
      </div>
    );
  }
  return (
    <div className={cn("max-w-none break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
