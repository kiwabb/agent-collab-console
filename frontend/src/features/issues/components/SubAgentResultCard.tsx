"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

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

function StatusBadgeSmall({ status }: { status: string }) {
  let cls = "bg-surface-raised text-text-muted border border-border-subtle";
  if (status === "done" || status === "completed") {
    cls = "bg-success/10 text-success border border-success/30";
  } else if (status === "failed") {
    cls = "bg-destructive/10 text-destructive border border-destructive/30";
  }
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {status}
    </span>
  );
}

function KindBadge({ taskKind }: { taskKind: string }) {
  const label = taskKind === "specialist_child" ? "Specialist" : taskKind;
  return (
    <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-raised border border-border-subtle text-text-muted uppercase tracking-wide">
      {label}
    </span>
  );
}

export function SubAgentResultCard({ result }: Props) {
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [artifactExpanded, setArtifactExpanded] = useState(false);
  const [artifactShowAll, setArtifactShowAll] = useState(false);

  const roleLabel = ROLE_LABEL[result.role] ?? result.role;
  const artifactText = result.artifact_json
    ? JSON.stringify(result.artifact_json, null, 2)
    : null;
  const artifactPreview = artifactText
    ? artifactShowAll
      ? artifactText
      : artifactText.slice(0, 400)
    : null;

  const updatedAt = result.updated_at
    ? new Date(result.updated_at).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="rounded-xl border border-border-subtle bg-surface-raised px-4 py-3 flex flex-col gap-2">
      {/* Header row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold text-brand uppercase tracking-wider">
          {roleLabel}
        </span>
        <StatusBadgeSmall status={result.status} />
        <KindBadge taskKind={result.task_kind} />
        {result.parent_task_id && (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
            ↑ specialist
          </span>
        )}
        {updatedAt && (
          <span className="ml-auto text-[10px] text-text-muted font-mono">{updatedAt}</span>
        )}
      </div>

      {/* Title */}
      {result.title && (
        <p className="text-[13px] font-medium text-foreground leading-snug">{result.title}</p>
      )}

      {/* Summary */}
      {result.summary && (
        <div>
          <p
            className={`text-[12px] text-text-secondary leading-relaxed whitespace-pre-wrap ${!summaryExpanded ? "line-clamp-3" : ""}`}
          >
            {result.summary}
          </p>
          {result.summary.length > 200 && (
            <button
              type="button"
              onClick={() => setSummaryExpanded((v) => !v)}
              className="mt-1 flex items-center gap-1 text-[11px] text-brand hover:text-brand-strong"
            >
              {summaryExpanded ? (
                <>
                  <ChevronUp size={12} /> Show less
                </>
              ) : (
                <>
                  <ChevronDown size={12} /> Show more
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Artifact JSON */}
      {artifactText && (
        <div>
          <button
            type="button"
            onClick={() => setArtifactExpanded((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-text-muted hover:text-foreground"
          >
            {artifactExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Artifact JSON
          </button>
          {artifactExpanded && (
            <div className="mt-1.5">
              <pre className="text-[11px] font-mono bg-background border border-border-subtle rounded p-2 overflow-x-auto whitespace-pre-wrap break-all text-text-secondary">
                {artifactPreview}
                {!artifactShowAll && artifactText.length > 400 && "…"}
              </pre>
              {artifactText.length > 400 && (
                <button
                  type="button"
                  onClick={() => setArtifactShowAll((v) => !v)}
                  className="mt-1 text-[11px] text-brand hover:text-brand-strong"
                >
                  {artifactShowAll ? "Show less" : "Show more"}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
