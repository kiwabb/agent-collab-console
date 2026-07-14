"use client";

import { ArrowRight, CheckCircle2, GitBranch } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type { StructuredPrototypeDocument } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
}

export function StructuredPrototypeFlow({ document }: Props) {
  const { t } = useI18n();
  const rules = new Map(document.runtime.rules.map((rule) => [rule.id, rule]));
  const pages = new Map(document.pages.map((page) => [page.id, page]));
  return (
    <div className="h-full min-h-0 overflow-auto bg-[#eef1ef] p-5">
      <div className="mx-auto max-w-5xl border border-[#d9dfdc] bg-white">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-[#d9dfdc] px-4">
          <div>
            <h2 className="text-sm font-bold text-[#17201d]">
              {t("prototype.structured.flow.title")}
            </h2>
            <p className="mt-1 text-xs text-[#62706b]">
              {t("prototype.structured.flow.summary", {
                pages: document.pages.length,
                rules: document.flows.length,
              })}
            </p>
          </div>
          <span className="inline-flex items-center gap-2 text-xs font-semibold text-[#237a45]">
            <CheckCircle2 size={15} aria-hidden />
            {t("prototype.structured.flow.valid")}
          </span>
        </header>
        <div className="grid gap-3 p-4 lg:grid-cols-3">
          {document.pages.map((page) => (
            <article key={page.id} className="border border-[#c9d2ce] bg-[#f7f8f7] p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#4f46a5]">
                <GitBranch size={14} aria-hidden />
                {page.route}
              </div>
              <h3 className="mt-2 text-sm font-bold text-[#17201d]">{page.title}</h3>
            </article>
          ))}
        </div>
        <div className="border-t border-[#d9dfdc] p-4">
          <div className="mb-3 text-xs font-bold uppercase text-[#62706b]">
            {t("prototype.structured.flow.rules")}
          </div>
          <div className="grid gap-2">
            {document.flows.map((flow) => {
              const rule = rules.get(flow.ruleId);
              const target = flow.toPageId ? pages.get(flow.toPageId) : null;
              return (
                <article
                  key={flow.id}
                  className="grid items-center gap-3 border border-[#d9dfdc] bg-white p-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-[#17201d]">
                      {rule?.key ?? flow.key}
                    </div>
                    <div className="mt-1 truncate font-mono text-[10px] text-[#62706b]">
                      {flow.fromNodeId}
                    </div>
                  </div>
                  <ArrowRight size={18} className="text-[#4f46a5]" aria-hidden />
                  <div className="min-w-0 text-sm font-semibold text-[#17201d]">
                    {target?.title ?? t("prototype.structured.flow.samePage")}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
