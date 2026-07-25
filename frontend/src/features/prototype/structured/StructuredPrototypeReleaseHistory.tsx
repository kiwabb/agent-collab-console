"use client";

import { useCallback, useEffect, useState } from "react";
import { Diff, ExternalLink, History, RotateCcw } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  diffStructuredPrototypeRevisions,
  listStructuredPrototypeRevisions,
  rollbackStructuredPrototypePublication,
} from "@/lib/api/prototypes";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type {
  StructuredPrototypePublicationEvent,
  StructuredPrototypePublishedRevision,
  StructuredPrototypeRevisionDiff,
  StructuredPrototypeRevisionHistory,
  StructuredPrototypeRevisionSource,
} from "./types";

type ReleaseHistoryFetchState =
  | { kind: "loading" }
  | { kind: "failed"; message: string }
  | { kind: "ready"; history: StructuredPrototypeRevisionHistory };

type RevisionDiffFetchState =
  | { kind: "loading" }
  | { kind: "failed"; message: string }
  | { kind: "ready"; diff: StructuredPrototypeRevisionDiff };

const SOURCE_LABEL_KEYS: Record<StructuredPrototypeRevisionSource, string> = {
  user: "prototype.structured.history.source.user",
  ai: "prototype.structured.history.source.ai",
  initial_generation: "prototype.structured.history.source.initial_generation",
};

function RevisionDiffSummary({ state }: { state: RevisionDiffFetchState | undefined }) {
  const { t } = useI18n();
  if (state === undefined || state.kind === "loading") {
    return <p className="text-text-muted">{t("prototype.structured.history.diff.loading")}</p>;
  }
  if (state.kind === "failed") {
    return (
      <p className="text-error">
        {t("prototype.structured.history.diff.failed", { message: state.message })}
      </p>
    );
  }
  const diff = state.diff;
  if (diff.identical) {
    return <p className="text-text-muted">{t("prototype.structured.history.diff.identical")}</p>;
  }
  const changedSections = [
    diff.tokensChanged ? t("prototype.structured.history.diff.section.tokens") : null,
    diff.settingsChanged ? t("prototype.structured.history.diff.section.settings") : null,
    diff.navigationChanged ? t("prototype.structured.history.diff.section.navigation") : null,
    diff.runtimeChanged ? t("prototype.structured.history.diff.section.runtime") : null,
    diff.componentDefinitionsChanged
      ? t("prototype.structured.history.diff.section.components")
      : null,
  ].filter((section): section is string => section !== null);
  return (
    <ul className="grid gap-1">
      {diff.titleFrom !== null && diff.titleTo !== null && (
        <li>
          {t("prototype.structured.history.diff.titleChanged", {
            from: diff.titleFrom,
            to: diff.titleTo,
          })}
        </li>
      )}
      {diff.pagesAdded.map((page) => (
        <li key={`added-${page.id}`} className="text-success">
          {t("prototype.structured.history.diff.pageAdded", { title: page.title })}
        </li>
      ))}
      {diff.pagesRemoved.map((page) => (
        <li key={`removed-${page.id}`} className="text-error">
          {t("prototype.structured.history.diff.pageRemoved", { title: page.title })}
        </li>
      ))}
      {diff.pagesModified.map((page) => (
        <li key={`modified-${page.id}`}>
          {t("prototype.structured.history.diff.pageModified", {
            title: page.title,
            added: page.nodesAdded,
            removed: page.nodesRemoved,
            modified: page.nodesModified,
          })}
        </li>
      ))}
      {(diff.flowsAdded > 0 || diff.flowsRemoved > 0 || diff.flowsModified > 0) && (
        <li>
          {t("prototype.structured.history.diff.flows", {
            added: diff.flowsAdded,
            removed: diff.flowsRemoved,
            modified: diff.flowsModified,
          })}
        </li>
      )}
      {(diff.assetRefsAdded > 0 || diff.assetRefsRemoved > 0) && (
        <li>
          {t("prototype.structured.history.diff.assets", {
            added: diff.assetRefsAdded,
            removed: diff.assetRefsRemoved,
          })}
        </li>
      )}
      {changedSections.length > 0 && (
        <li>
          {t("prototype.structured.history.diff.sections", {
            sections: changedSections.join(" / "),
          })}
        </li>
      )}
    </ul>
  );
}

function formatPublishedAt(locale: string, publishedAt: string): string {
  const parsed = new Date(publishedAt);
  if (Number.isNaN(parsed.getTime())) return publishedAt;
  return parsed.toLocaleString(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function StructuredPrototypeReleaseHistoryDialog({
  open,
  onOpenChange,
  documentId,
  onRestored,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentId: string;
  onRestored?: (() => void) | undefined;
}) {
  const { locale, t } = useI18n();
  const [fetchState, setFetchState] = useState<ReleaseHistoryFetchState>({ kind: "loading" });
  const [selectedRevisionNo, setSelectedRevisionNo] = useState<number | null>(null);
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffs, setDiffs] = useState<Record<number, RevisionDiffFetchState>>({});
  const [restoreImpact, setRestoreImpact] = useState<RevisionDiffFetchState | undefined>(undefined);

  const loadHistory = useCallback(async (): Promise<void> => {
    setFetchState({ kind: "loading" });
    try {
      const history = await listStructuredPrototypeRevisions(documentId);
      setFetchState({ kind: "ready", history });
      setSelectedRevisionNo((current) => {
        if (current !== null && history.revisions.some((entry) => entry.revisionNo === current)) {
          return current;
        }
        return history.currentRevisionNo ?? history.revisions[0]?.revisionNo ?? null;
      });
    } catch (error) {
      setFetchState({
        kind: "failed",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }, [documentId]);

  useEffect(() => {
    if (!open) return;
    setRestoreError(null);
    setDiffOpen(false);
    setDiffs({});
    void loadHistory();
  }, [open, loadHistory]);

  const revisions: StructuredPrototypePublishedRevision[] =
    fetchState.kind === "ready" ? fetchState.history.revisions : [];
  const currentRevisionNo =
    fetchState.kind === "ready" ? fetchState.history.currentRevisionNo : null;
  const selected =
    revisions.find((entry) => entry.revisionNo === selectedRevisionNo) ?? revisions[0] ?? null;

  const selectedIndex =
    selected === null
      ? -1
      : revisions.findIndex((entry) => entry.revisionNo === selected.revisionNo);
  const previousRevisionNo =
    selectedIndex >= 0 && selectedIndex < revisions.length - 1
      ? (revisions[selectedIndex + 1]?.revisionNo ?? null)
      : null;

  useEffect(() => {
    if (!diffOpen || selected === null || previousRevisionNo === null) return;
    if (diffs[selected.revisionNo] !== undefined) return;
    const targetRevisionNo = selected.revisionNo;
    setDiffs((current) => ({ ...current, [targetRevisionNo]: { kind: "loading" } }));
    void diffStructuredPrototypeRevisions(documentId, targetRevisionNo, previousRevisionNo)
      .then((diff) => {
        setDiffs((current) => ({ ...current, [targetRevisionNo]: { kind: "ready", diff } }));
      })
      .catch((error: unknown) => {
        setDiffs((current) => ({
          ...current,
          [targetRevisionNo]: {
            kind: "failed",
            message: error instanceof Error ? error.message : String(error),
          },
        }));
      });
  }, [diffOpen, selected, previousRevisionNo, diffs, documentId]);

  const openRestoreConfirm = useCallback((): void => {
    setRestoreConfirmOpen(true);
    if (selected === null || currentRevisionNo === null) return;
    const targetRevisionNo = selected.revisionNo;
    setRestoreImpact({ kind: "loading" });
    void diffStructuredPrototypeRevisions(documentId, targetRevisionNo, currentRevisionNo)
      .then((diff) => setRestoreImpact({ kind: "ready", diff }))
      .catch((error: unknown) => {
        setRestoreImpact({
          kind: "failed",
          message: error instanceof Error ? error.message : String(error),
        });
      });
  }, [selected, currentRevisionNo, documentId]);

  const restoreSelected = useCallback(async (): Promise<void> => {
    if (selected === null || currentRevisionNo === null || selected.isCurrent) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      await rollbackStructuredPrototypePublication(documentId, {
        contractVersion: 1,
        clientRequestId: crypto.randomUUID(),
        targetRevisionNo: selected.revisionNo,
        expectedCurrentRevisionNo: currentRevisionNo,
      });
      setRestoreConfirmOpen(false);
      onRestored?.();
      await loadHistory();
    } catch (error) {
      setRestoreConfirmOpen(false);
      setRestoreError(error instanceof Error ? error.message : String(error));
    } finally {
      setRestoring(false);
    }
  }, [selected, currentRevisionNo, documentId, loadHistory, onRestored]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid h-[min(85dvh,44rem)] grid-rows-[auto_minmax(0,1fr)] sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History size={16} aria-hidden />
            {t("prototype.structured.history.title")}
            {fetchState.kind === "ready" && revisions.length > 0 && (
              <span className="text-xs font-normal text-text-muted">
                {t("prototype.structured.history.count", { count: revisions.length })}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>{t("prototype.structured.history.description")}</DialogDescription>
        </DialogHeader>
        {fetchState.kind === "loading" ? (
          <div className="grid place-items-center text-sm text-text-muted">
            {t("prototype.structured.history.loading")}
          </div>
        ) : fetchState.kind === "failed" ? (
          <div className="grid content-center justify-items-center gap-3 text-center">
            <p className="max-w-md text-sm text-error">
              {t("prototype.structured.history.failed", { message: fetchState.message })}
            </p>
            <button
              type="button"
              className="inline-flex min-h-9 cursor-pointer items-center rounded-md border border-border-muted bg-surface-raised px-3 text-xs font-semibold text-brand hover:bg-surface-hover"
              onClick={() => void loadHistory()}
            >
              {t("prototype.structured.history.retry")}
            </button>
          </div>
        ) : revisions.length === 0 ? (
          <div className="grid place-items-center px-6 text-center text-sm text-text-muted">
            {t("prototype.structured.history.empty")}
          </div>
        ) : (
          <div className="grid min-h-0 grid-cols-1 gap-3 sm:grid-cols-[16rem_minmax(0,1fr)]">
            <div className="flex min-h-0 flex-col gap-2">
              <ol
                className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1"
                aria-label={t("prototype.structured.history.title")}
              >
                {revisions.map((entry) => {
                  const isSelected = selected?.revisionNo === entry.revisionNo;
                  return (
                    <li key={entry.revisionId}>
                      <button
                        type="button"
                        className={cn(
                          "w-full cursor-pointer rounded-md border px-3 py-2 text-left",
                          isSelected
                            ? "border-brand bg-brand-bg"
                            : "border-border-muted bg-surface-raised hover:bg-surface-hover",
                        )}
                        aria-pressed={isSelected}
                        onClick={() => setSelectedRevisionNo(entry.revisionNo)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-bold text-foreground">
                            {t("prototype.structured.history.revision", { no: entry.revisionNo })}
                          </span>
                          {entry.isCurrent && (
                            <span className="rounded-full bg-brand px-2 py-0.5 text-[10px] font-semibold text-black">
                              {t("prototype.structured.history.current")}
                            </span>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-text-muted">
                          {formatPublishedAt(locale, entry.publishedAt)}
                        </div>
                        <div className="mt-1 line-clamp-2 text-xs text-text-muted">
                          {entry.summary}
                        </div>
                        <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                          {t(SOURCE_LABEL_KEYS[entry.source])}
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ol>
              {fetchState.kind === "ready" && fetchState.history.events.length > 0 && (
                <div className="max-h-36 shrink-0 overflow-y-auto rounded-md border border-border-muted bg-surface-raised p-2 text-xs">
                  <p className="mb-1 font-bold uppercase tracking-wide text-text-muted">
                    {t("prototype.structured.history.timeline")}
                  </p>
                  <ol className="grid gap-1">
                    {fetchState.history.events.map(
                      (event: StructuredPrototypePublicationEvent, index: number) => (
                        <li
                          key={`${event.kind}-${event.revisionNo}-${event.occurredAt}-${index}`}
                          className="flex items-baseline justify-between gap-2"
                        >
                          <span
                            className={cn(event.kind === "rollback" && "text-amber-600")}
                            title={event.summary ?? undefined}
                          >
                            {t(
                              event.kind === "publish"
                                ? "prototype.structured.history.timeline.publish"
                                : "prototype.structured.history.timeline.rollback",
                              { no: event.revisionNo },
                            )}
                          </span>
                          <span className="shrink-0 text-text-muted">
                            {formatPublishedAt(locale, event.occurredAt)}
                          </span>
                        </li>
                      ),
                    )}
                  </ol>
                </div>
              )}
            </div>
            {selected && (
              <div className="flex min-h-0 flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-text-muted">
                    {t("prototype.structured.history.revision", { no: selected.revisionNo })} ·{" "}
                    {formatPublishedAt(locale, selected.publishedAt)}
                  </span>
                  <div className="flex items-center gap-2">
                    {previousRevisionNo !== null && (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold",
                          diffOpen
                            ? "border-brand bg-brand-bg text-brand"
                            : "border-border-muted bg-surface-raised text-brand hover:bg-surface-hover",
                        )}
                        aria-pressed={diffOpen}
                        onClick={() => setDiffOpen((current) => !current)}
                      >
                        <Diff size={13} aria-hidden />
                        {t("prototype.structured.history.diff")}
                      </button>
                    )}
                    {!selected.isCurrent && currentRevisionNo !== null && (
                      <button
                        type="button"
                        className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md bg-brand px-2.5 text-xs font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
                        onClick={openRestoreConfirm}
                        disabled={restoring}
                      >
                        <RotateCcw size={13} aria-hidden />
                        {t(
                          restoring
                            ? "prototype.structured.history.restoring"
                            : "prototype.structured.history.restore",
                        )}
                      </button>
                    )}
                    <a
                      href={selected.artifactPath}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border-muted bg-surface-raised px-2.5 text-xs font-semibold text-brand hover:bg-surface-hover"
                    >
                      <ExternalLink size={13} aria-hidden />
                      {t("prototype.structured.history.open")}
                    </a>
                  </div>
                </div>
                {restoreError !== null && (
                  <p className="text-xs text-error">
                    {t("prototype.structured.history.restoreFailed", { message: restoreError })}
                  </p>
                )}
                {diffOpen && previousRevisionNo !== null && (
                  <div className="max-h-44 overflow-y-auto rounded-md border border-border-muted bg-surface-raised p-2.5 text-xs text-foreground">
                    <p className="mb-1.5 font-semibold text-text-muted">
                      {t("prototype.structured.history.diff.base", { no: previousRevisionNo })}
                    </p>
                    <RevisionDiffSummary state={diffs[selected.revisionNo]} />
                  </div>
                )}
                <iframe
                  key={selected.artifactPath}
                  className="min-h-0 w-full flex-1 rounded-md border border-border-muted bg-white"
                  src={selected.artifactPath}
                  title={t("prototype.structured.history.preview")}
                  sandbox="allow-scripts"
                />
              </div>
            )}
          </div>
        )}
        <Dialog
          open={restoreConfirmOpen}
          onOpenChange={(nextOpen) => {
            if (!restoring) setRestoreConfirmOpen(nextOpen);
          }}
        >
          <DialogContent className="sm:max-w-lg" showCloseButton={false}>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <RotateCcw size={16} aria-hidden />
                {t("prototype.structured.history.restoreTitle")}
              </DialogTitle>
              <DialogDescription>
                {t("prototype.structured.history.restoreDescription", {
                  no: selected?.revisionNo ?? 0,
                })}
              </DialogDescription>
            </DialogHeader>
            {selected !== null && currentRevisionNo !== null && (
              <div className="max-h-48 overflow-y-auto rounded-md border border-border-muted bg-surface-raised p-2.5 text-xs text-foreground">
                <p className="mb-1.5 font-semibold text-text-muted">
                  {t("prototype.structured.history.restoreImpact", {
                    from: currentRevisionNo,
                    to: selected.revisionNo,
                  })}
                </p>
                <RevisionDiffSummary state={restoreImpact} />
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="inline-flex min-h-9 cursor-pointer items-center rounded-md border border-border-muted bg-surface-raised px-3 text-xs font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-45"
                onClick={() => setRestoreConfirmOpen(false)}
                disabled={restoring}
              >
                {t("prototype.structured.history.restoreCancel")}
              </button>
              <button
                type="button"
                className="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-md bg-brand px-3 text-xs font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
                onClick={() => void restoreSelected()}
                disabled={restoring}
              >
                <RotateCcw size={14} aria-hidden />
                {t(
                  restoring
                    ? "prototype.structured.history.restoring"
                    : "prototype.structured.history.restoreConfirm",
                )}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
