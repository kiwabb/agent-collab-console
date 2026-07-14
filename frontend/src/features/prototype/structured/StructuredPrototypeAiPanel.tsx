"use client";

import { useState } from "react";
import {
  Bot,
  Check,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Send,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { StructuredPrototypeDraft } from "./types";
import { useStructuredPrototypeAi } from "./useStructuredPrototypeAi";

interface Props {
  projectId: string;
  draft: StructuredPrototypeDraft;
  pageId: string;
  selectedNodeId: string | null;
  viewport: "desktop" | "tablet" | "mobile";
  disabled: boolean;
  onDraftApplied: (draft: StructuredPrototypeDraft) => Promise<void>;
}

function shortHash(value: string | null): string {
  if (!value) return "-";
  return value.length <= 20 ? value : `${value.slice(0, 13)}…${value.slice(-6)}`;
}

export function StructuredPrototypeAiPanel({
  projectId,
  draft,
  pageId,
  selectedNodeId,
  viewport,
  disabled,
  onDraftApplied,
}: Props) {
  const { t } = useI18n();
  const [content, setContent] = useState("");
  const ai = useStructuredPrototypeAi({
    projectId,
    draft,
    pageId,
    selectedNodeId,
    viewport,
    onDraftApplied,
  });
  const run = ai.snapshot?.latestRun ?? null;
  const active =
    run &&
    ["queued", "building_context", "generating", "validating", "rendering_preview"].includes(
      run.status,
    );
  const send = async () => {
    if (await ai.send(content)) setContent("");
  };

  return (
    <div className="grid h-full min-h-0 grid-rows-[minmax(0,1fr)_auto]">
      <div className="min-h-0 overflow-auto">
        {ai.loading && !ai.snapshot ? (
          <div className="grid min-h-40 place-items-center text-xs text-text-muted">
            <LoaderCircle size={16} className="motion-essential animate-spin" aria-hidden />
          </div>
        ) : (
          <div>
            {ai.snapshot?.messages.length ? (
              <ol className="divide-y divide-border-subtle">
                {ai.snapshot.messages.map((message) => (
                  <li
                    key={message.id}
                    className={cn(
                      "grid gap-2 px-4 py-3 text-xs leading-5",
                      message.role === "assistant" ? "bg-tool-bg" : "bg-surface",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase text-text-muted">
                      <span className="inline-flex items-center gap-1.5">
                        {message.role === "assistant" && <Bot size={12} aria-hidden />}
                        {message.role === "assistant"
                          ? t("prototype.structured.ai.engineer")
                          : t("prototype.structured.ai.you")}
                      </span>
                      <span>{message.status}</span>
                    </div>
                    <p className="whitespace-pre-wrap break-words text-text-secondary">
                      {message.content}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-text-muted">
                {t("prototype.structured.ai.empty")}
              </div>
            )}

            {run && (
              <section className="border-y border-border-subtle bg-surface px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "inline-flex min-h-6 items-center gap-1.5 rounded-full px-2 text-[10px] font-semibold",
                      run.status === "preview_ready"
                        ? "bg-done-bg text-status-done ring-1 ring-done-ring"
                        : run.status === "failed" || run.status === "stale"
                          ? "bg-failed-bg text-status-failed ring-1 ring-failed-ring"
                          : "bg-tool-bg text-status-tool ring-1 ring-tool-ring",
                    )}
                  >
                    {active && (
                      <LoaderCircle
                        size={11}
                        className="motion-essential animate-spin"
                        aria-hidden
                      />
                    )}
                    {t(`prototype.structured.ai.status.${run.status}`)}
                  </span>
                  <span className="font-mono text-[9px] text-text-faint">{run.id.slice(0, 8)}</span>
                </div>

                {run.summary && (
                  <p className="mt-3 text-xs font-semibold leading-5 text-text-secondary">
                    {run.summary}
                  </p>
                )}
                {run.errorMessage && (
                  <div className="mt-3 flex gap-2 text-xs leading-5 text-status-failed">
                    <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
                    <span>{run.errorMessage}</span>
                  </div>
                )}
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[9px] text-text-muted">
                  <div>
                    <dt>base</dt>
                    <dd className="mt-0.5 font-mono">seq {run.baseHeadSequenceNo}</dd>
                  </div>
                  <div>
                    <dt>candidate</dt>
                    <dd className="mt-0.5 font-mono">{shortHash(run.candidateObjectHash)}</dd>
                  </div>
                  <div>
                    <dt>task</dt>
                    <dd className="mt-0.5 truncate font-mono">{run.taskId ?? "-"}</dd>
                  </div>
                  <div>
                    <dt>process</dt>
                    <dd className="mt-0.5 truncate font-mono">{run.executionProcessId ?? "-"}</dd>
                  </div>
                </dl>

                {run.previewPath && run.status === "preview_ready" && (
                  <div className="mt-3 overflow-hidden rounded-lg border border-border-muted bg-background/40">
                    <div className="flex h-9 items-center justify-between border-b border-border-muted bg-surface-raised px-2 text-[10px] font-semibold text-text-secondary">
                      {t("prototype.structured.ai.preview")}
                      <a
                        href={run.previewPath}
                        target="_blank"
                        rel="noreferrer"
                        className="grid size-8 cursor-pointer place-items-center rounded-md text-brand hover:bg-brand-bg"
                        aria-label={t("prototype.structured.ai.openPreview")}
                        title={t("prototype.structured.ai.openPreview")}
                      >
                        <ExternalLink size={12} aria-hidden />
                      </a>
                    </div>
                    <iframe
                      src={run.previewPath}
                      title={t("prototype.structured.ai.preview")}
                      className="h-52 w-full bg-white"
                      sandbox="allow-scripts"
                    />
                  </div>
                )}

                {run.status === "preview_ready" && (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      className="inline-flex min-h-10 cursor-pointer items-center justify-center gap-1.5 rounded-md bg-brand px-3 text-xs font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
                      onClick={() => void ai.apply()}
                      disabled={disabled || ai.mutating}
                    >
                      <Check size={14} aria-hidden />
                      {t("prototype.structured.ai.apply")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex min-h-10 cursor-pointer items-center justify-center gap-1.5 rounded-md border border-border-muted bg-surface-raised px-3 text-xs font-semibold text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
                      onClick={() => void ai.reject()}
                      disabled={disabled || ai.mutating}
                    >
                      <X size={14} aria-hidden />
                      {t("prototype.structured.ai.reject")}
                    </button>
                  </div>
                )}
              </section>
            )}

            {ai.error && (
              <div
                className="m-3 flex gap-2 rounded-lg border border-failed-ring bg-failed-bg p-3 text-xs leading-5 text-status-failed"
                role="alert"
              >
                <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{ai.error}</span>
                <button
                  type="button"
                  className="ml-auto grid size-8 shrink-0 cursor-pointer place-items-center rounded-md border border-failed-ring bg-surface-raised hover:bg-surface-hover"
                  onClick={() => void ai.retry()}
                  aria-label={t("prototype.structured.retry")}
                  title={t("prototype.structured.retry")}
                >
                  <RefreshCw size={12} aria-hidden />
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-border-subtle bg-surface p-3">
        <div className="flex gap-2">
          <textarea
            className="min-h-20 min-w-0 flex-1 resize-none rounded-lg border border-border-muted bg-surface-input p-2 text-xs text-text-secondary outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-55"
            placeholder={t("prototype.structured.ai.placeholder")}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={disabled || ai.mutating || Boolean(active)}
            maxLength={8_000}
          />
          <button
            type="button"
            className="grid size-10 cursor-pointer place-items-center self-end rounded-lg bg-brand text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => void send()}
            disabled={disabled || ai.mutating || Boolean(active) || !content.trim()}
            aria-label={t("prototype.structured.ai.send")}
            title={t("prototype.structured.ai.send")}
          >
            {ai.mutating ? (
              <LoaderCircle size={15} className="motion-essential animate-spin" aria-hidden />
            ) : (
              <Send size={15} aria-hidden />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
