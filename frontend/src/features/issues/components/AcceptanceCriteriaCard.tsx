"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, CheckCircle2, Circle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { confirmIssueAcceptanceCriteria, type IssueChecklist } from "@/lib/api/issues";
import { parseAcceptanceCriteriaInput } from "@/lib/acceptanceCriteria";
import type { CodexIssue } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  issue: CodexIssue | null;
  checklist: IssueChecklist | null;
  onIssueUpdated: (issue: CodexIssue) => void;
}

function normalizedCriterion(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

export function AcceptanceCriteriaCard({ issue, checklist, onIssueUpdated }: Props) {
  const { t } = useI18n();
  const issueCriteriaText = issue?.acceptance_criteria.join("\n") ?? "";
  const [draft, setDraft] = useState(issueCriteriaText);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) setDraft(issueCriteriaText);
  }, [dirty, issueCriteriaText]);

  const criteria = useMemo(() => {
    const checklistByText = new Map(
      (checklist?.criteria ?? []).map((criterion) => [
        normalizedCriterion(criterion.text),
        criterion,
      ]),
    );
    if (issue && issue.acceptance_criteria.length > 0) {
      return issue.acceptance_criteria.map((text) => {
        const match = checklistByText.get(normalizedCriterion(text));
        return { text, covered: match?.covered ?? false, source: match?.source ?? null };
      });
    }
    return checklist?.criteria ?? [];
  }, [checklist, issue]);
  const covered = criteria.filter((criterion) => criterion.covered).length;
  const percent = criteria.length > 0 ? Math.round((covered / criteria.length) * 100) : 0;
  const confirmed = issue?.acceptance_criteria_confirmed === true;

  const handleConfirm = async () => {
    if (!issue || saving) return;
    const acceptanceCriteria = parseAcceptanceCriteriaInput(draft);
    if (acceptanceCriteria.length === 0) {
      setError(t("issue.side.acceptanceCriteriaRequired"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await confirmIssueAcceptanceCriteria(issue.id, acceptanceCriteria);
      setDraft(updated.acceptance_criteria.join("\n"));
      setDirty(false);
      onIssueUpdated(updated);
    } catch (cause) {
      console.error("acceptance criteria confirmation failed:", cause);
      setError(cause instanceof Error ? cause.message : t("issue.side.acceptanceConfirmFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="overflow-hidden border-b border-border-subtle bg-surface">
      <header className="flex items-center gap-2 border-b border-border-subtle/60 bg-surface-input/30 px-3 py-2.5">
        <CheckCircle2 size={15} className="shrink-0 text-status-done" aria-hidden />
        <h3 className="text-[13px] font-bold tracking-wide text-foreground">
          {t("issue.side.acceptance")}
        </h3>
        <span
          className={cn(
            "ml-auto rounded border px-2 py-0.5 font-mono text-[9px] font-black uppercase tracking-wider",
            confirmed
              ? "border-status-done/25 bg-status-done/10 text-status-done"
              : "border-status-awaiting/25 bg-status-awaiting/10 text-status-awaiting",
          )}
        >
          {confirmed ? t("issue.side.acceptanceConfirmed") : t("issue.side.acceptancePending")}
        </span>
      </header>

      <div className="m-2.5 flex items-center gap-3 rounded-lg border border-border-subtle/50 bg-surface-input/30 px-3 py-2.5">
        <span className="font-mono text-[20px] font-black leading-none tracking-tight text-foreground tabular-nums">
          {covered}
          <em className="text-sm font-normal not-italic text-text-muted">/{criteria.length}</em>
        </span>
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-input">
          <span
            className="block h-full rounded-full bg-status-done"
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className="rounded border border-status-done/20 bg-status-done/10 px-1.5 py-0.5 font-mono text-[11px] font-bold text-status-done tabular-nums">
          {percent}%
        </span>
      </div>

      {criteria.length > 0 && (
        <ul className="flex flex-col gap-0.5 px-1.5 pb-3">
          {criteria.map((criterion, index) => (
            <li
              key={`${criterion.text}:${index}`}
              className="flex items-start gap-2.5 rounded-md px-3 py-2.5"
            >
              <span
                className={cn(
                  "mt-px flex size-[18px] shrink-0 items-center justify-center rounded-full border",
                  criterion.covered
                    ? "border-status-done/20 bg-status-done/10 text-status-done"
                    : "border-border-subtle/40 bg-surface-input text-text-muted",
                )}
              >
                {criterion.covered ? (
                  <CheckCircle2 size={11} strokeWidth={3} aria-hidden />
                ) : (
                  <Circle size={11} strokeWidth={2.5} aria-hidden />
                )}
              </span>
              <span className="text-[13px] leading-snug text-foreground">{criterion.text}</span>
            </li>
          ))}
        </ul>
      )}

      {issue && !confirmed && (
        <div className="border-t border-border-subtle/60 p-3">
          <textarea
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setDirty(true);
              setError(null);
            }}
            rows={Math.max(3, Math.min(7, parseAcceptanceCriteriaInput(draft).length + 1))}
            aria-label={t("issue.side.acceptance")}
            placeholder={t("issue.side.acceptancePlaceholder")}
            className="w-full resize-y rounded-md border border-border-subtle/60 bg-surface-input/50 px-3 py-2 font-mono text-[12px] leading-5 text-foreground outline-none placeholder:text-text-faint focus:border-brand/60"
          />
          {error && (
            <p role="alert" className="mt-2 text-[11px] text-status-failed">
              {error}
            </p>
          )}
          <div className="mt-2 flex justify-end">
            <Button size="sm" onClick={() => void handleConfirm()} disabled={saving}>
              <Check size={14} aria-hidden />
              {saving ? t("issue.side.acceptanceConfirming") : t("issue.side.acceptanceConfirm")}
            </Button>
          </div>
        </div>
      )}

      {!issue && criteria.length === 0 && (
        <p className="px-4 pb-4 text-[12px] text-text-muted">{t("issue.side.acceptanceEmpty")}</p>
      )}
    </section>
  );
}
