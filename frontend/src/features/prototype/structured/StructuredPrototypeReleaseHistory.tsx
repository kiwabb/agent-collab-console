"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, History, RotateCcw } from "lucide-react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  listStructuredPrototypeRevisions,
  rollbackStructuredPrototypePublication,
} from "@/lib/api/prototypes";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type {
  StructuredPrototypePublishedRevision,
  StructuredPrototypeRevisionHistory,
  StructuredPrototypeRevisionSource,
} from "./types";

type ReleaseHistoryFetchState =
  | { kind: "loading" }
  | { kind: "failed"; message: string }
  | { kind: "ready"; history: StructuredPrototypeRevisionHistory };

const SOURCE_LABEL_KEYS: Record<StructuredPrototypeRevisionSource, string> = {
  user: "prototype.structured.history.source.user",
  ai: "prototype.structured.history.source.ai",
  initial_generation: "prototype.structured.history.source.initial_generation",
};

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
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentId: string;
}) {
  const { locale, t } = useI18n();
  const [fetchState, setFetchState] = useState<ReleaseHistoryFetchState>({ kind: "loading" });
  const [selectedRevisionNo, setSelectedRevisionNo] = useState<number | null>(null);
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

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
    void loadHistory();
  }, [open, loadHistory]);

  const revisions: StructuredPrototypePublishedRevision[] =
    fetchState.kind === "ready" ? fetchState.history.revisions : [];
  const currentRevisionNo = fetchState.kind === "ready" ? fetchState.history.currentRevisionNo : null;
  const selected =
    revisions.find((entry) => entry.revisionNo === selectedRevisionNo) ?? revisions[0] ?? null;

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
      await loadHistory();
    } catch (error) {
      setRestoreConfirmOpen(false);
      setRestoreError(error instanceof Error ? error.message : String(error));
    } finally {
      setRestoring(false);
    }
  }, [selected, currentRevisionNo, documentId, loadHistory]);

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
            <ol
              className="flex min-h-0 flex-col gap-2 overflow-y-auto pr-1"
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
            {selected && (
              <div className="flex min-h-0 flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-text-muted">
                    {t("prototype.structured.history.revision", { no: selected.revisionNo })} ·{" "}
                    {formatPublishedAt(locale, selected.publishedAt)}
                  </span>
                  <div className="flex items-center gap-2">
                    {!selected.isCurrent && currentRevisionNo !== null && (
                      <button
                        type="button"
                        className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md bg-brand px-2.5 text-xs font-semibold text-black hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-45"
                        onClick={() => setRestoreConfirmOpen(true)}
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
                <iframe
                  key={selected.artifactPath}
                  className="min-h-0 w-full flex-1 rounded-md border border-border-muted bg-white"
                  src={selected.artifactPath}
                  title={t("prototype.structured.history.preview")}
                  sandbox="allow-scripts allow-same-origin"
                />
              </div>
            )}
          </div>
        )}
        <ConfirmDialog
          open={restoreConfirmOpen}
          onOpenChange={(nextOpen) => {
            if (!restoring) setRestoreConfirmOpen(nextOpen);
          }}
          title={t("prototype.structured.history.restoreTitle")}
          description={t("prototype.structured.history.restoreDescription", {
            no: selected?.revisionNo ?? 0,
          })}
          confirmText={t("prototype.structured.history.restoreConfirm")}
          cancelText={t("prototype.structured.history.restoreCancel")}
          onConfirm={() => void restoreSelected()}
          isLoading={restoring}
          variant="default"
        />
      </DialogContent>
    </Dialog>
  );
}
