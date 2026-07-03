"use client";

import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, FileText, RefreshCcw } from "lucide-react";
import { Loader } from "@/components/ui/loader";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  actionError: string | null;
  activeProjectName: string | null;
  error: string | null;
  hasUnsavedChanges: boolean;
  loading: boolean;
  markdown: string;
  projectError: string | null;
  projectId: string | null;
  onMarkdownChange: (markdown: string) => void;
  onRetryLoad: () => void;
  onRetryProjects: () => void;
}

export function ResumeEditorPanel({
  actionError,
  activeProjectName,
  error,
  hasUnsavedChanges,
  loading,
  markdown,
  projectError,
  projectId,
  onMarkdownChange,
  onRetryLoad,
  onRetryProjects,
}: Props) {
  const { t } = useI18n();

  return (
    <section className="enterprise-card flex min-h-[560px] flex-col rounded-2xl p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{t("resume.editorLabel")}</h2>
          <p className="mt-1 truncate text-xs text-text-muted">
            {activeProjectName ?? projectId ?? t("resume.selectProject")}
          </p>
        </div>
        <span
          role="status"
          aria-live="polite"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
            hasUnsavedChanges
              ? "bg-status-awaiting/15 text-status-awaiting"
              : "bg-status-done/15 text-status-done",
          )}
        >
          {hasUnsavedChanges ? (
            <AlertTriangle size={12} aria-hidden />
          ) : (
            <CheckCircle2 size={12} aria-hidden />
          )}
          {hasUnsavedChanges ? t("resume.unsaved") : t("resume.clean")}
        </span>
      </div>

      {actionError && (
        <InlineAlert title={t("resume.actionError")} message={actionError} className="mb-3" />
      )}

      {loading ? (
        <Loader
          variant="card"
          label={t("resume.loading")}
          className="min-h-[420px] border-0 bg-transparent"
        />
      ) : error ? (
        <ErrorPanel
          title={t("resume.loadFailed")}
          message={error}
          buttonLabel={t("resume.retry")}
          onRetry={onRetryLoad}
        />
      ) : !projectId ? (
        projectError ? (
          <ErrorPanel
            title={t("resume.projectLoadFailed")}
            message={projectError}
            buttonLabel={t("resume.retry")}
            onRetry={onRetryProjects}
          />
        ) : (
          <EmptyPanel icon={<FileText size={20} />} text={t("resume.selectProject")} />
        )
      ) : (
        <Textarea
          value={markdown}
          onChange={(event) => onMarkdownChange(event.target.value)}
          placeholder={t("resume.editorPlaceholder")}
          className="min-h-[470px] flex-1 resize-none border-border-subtle bg-surface-input/70 font-mono text-base leading-7 md:text-sm"
          aria-label={t("resume.editorLabel")}
        />
      )}
    </section>
  );
}

function InlineAlert({
  title,
  message,
  className,
}: {
  title: string;
  message: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-xl border border-status-failed/25 bg-status-failed/10 p-3 text-sm text-status-failed",
        className,
      )}
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div className="mt-1 break-words text-xs opacity-90">{message}</div>
      </div>
    </div>
  );
}

function ErrorPanel({
  title,
  message,
  buttonLabel,
  onRetry,
}: {
  title: string;
  message: string;
  buttonLabel: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex min-h-[420px] items-center justify-center rounded-xl border border-status-failed/25 bg-status-failed/10 p-6 text-sm text-status-failed"
    >
      <div className="max-w-md text-center">
        <AlertTriangle size={24} className="mx-auto mb-3" aria-hidden />
        <div className="font-semibold">{title}</div>
        <div className="mt-2 break-words text-xs opacity-90">{message}</div>
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-status-failed/30 bg-status-failed/10 px-4 text-sm font-medium transition-colors hover:bg-status-failed/15"
        >
          <RefreshCcw size={15} aria-hidden />
          {buttonLabel}
        </button>
      </div>
    </div>
  );
}

function EmptyPanel({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border-subtle p-6 text-center text-sm text-text-muted">
      <div className="flex size-11 items-center justify-center rounded-xl border border-border-subtle bg-surface-input/55">
        {icon}
      </div>
      <span>{text}</span>
    </div>
  );
}
