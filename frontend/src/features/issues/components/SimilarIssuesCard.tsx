"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GitBranch, Sparkles } from "lucide-react";
import { getSimilarIssues, type SimilarIssue } from "@/lib/api";
import { useI18n } from "@/providers/I18nProvider";

export function SimilarIssuesCard({ issueId }: { issueId: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const [items, setItems] = useState<SimilarIssue[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSimilarIssues(issueId, 5)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [issueId]);

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface overflow-hidden">
      <div className="px-4 py-3.5 flex items-center gap-2.5 border-b border-border-subtle">
        <Sparkles size={14} className="text-brand" />
        <span className="text-[13px] font-semibold">{t("issue.similar")}</span>
      </div>
      {loading ? (
        <div className="px-4 py-3 text-[12px] text-text-muted">…</div>
      ) : items.length === 0 ? (
        <div className="px-4 py-3 text-[12px] text-text-muted">
          {t("issue.similarEmpty")}
        </div>
      ) : (
        <ul className="px-2 pb-2">
          {items.map((it) => (
            <li key={it.issue_id}>
              <button
                type="button"
                onClick={() => router.push(`/issues/${it.issue_id}`)}
                className="w-full text-left px-2 py-1.5 rounded-md hover:bg-surface-hover flex items-start gap-2"
              >
                <GitBranch size={12} className="mt-1 text-text-muted shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px]">{it.title || it.issue_id}</div>
                  {typeof it.score === "number" && (
                    <div className="text-[10px] font-mono text-text-muted">
                      {it.source ? `${it.source} · ` : ""}
                      {it.score.toFixed(3)}
                    </div>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
