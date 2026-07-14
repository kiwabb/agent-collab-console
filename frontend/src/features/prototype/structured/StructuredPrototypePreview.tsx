"use client";

import { Menu, UserRound } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { PrototypeRuntimeState, RuntimeEntity, RuntimeViewModel } from "../runtime/types";
import { StructuredPrototypeCanvas } from "./StructuredPrototypeCanvas";
import type { ProcurementRuntimeBindings } from "./structuredPrototypeDerived";
import type { StructuredPrototypeDocument, StructuredPrototypePage } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  page: StructuredPrototypePage;
  runtimeState: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
  runtimeBindings: ProcurementRuntimeBindings;
  viewport: "desktop" | "tablet" | "mobile";
  selectedNodeId: string | null;
  formValues: Record<string, string>;
  disabled: boolean;
  onPageSelect: (pageId: string) => void;
  onSelectNode: (nodeId: string) => void;
  onFormValue: (nodeId: string, value: string) => void;
  onSubmit: () => void;
  onApprove: () => void;
  onRowActivate: (entity: RuntimeEntity) => void;
}

const VIEWPORT_WIDTH = { desktop: "100%", tablet: "760px", mobile: "390px" } as const;

export function StructuredPrototypePreview({
  document,
  page,
  runtimeState,
  viewModel,
  runtimeBindings,
  viewport,
  selectedNodeId,
  formValues,
  disabled,
  onPageSelect,
  onSelectNode,
  onFormValue,
  onSubmit,
  onApprove,
  onRowActivate,
}: Props) {
  const { t } = useI18n();
  const role = document.runtime.roles.find(
    (candidate) => candidate.id === runtimeState.actorRoleId,
  );
  const notification = runtimeState.notifications.at(-1);
  return (
    <div className="h-full min-h-0 overflow-auto bg-[#eef1ef] p-3 sm:p-5">
      <div
        className="mx-auto min-h-[610px] overflow-hidden border border-[#c9d2ce] bg-white shadow-[0_12px_34px_rgba(18,31,27,0.12)] transition-[width] motion-reduce:transition-none"
        style={{ width: VIEWPORT_WIDTH[viewport], maxWidth: "100%" }}
      >
        <div className="grid min-h-9 grid-cols-[auto_minmax(0,1fr)] items-center gap-3 border-b border-[#d9dfdc] bg-[#f7f8f7] px-3">
          <div className="flex gap-1.5" aria-hidden>
            <span className="size-2 rounded-full bg-[#b8c3be]" />
            <span className="size-2 rounded-full bg-[#b8c3be]" />
            <span className="size-2 rounded-full bg-[#b8c3be]" />
          </div>
          <div className="truncate border border-[#e1e5e3] bg-white px-3 py-1 text-[10px] text-[#62706b]">
            prototype.local{page.route}
          </div>
        </div>
        <div
          className={cn(
            "grid min-h-[570px]",
            viewport === "desktop"
              ? "grid-cols-1 md:grid-cols-[185px_minmax(0,1fr)]"
              : "grid-cols-1",
          )}
        >
          {viewport === "desktop" && (
            <aside className="hidden bg-[#18231f] p-4 text-white md:block">
              <div className="text-base font-bold">Orion</div>
              <div className="mt-1 text-[10px] text-[#b8c3be]">{document.title}</div>
              <nav
                className="mt-6 grid gap-1"
                aria-label={t("prototype.structured.preview.navigation")}
              >
                {document.navigation.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={cn(
                      "min-h-10 px-3 text-left text-xs",
                      item.targetPageId === page.id
                        ? "bg-white/14 font-semibold text-white"
                        : "text-[#d5ddd9] hover:bg-white/8",
                    )}
                    onClick={() => onPageSelect(item.targetPageId)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
            </aside>
          )}
          <section className="min-w-0 bg-[#fbfcfb]">
            <header className="flex min-h-12 items-center justify-between border-b border-[#e6eae8] px-4">
              <div className="flex items-center gap-2 text-xs text-[#62706b]">
                <Menu size={15} className="md:hidden" aria-hidden />
                {page.title}
              </div>
              <span className="inline-flex items-center gap-1.5 bg-[#e1f1ed] px-2 py-1 text-[10px] font-semibold text-[#126b5f]">
                <UserRound size={12} aria-hidden />
                {t("prototype.structured.role.simulated", { role: role?.label ?? "-" })}
              </span>
            </header>
            {notification && (
              <div
                className={cn(
                  "mx-4 mt-3 border px-3 py-2 text-xs",
                  notification.level === "error"
                    ? "border-[#e4a8b2] bg-[#fff1f3] text-[#8c1d31]"
                    : "border-[#b6d7cf] bg-[#e9f4ec] text-[#237a45]",
                )}
                role="status"
              >
                {notification.message}
              </div>
            )}
            <StructuredPrototypeCanvas
              page={page}
              runtimeState={runtimeState}
              viewModel={viewModel}
              runtimeBindings={runtimeBindings}
              selectedNodeId={selectedNodeId}
              formValues={formValues}
              disabled={disabled}
              onSelect={onSelectNode}
              onFormValue={onFormValue}
              onSubmit={onSubmit}
              onApprove={onApprove}
              onRowActivate={onRowActivate}
            />
          </section>
        </div>
      </div>
    </div>
  );
}
