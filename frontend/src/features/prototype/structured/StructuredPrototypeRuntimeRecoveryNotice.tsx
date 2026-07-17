"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useI18n } from "@/providers/I18nProvider";

import type { StructuredPrototypeRuntimeRecoveryIssue } from "./structuredPrototypeRuntimeRecovery";

interface Props {
  issue: StructuredPrototypeRuntimeRecoveryIssue;
  hasLastSnapshot: boolean;
  isResetting: boolean;
  resetError: string | null;
  onReset: () => void;
}

export function StructuredPrototypeRuntimeRecoveryNotice({
  issue,
  hasLastSnapshot,
  isResetting,
  resetError,
  onReset,
}: Props) {
  const { t } = useI18n();
  const reason = (() => {
    switch (issue.code) {
      case "runtime_session_corrupt":
        return t("prototype.structured.runtimeRecovery.reason.sessionCorrupt");
      case "runtime_replay_version_mismatch":
        return t("prototype.structured.runtimeRecovery.reason.versionMismatch");
      case "runtime_replay_contract_unsupported":
        return t("prototype.structured.runtimeRecovery.reason.contractUnsupported");
      case "runtime_reset_failed":
        return t("prototype.structured.runtimeRecovery.reason.resetFailed");
    }
  })();

  return (
    <section
      className="border-b border-status-awaiting/35 bg-status-awaiting/10 px-4 py-3 text-foreground"
      role="alert"
      aria-live="polite"
      data-runtime-recovery-reason={issue.code}
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <AlertTriangle className="mt-0.5 shrink-0 text-status-awaiting" size={18} aria-hidden />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">
              {t("prototype.structured.runtimeRecovery.title")}
            </h2>
            <p className="mt-1 text-xs leading-5 text-text-muted">{reason}</p>
            <p className="mt-1 text-xs leading-5 text-text-muted">
              {hasLastSnapshot
                ? t("prototype.structured.runtimeRecovery.lastSnapshot")
                : t("prototype.structured.runtimeRecovery.noSnapshot")}
            </p>
            {resetError !== null && (
              <p className="mt-1 text-xs leading-5 text-status-failed">
                {t("prototype.structured.runtimeRecovery.resetFailed", { message: resetError })}
              </p>
            )}
            {issue.resetEvidence === null && (
              <p className="mt-1 text-xs leading-5 text-status-failed">
                {t("prototype.structured.runtimeRecovery.evidenceUnavailable")}
              </p>
            )}
            {issue.correlationId !== null && (
              <p className="mt-1 truncate font-mono text-[10px] text-text-faint">
                {t("prototype.structured.runtimeRecovery.evidence", {
                  correlationId: issue.correlationId,
                })}
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          className="inline-flex min-h-10 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md border border-status-awaiting/40 bg-surface-raised px-3 text-xs font-semibold text-foreground hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
          onClick={onReset}
          disabled={isResetting || issue.resetEvidence === null}
        >
          {isResetting ? (
            <AgentThinkingIndicator phase="tool" size={14} />
          ) : (
            <RefreshCw size={14} aria-hidden />
          )}
          {isResetting
            ? t("prototype.structured.runtimeRecovery.resetting")
            : t("prototype.structured.runtimeRecovery.reset")}
        </button>
      </div>
    </section>
  );
}
