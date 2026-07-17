"use client";

import { useState } from "react";
import {
  Check,
  CircleAlert,
  ExternalLink,
  LoaderCircle,
  Play,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import {
  canStartStructuredPrototypeGeneration,
  isStructuredPrototypeGenerationActive,
  structuredPrototypeGenerationBlueprintScope,
  structuredPrototypeGenerationPercent,
  structuredPrototypeGenerationSourceExclusion,
} from "./structuredPrototypeGenerationState";
import type { StructuredPrototypeDraft } from "./types";
import { useStructuredPrototypeGeneration } from "./useStructuredPrototypeGeneration";

interface Props {
  projectId: string;
  onAccepted: (draft: StructuredPrototypeDraft) => Promise<boolean>;
}

function shortIdentity(value: string | null): string {
  if (!value) return "-";
  return value.length > 22 ? `${value.slice(0, 13)}...${value.slice(-6)}` : value;
}

export function StructuredPrototypeGenerationPanel({ projectId, onAccepted }: Props) {
  const { t } = useI18n();
  const generation = useStructuredPrototypeGeneration({ projectId, onAccepted });
  const [brief, setBrief] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const job = generation.job;
  const active = job ? isStructuredPrototypeGenerationActive(job.status) : false;
  const canStart = canStartStructuredPrototypeGeneration(job);
  const blueprintScope = job?.blueprint
    ? structuredPrototypeGenerationBlueprintScope(job.blueprint).map((group) => ({
        ...group,
        label: t(`prototype.structured.generation.blueprint.${group.key}`),
      }))
    : [];
  const sourceExclusion = structuredPrototypeGenerationSourceExclusion(job);
  let sourceExclusionLabel = "-";
  if (sourceExclusion.kind === "clean") {
    sourceExclusionLabel = t("prototype.structured.generation.evidence.clean");
    if (sourceExclusion.sensitive > 0) {
      sourceExclusionLabel += `, ${sourceExclusion.sensitive} ${t("prototype.structured.generation.evidence.sensitive")}`;
    }
  } else if (sourceExclusion.kind === "dirty") {
    sourceExclusionLabel = `${sourceExclusion.tracked} ${t("prototype.structured.generation.evidence.tracked")}, ${sourceExclusion.untracked} ${t("prototype.structured.generation.evidence.untracked")}`;
    if (sourceExclusion.sensitive > 0) {
      sourceExclusionLabel += `, ${sourceExclusion.sensitive} ${t("prototype.structured.generation.evidence.sensitive")}`;
    }
  }

  const confirmDelete = async () => {
    setDeleteError(null);
    const deleted = await generation.deleteAll();
    if (deleted) {
      setDeleteDialogOpen(false);
      return;
    }
    setDeleteError(t("prototype.structured.deleteFailed"));
  };

  return (
    <section className="min-h-full overflow-hidden bg-surface/90">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-5 py-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-bg text-brand ring-1 ring-brand-ring">
            <Sparkles size={18} aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-foreground">
              {t("prototype.structured.generation.title")}
            </h2>
            <p className="mt-1 text-xs text-text-muted">Claude UI Engineer</p>
          </div>
        </div>
        {(job || generation.error) && (
          <div className="flex items-center gap-2">
            {job && (
              <span
                className={cn(
                  "inline-flex min-h-8 items-center gap-2 rounded-full px-3 text-xs font-semibold",
                  job.status === "ready" || job.status === "accepted"
                    ? "bg-done-bg text-status-done ring-1 ring-done-ring"
                    : ["failed", "interrupted", "cancelled"].includes(job.status)
                      ? "bg-failed-bg text-status-failed ring-1 ring-failed-ring"
                      : job.status === "awaiting_confirmation"
                        ? "bg-warning-bg text-status-awaiting ring-1 ring-status-awaiting/20"
                        : "bg-tool-bg text-status-tool ring-1 ring-tool-ring",
                )}
              >
                {active && (
                  <LoaderCircle size={13} className="motion-essential animate-spin" aria-hidden />
                )}
                {t(`prototype.structured.generation.status.${job.status}`)}
              </span>
            )}
            <button
              type="button"
              className="grid size-9 cursor-pointer place-items-center rounded-md border border-error/35 bg-surface-raised text-error hover:bg-error/10 disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => {
                setDeleteError(null);
                setDeleteDialogOpen(true);
              }}
              disabled={generation.mutating || active}
              aria-label={t("prototype.structured.delete")}
              title={t("prototype.structured.delete")}
            >
              <Trash2 size={15} aria-hidden />
            </button>
          </div>
        )}
      </header>

      <div className="grid min-h-[460px] lg:grid-cols-[360px_minmax(0,1fr)]">
        <div className="border-b border-border-subtle bg-surface/75 p-5 lg:border-b-0 lg:border-r sm:p-6">
          <label
            htmlFor="prototype-generation-guidance"
            className="text-sm font-semibold text-foreground"
          >
            {t("prototype.structured.generation.requirements")}
          </label>
          <textarea
            id="prototype-generation-guidance"
            className="mt-3 min-h-32 w-full resize-y rounded-lg border border-border-muted bg-surface-input p-3 text-sm leading-6 text-foreground outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:cursor-not-allowed disabled:opacity-45"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder={t("prototype.structured.generation.placeholder")}
            maxLength={8_000}
            disabled={!canStart || generation.mutating}
          />
          <button
            type="button"
            className="mt-3 inline-flex min-h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-black transition-colors hover:bg-brand-strong focus-visible:ring-2 focus-visible:ring-brand/50 disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => void generation.start(brief)}
            disabled={!canStart || generation.mutating}
          >
            {generation.mutating && canStart ? (
              <LoaderCircle size={16} className="motion-essential animate-spin" aria-hidden />
            ) : (
              <Play size={16} aria-hidden />
            )}
            {t("prototype.structured.generation.start")}
          </button>

          {job && (
            <dl className="mt-6 grid gap-3 border-t border-border-subtle pt-4 text-xs text-text-muted">
              <div>
                <dt>{t("prototype.structured.generation.evidence.job")}</dt>
                <dd className="mt-1 break-all font-mono text-[11px] text-text-secondary">
                  {job.id}
                </dd>
              </div>
              <div>
                <dt>{t("prototype.structured.generation.evidence.operation")}</dt>
                <dd className="mt-1 break-all font-mono text-[11px] text-text-secondary">
                  {job.operationId}
                </dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt>{t("prototype.structured.generation.evidence.source")}</dt>
                  <dd className="mt-1 font-mono text-[11px] text-text-secondary">
                    {job.sourcePolicy ?? "-"}
                  </dd>
                </div>
                <div>
                  <dt>{t("prototype.structured.generation.evidence.revision")}</dt>
                  <dd
                    className="mt-1 font-mono text-[11px] text-text-secondary"
                    title={job.worktreeBaseCommit ?? undefined}
                  >
                    {shortIdentity(job.worktreeBaseCommit)}
                  </dd>
                </div>
              </div>
              <div>
                <dt>{t("prototype.structured.generation.evidence.excluded")}</dt>
                <dd className="mt-1 text-[11px] leading-5 text-text-secondary">
                  {sourceExclusionLabel}
                </dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt>{t("prototype.structured.generation.evidence.blueprint")}</dt>
                  <dd className="mt-1 font-mono text-[11px] text-text-secondary">
                    {shortIdentity(job.blueprintHash)}
                  </dd>
                </div>
                <div>
                  <dt>{t("prototype.structured.generation.evidence.replay")}</dt>
                  <dd className="mt-1 font-mono text-[11px] text-text-secondary">
                    {shortIdentity(job.replayManifestObjectHash)}
                  </dd>
                </div>
              </div>
            </dl>
          )}
        </div>

        <div className="min-w-0 bg-background/35 p-4 sm:p-6">
          {generation.loading && !job ? (
            <div className="grid min-h-80 place-items-center text-sm text-text-muted">
              <LoaderCircle size={20} className="motion-essential animate-spin" aria-hidden />
            </div>
          ) : !job ? (
            <div className="grid min-h-80 place-items-center rounded-lg border border-dashed border-border-strong bg-surface/60 px-8 text-center text-sm leading-6 text-text-muted">
              {t("prototype.structured.generation.empty")}
            </div>
          ) : (
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-3">
                <div>
                  <div className="text-xs text-text-muted">
                    {t("prototype.structured.generation.stage")}
                  </div>
                  <div className="mt-1 text-base font-semibold text-foreground">
                    {t(`prototype.structured.generation.status.${job.status}`)}
                  </div>
                </div>
                <span className="font-mono text-xs text-text-secondary">
                  {job.processed}/{job.total}
                </span>
              </div>

              {job.blueprint && (
                <section className="enterprise-card rounded-lg p-4 sm:p-5">
                  <h3 className="text-lg font-semibold text-foreground">
                    {job.blueprint.documentTitle}
                  </h3>
                  <p className="mt-2 text-sm leading-6 text-text-secondary">
                    {job.blueprint.productIntent}
                  </p>
                  <div className="mt-4 border-y border-border-subtle">
                    <div className="flex items-center justify-between px-1 py-2 text-[11px] font-semibold uppercase text-text-muted">
                      <span>{t("prototype.structured.generation.blueprint.pages")}</span>
                      <span className="font-mono">{job.blueprint.pages.length}</span>
                    </div>
                    <ol className="divide-y divide-border-subtle">
                      {job.blueprint.pages.map((page) => (
                        <li
                          key={page.pageKey}
                          className="grid gap-1 px-1 py-3 sm:grid-cols-[180px_1fr]"
                        >
                          <div className="min-w-0">
                            <div className="truncate text-xs font-semibold text-foreground">
                              {page.title}
                            </div>
                            <div className="mt-1 font-mono text-[11px] text-brand">
                              {page.route}
                            </div>
                          </div>
                          <p className="text-xs leading-5 text-text-muted">{page.purpose}</p>
                        </li>
                      ))}
                    </ol>
                  </div>
                  {blueprintScope.length > 0 && (
                    <dl className="mt-4 divide-y divide-border-subtle border-y border-border-subtle">
                      {blueprintScope.map((group) => (
                        <div
                          key={group.key}
                          className="grid gap-1 px-1 py-3 sm:grid-cols-[110px_1fr]"
                        >
                          <dt className="text-xs font-semibold text-text-secondary">
                            {group.label}
                          </dt>
                          <dd className="break-words font-mono text-[11px] leading-5 text-text-muted">
                            {group.values.join("; ")}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {job.canConfirm && (
                    <button
                      type="button"
                      className="mt-4 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-brand px-4 text-sm font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
                      onClick={() => void generation.confirm()}
                      disabled={generation.mutating}
                    >
                      <Check size={16} aria-hidden />
                      {t("prototype.structured.generation.confirm")}
                    </button>
                  )}
                </section>
              )}

              {job.total > 0 && (
                <section className="enterprise-card rounded-lg p-4 sm:p-5">
                  <div className="flex items-center justify-between text-xs font-semibold text-foreground">
                    <span>{t("prototype.structured.generation.progress")}</span>
                    <span>{structuredPrototypeGenerationPercent(job)}%</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-input">
                    <div
                      className="h-full bg-brand transition-[width] motion-reduce:transition-none"
                      style={{ width: `${structuredPrototypeGenerationPercent(job)}%` }}
                    />
                  </div>
                  <ol className="mt-4 divide-y divide-border-subtle">
                    {job.items.map((item) => (
                      <li key={item.id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto]">
                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-foreground">
                            {item.pageKey ?? item.itemKey}
                          </div>
                          <div className="mt-1 text-[11px] text-text-muted">
                            {item.phase} / {item.status}
                          </div>
                          {item.errorMessage && (
                            <div className="mt-1 text-[11px] text-status-failed">
                              {item.errorMessage}
                            </div>
                          )}
                        </div>
                        <div className="text-right font-mono text-[10px] leading-4 text-text-faint">
                          <div>task {shortIdentity(item.taskId)}</div>
                          <div>process {shortIdentity(item.executionProcessId)}</div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {job.previewPath && (job.status === "ready" || job.status === "accepted") && (
                <section className="overflow-hidden rounded-lg border border-border-muted bg-surface">
                  <div className="flex h-11 items-center justify-between border-b border-border-subtle px-3 text-xs font-semibold text-foreground">
                    {t("prototype.structured.generation.preview")}
                    <a
                      href={job.previewPath}
                      target="_blank"
                      rel="noreferrer"
                      className="grid size-9 cursor-pointer place-items-center rounded-md text-brand hover:bg-brand-bg"
                      aria-label={t("prototype.structured.generation.openPreview")}
                      title={t("prototype.structured.generation.openPreview")}
                    >
                      <ExternalLink size={15} aria-hidden />
                    </a>
                  </div>
                  <iframe
                    src={job.previewPath}
                    title={t("prototype.structured.generation.preview")}
                    className="h-[460px] w-full bg-white"
                    sandbox="allow-scripts allow-same-origin"
                  />
                </section>
              )}

              {job.canAccept && (
                <button
                  type="button"
                  className="inline-flex min-h-11 w-fit cursor-pointer items-center gap-2 rounded-lg bg-brand px-5 text-sm font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
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
                  className="inline-flex min-h-11 w-fit cursor-pointer items-center gap-2 rounded-lg bg-brand px-5 text-sm font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
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
            <div
              className="mt-4 flex gap-3 rounded-lg border border-failed-ring bg-failed-bg p-3 text-xs leading-5 text-status-failed"
              role="alert"
            >
              <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 break-words">{generation.error}</span>
              <button
                type="button"
                className="grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border border-failed-ring bg-surface-raised hover:bg-surface-hover"
                onClick={() => void generation.retry()}
                aria-label={t("prototype.structured.retry")}
                title={t("prototype.structured.retry")}
              >
                <RefreshCw size={14} aria-hidden />
              </button>
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open) setDeleteError(null);
        }}
        title={t("prototype.structured.deleteTitle")}
        description={
          deleteError
            ? `${t("prototype.structured.deleteDescription")} ${deleteError}`
            : t("prototype.structured.deleteDescription")
        }
        confirmText={t("prototype.structured.deleteConfirm")}
        cancelText={t("prototype.structured.deleteCancel")}
        onConfirm={() => void confirmDelete()}
        isLoading={generation.mutating}
        loadingMotionPhase="tool"
        loadingDensity="prototype-delete"
        variant="destructive"
      />
    </section>
  );
}
