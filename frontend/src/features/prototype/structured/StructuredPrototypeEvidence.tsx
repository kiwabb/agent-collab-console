"use client";

import { CheckCircle2, CircleAlert, Database, Hash, PackageCheck } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type {
  StructuredPrototypeDraft,
  StructuredPrototypePublication,
  StructuredPrototypeRuntimeSession,
} from "./types";

interface Props {
  draft: StructuredPrototypeDraft;
  runtime: StructuredPrototypeRuntimeSession;
  publication: StructuredPrototypePublication | null;
  error: string | null;
}

function shortHash(hash: string): string {
  return hash.length <= 22 ? hash : `${hash.slice(0, 15)}…${hash.slice(-6)}`;
}

export function StructuredPrototypeEvidence({ draft, runtime, publication, error }: Props) {
  const { t } = useI18n();
  return (
    <div className="grid gap-3 p-4">
      {error && (
        <div className="flex gap-2 rounded-lg border border-failed-ring bg-failed-bg p-3 text-xs leading-5 text-status-failed">
          <CircleAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}
      <div className="flex items-center gap-2 text-xs font-semibold text-status-done">
        <CheckCircle2 size={15} aria-hidden />
        {t("prototype.structured.evidence.persisted")}
      </div>
      <dl className="grid gap-3 text-xs">
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-3">
          <dt className="flex items-center gap-2 font-semibold text-text-muted">
            <Database size={13} aria-hidden />
            {t("prototype.structured.evidence.draft")}
          </dt>
          <dd className="mt-2 text-foreground">seq {draft.headSequenceNo}</dd>
          <dd className="mt-1 font-mono text-[10px] text-text-muted">
            {shortHash(draft.documentHash)}
          </dd>
        </div>
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-3">
          <dt className="flex items-center gap-2 font-semibold text-text-muted">
            <Hash size={13} aria-hidden />
            {t("prototype.structured.evidence.runtime")}
          </dt>
          <dd className="mt-2 text-foreground">seq {runtime.headSequenceNo}</dd>
          <dd className="mt-1 font-mono text-[10px] text-text-muted">
            {shortHash(runtime.stateHash)}
          </dd>
          <dd className="mt-1 font-mono text-[10px] text-text-muted">
            {shortHash(runtime.viewModelHash)}
          </dd>
        </div>
        <div className="rounded-lg border border-border-subtle bg-surface-raised p-3">
          <dt className="font-semibold text-text-muted">
            {t("prototype.structured.evidence.checkpoint")}
          </dt>
          <dd className="mt-2 text-foreground">seq {runtime.checkpointSequenceNo}</dd>
          <dd className="mt-1 truncate font-mono text-[10px] text-text-muted">
            {runtime.checkpointId}
          </dd>
        </div>
        {publication && (
          <div className="rounded-lg border border-done-ring bg-done-bg p-3">
            <dt className="flex items-center gap-2 font-semibold text-status-done">
              <PackageCheck size={13} aria-hidden />
              {t("prototype.structured.evidence.publication")}
            </dt>
            <dd className="mt-2 text-foreground">
              {t("prototype.structured.evidence.revision", {
                revision: publication.revisionNo,
              })}
            </dd>
            <dd className="mt-1 text-[10px] text-text-muted">{publication.rendererVersion}</dd>
            <dd className="mt-1 font-mono text-[10px] text-text-muted">
              {shortHash(publication.outputHash)}
            </dd>
            <dd className="mt-1 truncate font-mono text-[10px] text-text-muted">
              {publication.artifactId}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
