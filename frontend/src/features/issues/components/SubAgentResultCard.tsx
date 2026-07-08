"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, FileJson2, CheckCircle2, XCircle, Clock3 } from "lucide-react";

const ROLE_LABEL: Record<string, string> = {
  conductor: "Conductor",
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  engineer_frontend: "FE Engineer",
  engineer_backend: "BE Engineer",
  qa: "QA",
  "specialist:security_reviewer": "Security",
  "specialist:performance_reviewer": "Performance",
  "specialist:doc_writer": "Doc Writer",
  "specialist:code_reviewer": "Code Reviewer",
  "specialist:migration_planner": "Migration",
  "specialist:dependency_auditor": "Dep Auditor",
  "specialist:api_contract_checker": "API Contract",
  "specialist:accessibility_reviewer": "A11y",
  "specialist:i18n_checker": "i18n",
  "specialist:log_summarizer": "Log Summarizer",
};

const STATUS_CONFIG: Record<
  string,
  { icon: typeof CheckCircle2; color: string; bg: string; border: string }
> = {
  done: {
    icon: CheckCircle2,
    color: "var(--color-status-done)",
    bg: "var(--color-done-bg)",
    border: "var(--color-done-ring)",
  },
  completed: {
    icon: CheckCircle2,
    color: "var(--color-status-done)",
    bg: "var(--color-done-bg)",
    border: "var(--color-done-ring)",
  },
  failed: {
    icon: XCircle,
    color: "var(--color-status-failed)",
    bg: "var(--color-failed-bg)",
    border: "var(--color-failed-ring)",
  },
};

interface SubAgentResult {
  task_id: string;
  role: string;
  title: string;
  status: string;
  task_kind: string;
  parent_task_id: string | null;
  summary: string;
  artifact_json: Record<string, unknown> | null;
  updated_at: string | null;
}

interface Props {
  result: SubAgentResult;
}

export function SubAgentResultCard({ result }: Props) {
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [artifactExpanded, setArtifactExpanded] = useState(false);
  const [artifactShowAll, setArtifactShowAll] = useState(false);

  const roleLabel = ROLE_LABEL[result.role] ?? result.role;
  const artifactText = result.artifact_json ? JSON.stringify(result.artifact_json, null, 2) : null;
  const artifactPreview = artifactText
    ? artifactShowAll
      ? artifactText
      : artifactText.slice(0, 600)
    : null;

  const updatedAt = result.updated_at
    ? new Date(result.updated_at).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  const statusCfg = STATUS_CONFIG[result.status] ?? {
    icon: Clock3,
    color: "var(--color-text-muted)",
    bg: "var(--color-surface-raised)",
    border: "var(--color-border-subtle)",
  };
  const StatusIcon = statusCfg.icon;

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface-raised/60 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3.5 flex items-center gap-3 border-b border-border-subtle bg-surface/60">
        <span
          className="inline-flex size-7 items-center justify-center rounded-xl shrink-0"
          style={{
            backgroundColor: statusCfg.bg,
            color: statusCfg.color,
            boxShadow: `0 0 0 2px ${statusCfg.border}`,
          }}
        >
          <StatusIcon size={14} strokeWidth={2.5} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-[11px] font-black uppercase tracking-[0.12em]"
              style={{ color: statusCfg.color }}
            >
              {roleLabel}
            </span>
            <span
              className="inline-flex px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wide border"
              style={{
                color: statusCfg.color,
                borderColor: statusCfg.border,
                backgroundColor: statusCfg.bg,
              }}
            >
              {result.status}
            </span>
            {result.task_kind && result.task_kind !== "default" && (
              <span className="inline-flex px-1.5 py-0.5 rounded-md text-[9px] font-medium bg-surface-input border border-border-subtle text-text-muted uppercase tracking-wide">
                {result.task_kind === "specialist_child" ? "Specialist" : result.task_kind}
              </span>
            )}
            {result.parent_task_id && (
              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[9px] font-medium bg-brand/8 text-brand border border-brand/20">
                ↑ specialist
              </span>
            )}
          </div>
        </div>
        {updatedAt && (
          <span className="text-[10px] text-text-faint font-mono shrink-0">{updatedAt}</span>
        )}
      </div>

      {/* Body */}
      <div className="px-4 py-4 flex flex-col gap-3">
        {/* Title */}
        {result.title && (
          <h4 className="text-[14px] font-bold text-foreground leading-snug tracking-tight">
            {result.title}
          </h4>
        )}

        {/* Summary */}
        {result.summary && (
          <div>
            <p
              className={`text-[13px] text-text-secondary leading-relaxed whitespace-pre-wrap ${!summaryExpanded ? "line-clamp-4" : ""}`}
            >
              {result.summary}
            </p>
            {result.summary.length > 200 && (
              <button
                type="button"
                onClick={() => setSummaryExpanded((v) => !v)}
                className="mt-2 flex items-center gap-1.5 text-[12px] font-semibold text-brand hover:text-brand-strong transition-colors"
              >
                {summaryExpanded ? (
                  <>
                    <ChevronUp size={13} /> Show less
                  </>
                ) : (
                  <>
                    <ChevronDown size={13} /> Show more
                  </>
                )}
              </button>
            )}
          </div>
        )}

        {/* Artifact JSON */}
        {artifactText && (
          <div className="mt-1">
            <button
              type="button"
              onClick={() => setArtifactExpanded((v) => !v)}
              className="flex items-center gap-2 text-[12px] font-semibold text-text-muted hover:text-foreground transition-colors group"
            >
              <FileJson2
                size={13}
                className="text-text-faint group-hover:text-brand transition-colors"
              />
              {artifactExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              <span>Artifact JSON</span>
            </button>
            {artifactExpanded && (
              <div className="mt-2.5">
                <pre className="text-[11px] font-mono bg-background/50 border border-border-subtle rounded-xl p-3.5 overflow-x-auto whitespace-pre-wrap break-all text-text-secondary leading-relaxed max-h-96 overflow-y-auto">
                  {artifactPreview}
                  {!artifactShowAll && artifactText.length > 600 && "…"}
                </pre>
                {artifactText.length > 600 && (
                  <button
                    type="button"
                    onClick={() => setArtifactShowAll((v) => !v)}
                    className="mt-2 text-[12px] font-semibold text-brand hover:text-brand-strong transition-colors"
                  >
                    {artifactShowAll
                      ? "Show less"
                      : `Show all (${Math.round(artifactText.length / 1024)}KB)`}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
