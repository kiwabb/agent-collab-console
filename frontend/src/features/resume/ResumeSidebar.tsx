"use client";

import type { ChangeEvent, Ref } from "react";
import { Upload } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import type { ProjectResume, ProjectResumeImport } from "@/lib/api/resume";
import { useI18n } from "@/providers/I18nProvider";
import { formatByteCount, type ResumeStats } from "./resumeStats";

interface Props {
  fileInputRef: Ref<HTMLInputElement>;
  importDraft: ProjectResumeImport | null;
  importing: boolean;
  projectId: string | null;
  resume: ProjectResume | null;
  saving: boolean;
  stats: ResumeStats;
  updatedAtLabel: string;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onImportClick: () => void;
}

export function ResumeSidebar({
  fileInputRef,
  importDraft,
  importing,
  projectId,
  resume,
  saving,
  stats,
  updatedAtLabel,
  onFileChange,
  onImportClick,
}: Props) {
  const { t } = useI18n();

  return (
    <aside className="flex min-h-0 flex-col gap-4">
      <section className="enterprise-card rounded-2xl p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">{t("resume.importTitle")}</h2>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">
              {t("resume.importStatus")}
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={onFileChange}
          />
          <button
            type="button"
            onClick={onImportClick}
            disabled={!projectId || importing || saving}
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-sm font-medium transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {importing ? <AgentThinkingIndicator phase="tool" size={15} /> : <Upload size={15} />}
            {importing ? t("resume.importing") : t("resume.importPdf")}
          </button>
        </div>
        {importDraft && (
          <div className="mt-4 rounded-xl border border-brand/25 bg-brand/10 p-3 text-xs">
            <div className="flex items-start gap-2">
              <Upload size={15} className="mt-0.5 shrink-0 text-brand" aria-hidden />
              <div className="min-w-0">
                <div className="truncate font-medium text-brand">{importDraft.source_filename}</div>
                <div className="mt-1 text-text-muted">
                  {t("resume.importSummary", {
                    pages: importDraft.extracted_pages,
                    total: importDraft.page_count,
                  })}
                </div>
                <div className="mt-1 text-text-muted">
                  {t("resume.importDetail", {
                    size: formatByteCount(importDraft.size_bytes),
                  })}
                </div>
              </div>
            </div>
            {importDraft.warnings.length > 0 && (
              <div className="mt-3 rounded-lg border border-status-awaiting/20 bg-status-awaiting/10 p-2">
                <div className="mb-1 font-medium text-status-awaiting">
                  {t("resume.importWarnings")}
                </div>
                <ul className="list-disc space-y-1 pl-4 text-status-awaiting">
                  {importDraft.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="enterprise-card rounded-2xl p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">{t("resume.documentTitle")}</h2>
          <span className="rounded-full border border-border-subtle bg-surface-input/55 px-2 py-1 text-[11px] text-text-muted">
            {resume?.exists ? t("resume.savedDocument") : t("resume.currentDraft")}
          </span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <Metric label={t("resume.metric.characters")} value={stats.characters.toLocaleString()} />
          <Metric label={t("resume.metric.words")} value={stats.words.toLocaleString()} />
          <Metric label={t("resume.metric.lines")} value={stats.lines.toLocaleString()} />
          <Metric label={t("resume.metric.size")} value={formatByteCount(stats.sizeBytes)} />
        </dl>
        <div className="mt-4 space-y-2 text-xs text-text-muted">
          <InfoRow
            label={t("resume.path")}
            value={resume?.relative_path ?? ".agent-collab/resume.md"}
          />
          <InfoRow label={t("resume.updatedAt")} value={updatedAtLabel} />
        </div>
      </section>
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface-input/55 p-2.5">
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd className="mt-1 font-mono text-sm text-foreground">{value}</dd>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0">{label}</span>
      <span className="min-w-0 break-words text-right text-foreground">{value}</span>
    </div>
  );
}
