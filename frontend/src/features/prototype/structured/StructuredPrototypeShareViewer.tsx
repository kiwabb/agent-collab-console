"use client";

import { useEffect, useMemo, useState } from "react";

import { listStructuredPrototypeRevisions } from "@/lib/api/prototypes";
import { useI18n } from "@/providers/I18nProvider";

import type { StructuredPrototypePublishedRevision } from "./types";

function shareRevisionOptionLabel(
  locale: string,
  entry: StructuredPrototypePublishedRevision,
  currentLabel: string,
): string {
  const parsed = new Date(entry.publishedAt);
  const stamp = Number.isNaN(parsed.getTime())
    ? entry.publishedAt
    : parsed.toLocaleString(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
  const suffix = entry.isCurrent ? ` · ${currentLabel}` : "";
  return `v${entry.revisionNo} · ${stamp}${suffix}`;
}

export function StructuredPrototypeShareViewer({ documentId }: { documentId: string }) {
  const { locale, t } = useI18n();
  const [revisions, setRevisions] = useState<StructuredPrototypePublishedRevision[]>([]);
  const [selectedRevisionNo, setSelectedRevisionNo] = useState<number | null>(null);
  const [historyEmpty, setHistoryEmpty] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listStructuredPrototypeRevisions(documentId)
      .then((history) => {
        if (cancelled) return;
        setRevisions(history.revisions);
        setSelectedRevisionNo(history.currentRevisionNo);
        setHistoryEmpty(history.revisions.length === 0);
      })
      .catch(() => {
        // Viewers without history access keep the plain current publication.
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const currentPath = `/api/structured-prototype-public/${encodeURIComponent(documentId)}/current/index.html`;
  const selected = useMemo(
    () => revisions.find((entry) => entry.revisionNo === selectedRevisionNo) ?? null,
    [revisions, selectedRevisionNo],
  );
  const viewingArchived = selected !== null && !selected.isCurrent;
  const source = viewingArchived ? selected.artifactPath : currentPath;
  const currentRevisionNo = revisions.find((entry) => entry.isCurrent)?.revisionNo ?? null;

  return (
    <main className="relative h-dvh w-full overflow-hidden bg-white">
      {revisions.length > 1 && (
        <div className="absolute top-3 right-3 z-10 grid max-w-[min(92vw,26rem)] gap-1.5 rounded-lg border border-black/10 bg-white/95 px-3 py-2 text-xs text-neutral-700 shadow-lg backdrop-blur">
          <div className="flex items-center justify-end gap-2">
            {viewingArchived && (
              <>
                <span className="font-semibold text-amber-700">
                  {t("prototype.structured.share.viewingArchived", { no: selected.revisionNo })}
                </span>
                <button
                  type="button"
                  className="cursor-pointer rounded-md border border-black/15 bg-white px-2 py-1 font-semibold hover:bg-neutral-100"
                  onClick={() => setSelectedRevisionNo(currentRevisionNo)}
                >
                  {t("prototype.structured.share.backToCurrent")}
                </button>
              </>
            )}
            <label className="flex items-center gap-1.5">
              <span className="font-semibold">{t("prototype.structured.share.versionLabel")}</span>
              <select
                className="cursor-pointer rounded-md border border-black/15 bg-white px-1.5 py-1"
                value={selectedRevisionNo ?? ""}
                onChange={(event) => setSelectedRevisionNo(Number(event.target.value))}
              >
                {revisions.map((entry) => (
                  <option key={entry.revisionId} value={entry.revisionNo} title={entry.summary}>
                    {shareRevisionOptionLabel(
                      locale,
                      entry,
                      t("prototype.structured.history.current"),
                    )}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {viewingArchived && selected.summary.length > 0 && (
            <p className="truncate text-right text-[11px] text-neutral-500" title={selected.summary}>
              {selected.summary}
            </p>
          )}
        </div>
      )}
      {historyEmpty ? (
        <div className="grid h-full w-full place-items-center px-6 text-center">
          <div className="grid max-w-sm gap-2">
            <p className="text-base font-semibold text-neutral-700">
              {t("prototype.structured.share.emptyTitle")}
            </p>
            <p className="text-sm text-neutral-500">
              {t("prototype.structured.share.emptyDescription")}
            </p>
          </div>
        </div>
      ) : (
        <iframe
          key={source}
          className="h-full w-full border-0"
          src={source}
          title={t("prototype.structured.share.title")}
          sandbox="allow-scripts allow-same-origin"
        />
      )}
    </main>
  );
}
