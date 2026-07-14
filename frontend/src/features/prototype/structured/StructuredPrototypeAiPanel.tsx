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
          <div className="grid min-h-40 place-items-center text-xs text-[#62706b]">
            <LoaderCircle size={16} className="animate-spin" aria-hidden />
          </div>
        ) : (
          <div>
            {ai.snapshot?.messages.length ? (
              <ol className="divide-y divide-[#e3e7e5]">
                {ai.snapshot.messages.map((message) => (
                  <li
                    key={message.id}
                    className={cn(
                      "grid gap-2 px-4 py-3 text-xs leading-5",
                      message.role === "assistant" ? "bg-[#f4f8f6]" : "bg-white",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase text-[#62706b]">
                      <span className="inline-flex items-center gap-1.5">
                        {message.role === "assistant" && <Bot size={12} aria-hidden />}
                        {message.role === "assistant"
                          ? t("prototype.structured.ai.engineer")
                          : t("prototype.structured.ai.you")}
                      </span>
                      <span>{message.status}</span>
                    </div>
                    <p className="whitespace-pre-wrap break-words text-[#26312d]">
                      {message.content}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="grid min-h-40 place-items-center px-6 text-center text-xs text-[#62706b]">
                {t("prototype.structured.ai.empty")}
              </div>
            )}

            {run && (
              <section className="border-y border-[#d9dfdc] bg-white px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "inline-flex min-h-6 items-center gap-1.5 px-2 text-[10px] font-semibold",
                      run.status === "preview_ready"
                        ? "bg-[#e1f1ed] text-[#126b5f]"
                        : run.status === "failed" || run.status === "stale"
                          ? "bg-[#fff1f3] text-[#8c1d31]"
                          : "bg-[#edf0ef] text-[#53615c]",
                    )}
                  >
                    {active && <LoaderCircle size={11} className="animate-spin" aria-hidden />}
                    {t(`prototype.structured.ai.status.${run.status}`)}
                  </span>
                  <span className="font-mono text-[9px] text-[#7b8782]">{run.id.slice(0, 8)}</span>
                </div>

                {run.summary && (
                  <p className="mt-3 text-xs font-semibold leading-5 text-[#26312d]">
                    {run.summary}
                  </p>
                )}
                {run.errorMessage && (
                  <div className="mt-3 flex gap-2 text-xs leading-5 text-[#8c1d31]">
                    <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
                    <span>{run.errorMessage}</span>
                  </div>
                )}
                <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[9px] text-[#62706b]">
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
                  <div className="mt-3 border border-[#c9d2ce] bg-[#eef1ef]">
                    <div className="flex h-8 items-center justify-between border-b border-[#c9d2ce] bg-white px-2 text-[10px] font-semibold text-[#53615c]">
                      {t("prototype.structured.ai.preview")}
                      <a
                        href={run.previewPath}
                        target="_blank"
                        rel="noreferrer"
                        className="grid size-6 place-items-center text-[#126b5f]"
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
                      className="inline-flex min-h-9 items-center justify-center gap-1.5 bg-[#126b5f] px-3 text-xs font-semibold text-white disabled:opacity-45"
                      onClick={() => void ai.apply()}
                      disabled={disabled || ai.mutating}
                    >
                      <Check size={14} aria-hidden />
                      {t("prototype.structured.ai.apply")}
                    </button>
                    <button
                      type="button"
                      className="inline-flex min-h-9 items-center justify-center gap-1.5 border border-[#c9d2ce] bg-white px-3 text-xs font-semibold text-[#39443f] disabled:opacity-45"
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
              <div className="m-3 flex gap-2 border border-[#e4a8b2] bg-[#fff1f3] p-3 text-xs leading-5 text-[#8c1d31]">
                <CircleAlert size={14} className="mt-0.5 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{ai.error}</span>
                <button
                  type="button"
                  className="ml-auto grid size-7 shrink-0 place-items-center border border-[#e4a8b2] bg-white"
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

      <div className="border-t border-[#d9dfdc] bg-white p-3">
        <div className="flex gap-2">
          <textarea
            className="min-h-20 min-w-0 flex-1 resize-none border border-[#c9d2ce] bg-[#f7f8f7] p-2 text-xs text-[#26312d] outline-none focus:border-[#126b5f] focus:ring-2 focus:ring-[#126b5f]/15 disabled:opacity-55"
            placeholder={t("prototype.structured.ai.placeholder")}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={disabled || ai.mutating || Boolean(active)}
            maxLength={8_000}
          />
          <button
            type="button"
            className="grid size-9 place-items-center self-end bg-[#126b5f] text-white disabled:opacity-45"
            onClick={() => void send()}
            disabled={disabled || ai.mutating || Boolean(active) || !content.trim()}
            aria-label={t("prototype.structured.ai.send")}
            title={t("prototype.structured.ai.send")}
          >
            {ai.mutating ? (
              <LoaderCircle size={15} className="animate-spin" aria-hidden />
            ) : (
              <Send size={15} aria-hidden />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
