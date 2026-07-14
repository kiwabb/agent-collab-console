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
        <div className="flex gap-2 border border-[#e4a8b2] bg-[#fff1f3] p-3 text-xs leading-5 text-[#8c1d31]">
          <CircleAlert size={15} className="mt-0.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}
      <div className="flex items-center gap-2 text-xs font-semibold text-[#237a45]">
        <CheckCircle2 size={15} aria-hidden />
        {t("prototype.structured.evidence.persisted")}
      </div>
      <dl className="grid gap-3 text-xs">
        <div className="border border-[#d9dfdc] bg-[#f7f8f7] p-3">
          <dt className="flex items-center gap-2 font-semibold text-[#62706b]">
            <Database size={13} aria-hidden />
            {t("prototype.structured.evidence.draft")}
          </dt>
          <dd className="mt-2 text-[#17201d]">seq {draft.headSequenceNo}</dd>
          <dd className="mt-1 font-mono text-[10px] text-[#62706b]">
            {shortHash(draft.documentHash)}
          </dd>
        </div>
        <div className="border border-[#d9dfdc] bg-[#f7f8f7] p-3">
          <dt className="flex items-center gap-2 font-semibold text-[#62706b]">
            <Hash size={13} aria-hidden />
            {t("prototype.structured.evidence.runtime")}
          </dt>
          <dd className="mt-2 text-[#17201d]">seq {runtime.headSequenceNo}</dd>
          <dd className="mt-1 font-mono text-[10px] text-[#62706b]">
            {shortHash(runtime.stateHash)}
          </dd>
          <dd className="mt-1 font-mono text-[10px] text-[#62706b]">
            {shortHash(runtime.viewModelHash)}
          </dd>
        </div>
        <div className="border border-[#d9dfdc] bg-[#f7f8f7] p-3">
          <dt className="font-semibold text-[#62706b]">
            {t("prototype.structured.evidence.checkpoint")}
          </dt>
          <dd className="mt-2 text-[#17201d]">seq {runtime.checkpointSequenceNo}</dd>
          <dd className="mt-1 truncate font-mono text-[10px] text-[#62706b]">
            {runtime.checkpointId}
          </dd>
        </div>
        {publication && (
          <div className="border border-[#b7d3c7] bg-[#f2f8f5] p-3">
            <dt className="flex items-center gap-2 font-semibold text-[#237a45]">
              <PackageCheck size={13} aria-hidden />
              {t("prototype.structured.evidence.publication")}
            </dt>
            <dd className="mt-2 text-[#17201d]">
              {t("prototype.structured.evidence.revision", {
                revision: publication.revisionNo,
              })}
            </dd>
            <dd className="mt-1 text-[10px] text-[#62706b]">{publication.rendererVersion}</dd>
            <dd className="mt-1 font-mono text-[10px] text-[#62706b]">
              {shortHash(publication.outputHash)}
            </dd>
            <dd className="mt-1 truncate font-mono text-[10px] text-[#62706b]">
              {publication.artifactId}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
