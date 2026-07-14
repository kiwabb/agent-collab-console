"use client";

import { AlertTriangle, Braces, ChevronRight, FileCode2, Link2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { Locale } from "@/lib/i18n";
import type { PrototypePlanItem } from "@/lib/types";
import {
  boundedPrototypeEvidenceExcerpt,
  prototypeDiagnosticMessage,
  prototypeEvidenceDetailMessage,
  prototypeEvidenceKindKey,
} from "./prototypePlanReviewState";

interface Props {
  item: PrototypePlanItem;
  locale: Locale;
  t: (key: string, params?: Record<string, string | number>) => string;
}

export function PrototypeEvidenceList({ item, locale, t }: Props) {
  return (
    <Sheet>
      <SheetTrigger
        render={
          <button
            type="button"
            className="mt-2 flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 rounded-md border border-border-subtle bg-surface-base px-3 py-2 text-left text-xs text-foreground transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
          />
        }
      >
        <span className="flex min-w-0 items-center gap-2 font-medium">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-sm bg-brand/10 text-brand">
            <FileCode2 size={15} aria-hidden="true" />
          </span>
          <span>{t("prototype.plan.evidenceCount", { count: item.evidence.length })}</span>
        </span>
        <ChevronRight className="shrink-0 text-text-muted" size={16} aria-hidden="true" />
      </SheetTrigger>
      <SheetContent
        side="right"
        className="w-[calc(100vw-1rem)] gap-0 p-0 sm:w-[min(720px,calc(100vw-2rem))]"
      >
        <SheetHeader className="shrink-0 border-b border-border-subtle px-5 py-4 pr-12">
          <SheetTitle className="flex items-center gap-2 text-base">
            <FileCode2 className="text-brand" size={18} aria-hidden="true" />
            {t("prototype.plan.evidenceCount", { count: item.evidence.length })}
          </SheetTitle>
          <SheetDescription className="break-words text-xs text-text-muted">
            {item.title} · {item.route_patterns.join(", ") || "-"}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
          {item.evidence.length === 0 ? (
            <p className="rounded-md border border-dashed border-border-subtle px-3 py-8 text-center text-text-muted">
              {t("prototype.plan.evidenceEmpty")}
            </p>
          ) : (
            <ol className="space-y-3">
              {item.evidence.map((evidence) => {
                const kindKey = prototypeEvidenceKindKey(evidence.kind);
                const detail =
                  evidence.detail && evidence.detail !== evidence.diagnostic
                    ? prototypeEvidenceDetailMessage(evidence.detail, locale)
                    : null;
                const diagnostic = evidence.diagnostic
                  ? prototypeDiagnosticMessage(evidence.diagnostic, locale)
                  : null;
                const excerpt = boundedPrototypeEvidenceExcerpt(evidence.content);
                const referenceIndex = item.evidence_ids.indexOf(evidence.evidence_id);
                return (
                  <li
                    key={evidence.evidence_id}
                    className="min-w-0 overflow-hidden rounded-md border border-border-subtle bg-surface-raised/50"
                  >
                    <header className="flex min-w-0 flex-wrap items-center gap-1.5 border-b border-border-subtle px-3 py-2.5">
                      <Badge variant="outline" className="bg-surface-base">
                        {t(kindKey)}
                      </Badge>
                      <Badge variant={evidence.confidence === "low" ? "destructive" : "secondary"}>
                        {t("prototype.plan.evidenceConfidence", {
                          confidence: t(`prototype.plan.confidence.${evidence.confidence}`),
                        })}
                      </Badge>
                      {referenceIndex >= 0 && (
                        <span className="ml-auto inline-flex items-center gap-1 text-text-muted">
                          <Link2 size={12} aria-hidden="true" />
                          {t("prototype.plan.evidenceReferenced", { index: referenceIndex + 1 })}
                        </span>
                      )}
                    </header>
                    <div className="space-y-3 px-3 py-3">
                      <div className="flex min-w-0 items-start gap-2 rounded-sm bg-surface-base px-2.5 py-2 font-mono text-[12px] leading-relaxed text-foreground">
                        <FileCode2
                          className="mt-0.5 shrink-0 text-text-muted"
                          size={13}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 break-all">
                          {evidence.path}
                          <span className="text-text-muted">
                            :{evidence.start_line}
                            {evidence.end_line !== evidence.start_line
                              ? `-${evidence.end_line}`
                              : ""}
                          </span>
                        </span>
                      </div>
                      {detail && (
                        <p className="break-words text-[13px] leading-relaxed text-text-muted">
                          {t(detail.key, detail.params)}
                        </p>
                      )}
                      {diagnostic && (
                        <div className="flex min-w-0 items-start gap-2 rounded-sm border border-status-awaiting/30 bg-status-awaiting/5 px-2.5 py-2 text-status-awaiting">
                          <AlertTriangle className="mt-0.5 shrink-0" size={14} aria-hidden="true" />
                          <div className="min-w-0 break-words text-[12px] leading-relaxed">
                            <span className="font-semibold">
                              {t("prototype.plan.evidenceDiagnostic")}:
                            </span>{" "}
                            {t(diagnostic.key, diagnostic.params)}
                          </div>
                        </div>
                      )}
                      {excerpt.text && (
                        <div className="min-w-0">
                          <div className="mb-1.5 flex items-center gap-1.5 font-medium text-text-muted">
                            <Braces size={13} aria-hidden="true" />
                            {t("prototype.plan.evidenceExcerpt")}
                          </div>
                          <pre className="max-h-48 max-w-full overflow-auto whitespace-pre-wrap rounded-sm border border-border-subtle bg-surface-base px-3 py-2.5 font-mono text-[12px] leading-relaxed text-foreground [overflow-wrap:anywhere]">
                            {excerpt.text}
                          </pre>
                          {excerpt.truncated && (
                            <p className="mt-1.5 text-text-muted">
                              {t("prototype.plan.evidenceExcerptTruncated")}
                            </p>
                          )}
                        </div>
                      )}
                      <div className="break-all border-t border-border-subtle pt-2 font-mono text-xs text-text-muted">
                        {t("prototype.plan.evidenceId")}: {evidence.evidence_id}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
