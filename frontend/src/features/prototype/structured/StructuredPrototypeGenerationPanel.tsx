"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Check,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  Play,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import {
  canStartStructuredPrototypeGeneration,
  isStructuredPrototypeGenerationActive,
  structuredPrototypeGenerationPercent,
} from "./structuredPrototypeGenerationState";
import type { StructuredPrototypeDraft } from "./types";
import { useStructuredPrototypeGeneration } from "./useStructuredPrototypeGeneration";

interface Props {
  projectId: string;
  onAccepted: (draft: StructuredPrototypeDraft) => Promise<void>;
}

function shortIdentity(value: string | null): string {
  if (!value) return "-";
  return value.length > 22 ? `${value.slice(0, 13)}...${value.slice(-6)}` : value;
}

export function StructuredPrototypeGenerationPanel({ projectId, onAccepted }: Props) {
  const { t } = useI18n();
  const generation = useStructuredPrototypeGeneration({ projectId, onAccepted });
  const [brief, setBrief] = useState("");
  const job = generation.job;
  const active = job ? isStructuredPrototypeGenerationActive(job.status) : false;
  const canStart = canStartStructuredPrototypeGeneration(job);

  return (
    <div className="min-h-[100dvh] bg-[#eef1ef] text-[#17201d]">
      <header className="flex min-h-14 items-center gap-3 border-b border-[#d9dfdc] bg-white px-4">
        <Link
          href={`/projects/${projectId}/prototypes`}
          className="grid size-8 place-items-center bg-[#17201d] text-white"
          aria-label={t("prototype.structured.back")}
        >
          <ArrowLeft size={15} aria-hidden />
        </Link>
        <div className="min-w-0">
          <div className="text-xs font-bold">{t("prototype.structured.brand")}</div>
          <div className="truncate text-[10px] text-[#62706b]">
            {t("prototype.structured.generation.title")}
          </div>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1180px] gap-0 lg:grid-cols-[360px_minmax(0,1fr)]">
        <section className="border-b border-[#d9dfdc] bg-white p-5 lg:min-h-[calc(100dvh-56px)] lg:border-b-0 lg:border-r">
          <div className="flex items-center gap-2 text-sm font-bold">
            <Sparkles size={16} className="text-[#126b5f]" aria-hidden />
            {t("prototype.structured.generation.requirements")}
          </div>
          <textarea
            className="mt-4 min-h-40 w-full resize-y border border-[#c9d2ce] bg-[#f7f8f7] p-3 text-sm leading-6 outline-none focus:border-[#126b5f] focus:ring-2 focus:ring-[#126b5f]/15 disabled:opacity-55"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder={t("prototype.structured.generation.placeholder")}
            maxLength={8_000}
            disabled={!canStart || generation.mutating}
          />
          <button
            type="button"
            className="mt-3 inline-flex min-h-10 w-full items-center justify-center gap-2 bg-[#126b5f] px-4 text-sm font-semibold text-white disabled:opacity-45"
            onClick={() => void generation.start(brief)}
            disabled={!canStart || generation.mutating || !brief.trim()}
          >
            {generation.mutating && canStart ? (
              <LoaderCircle size={15} className="animate-spin" aria-hidden />
            ) : (
              <Play size={15} aria-hidden />
            )}
            {t("prototype.structured.generation.start")}
          </button>

          {job && (
            <dl className="mt-6 grid gap-3 border-t border-[#e3e7e5] pt-4 text-[10px] text-[#62706b]">
              <div>
                <dt>{t("prototype.structured.generation.evidence.job")}</dt>
                <dd className="mt-1 break-all font-mono text-[#26312d]">{job.id}</dd>
              </div>
              <div>
                <dt>{t("prototype.structured.generation.evidence.operation")}</dt>
                <dd className="mt-1 break-all font-mono text-[#26312d]">{job.operationId}</dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt>{t("prototype.structured.generation.evidence.blueprint")}</dt>
                  <dd className="mt-1 font-mono text-[#26312d]">
                    {shortIdentity(job.blueprintHash)}
                  </dd>
                </div>
                <div>
                  <dt>{t("prototype.structured.generation.evidence.replay")}</dt>
                  <dd className="mt-1 font-mono text-[#26312d]">
                    {shortIdentity(job.replayManifestObjectHash)}
                  </dd>
                </div>
              </div>
            </dl>
          )}
        </section>

        <section className="min-w-0 p-4 sm:p-6">
          {generation.loading && !job ? (
            <div className="grid min-h-72 place-items-center text-sm text-[#62706b]">
              <LoaderCircle size={18} className="animate-spin" aria-hidden />
            </div>
          ) : !job ? (
            <div className="grid min-h-72 place-items-center border border-dashed border-[#b8c3be] bg-white px-8 text-center text-sm leading-6 text-[#62706b]">
              {t("prototype.structured.generation.empty")}
            </div>
          ) : (
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#c9d2ce] pb-3">
                <div>
                  <div className="text-xs text-[#62706b]">
                    {t("prototype.structured.generation.stage")}
                  </div>
                  <div className="mt-1 text-base font-bold">
                    {t(`prototype.structured.generation.status.${job.status}`)}
                  </div>
                </div>
                <span
                  className={cn(
                    "inline-flex min-h-7 items-center gap-2 px-3 text-xs font-semibold",
                    job.status === "ready" || job.status === "accepted"
                      ? "bg-[#e1f1ed] text-[#126b5f]"
                      : ["failed", "interrupted", "cancelled"].includes(job.status)
                        ? "bg-[#fff1f3] text-[#8c1d31]"
                        : "bg-[#edf0ef] text-[#53615c]",
                  )}
                >
                  {active && <LoaderCircle size={13} className="animate-spin" aria-hidden />}
                  {job.processed}/{job.total}
                </span>
              </div>

              {job.blueprint && (
                <section className="bg-white p-4 sm:p-5">
                  <h1 className="text-lg font-bold">{job.blueprint.documentTitle}</h1>
                  <p className="mt-2 text-sm leading-6 text-[#53615c]">
                    {job.blueprint.productIntent}
                  </p>
                  <div className="mt-4 grid gap-2 sm:grid-cols-3">
                    {job.blueprint.pages.map((page) => (
                      <div key={page.pageKey} className="border border-[#d9dfdc] p-3">
                        <div className="text-xs font-bold">{page.title}</div>
                        <div className="mt-1 font-mono text-[10px] text-[#126b5f]">
                          {page.route}
                        </div>
                        <p className="mt-2 text-[11px] leading-5 text-[#62706b]">{page.purpose}</p>
                      </div>
                    ))}
                  </div>
                  {job.canConfirm && (
                    <button
                      type="button"
                      className="mt-4 inline-flex min-h-10 items-center gap-2 bg-[#126b5f] px-4 text-sm font-semibold text-white disabled:opacity-45"
                      onClick={() => void generation.confirm()}
                      disabled={generation.mutating}
                    >
                      <Check size={15} aria-hidden />
                      {t("prototype.structured.generation.confirm")}
                    </button>
                  )}
                </section>
              )}

              {job.total > 0 && (
                <section className="bg-white p-4 sm:p-5">
                  <div className="flex items-center justify-between text-xs font-semibold">
                    <span>{t("prototype.structured.generation.progress")}</span>
                    <span>{structuredPrototypeGenerationPercent(job)}%</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden bg-[#dfe5e2]">
                    <div
                      className="h-full bg-[#126b5f] transition-[width] motion-reduce:transition-none"
                      style={{ width: `${structuredPrototypeGenerationPercent(job)}%` }}
                    />
                  </div>
                  <ol className="mt-4 divide-y divide-[#e3e7e5]">
                    {job.items.map((item) => (
                      <li key={item.id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto]">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold">
                            {item.pageKey ?? item.itemKey}
                          </div>
                          <div className="mt-1 text-[10px] text-[#62706b]">
                            {item.phase} / {item.status}
                          </div>
                          {item.errorMessage && (
                            <div className="mt-1 text-[10px] text-[#8c1d31]">
                              {item.errorMessage}
                            </div>
                          )}
                        </div>
                        <div className="text-right font-mono text-[9px] leading-4 text-[#7b8782]">
                          <div>task {shortIdentity(item.taskId)}</div>
                          <div>process {shortIdentity(item.executionProcessId)}</div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {job.previewPath && (job.status === "ready" || job.status === "accepted") && (
                <section className="overflow-hidden border border-[#c9d2ce] bg-white">
                  <div className="flex h-10 items-center justify-between border-b border-[#c9d2ce] px-3 text-xs font-semibold">
                    {t("prototype.structured.generation.preview")}
                    <a
                      href={job.previewPath}
                      target="_blank"
                      rel="noreferrer"
                      className="grid size-7 place-items-center text-[#126b5f]"
                      aria-label={t("prototype.structured.generation.openPreview")}
                      title={t("prototype.structured.generation.openPreview")}
                    >
                      <ExternalLink size={14} aria-hidden />
                    </a>
                  </div>
                  <iframe
                    src={job.previewPath}
                    title={t("prototype.structured.generation.preview")}
                    className="h-[460px] w-full bg-white"
                    sandbox="allow-scripts"
                  />
                </section>
              )}

              {job.canAccept && (
                <button
                  type="button"
                  className="inline-flex min-h-11 w-fit items-center gap-2 bg-[#126b5f] px-5 text-sm font-semibold text-white disabled:opacity-45"
                  onClick={() => void generation.accept()}
                  disabled={generation.mutating}
                >
                  <Check size={16} aria-hidden />
                  {t("prototype.structured.generation.accept")}
                </button>
              )}
              {job.status === "accepted" && (
                <button
                  type="button"
                  className="inline-flex min-h-11 w-fit items-center gap-2 bg-[#126b5f] px-5 text-sm font-semibold text-white disabled:opacity-45"
                  onClick={() => void generation.enterAccepted()}
                  disabled={generation.mutating}
                >
                  <Play size={16} aria-hidden />
                  {t("prototype.structured.generation.enter")}
                </button>
              )}
            </div>
          )}

          {generation.error && (
            <div className="mt-4 flex gap-3 border border-[#e4a8b2] bg-[#fff1f3] p-3 text-xs leading-5 text-[#8c1d31]">
              <CircleAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 break-words">{generation.error}</span>
              <button
                type="button"
                className="grid size-8 shrink-0 place-items-center border border-[#e4a8b2] bg-white"
                onClick={() => void generation.retry()}
                aria-label={t("prototype.structured.retry")}
                title={t("prototype.structured.retry")}
              >
                <RefreshCw size={13} aria-hidden />
              </button>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
