"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  CloudUpload,
  ExternalLink,
  Files,
  PanelsTopLeft,
  MessageSquare,
  Save,
  Undo2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { RuntimeEntity, RuntimeEvent } from "../runtime/types";
import {
  createPaletteNode,
  insertPaletteNodeBatch,
  moveNodeBatch,
} from "./structuredPrototypeCommands";
import {
  deriveProcurementRuntimeBindings,
  findStructuredPrototypeNode,
} from "./structuredPrototypeDerived";
import { StructuredPrototypeAiPanel } from "./StructuredPrototypeAiPanel";
import { StructuredPrototypeFlow } from "./StructuredPrototypeFlow";
import { StructuredPrototypeGenerationPanel } from "./StructuredPrototypeGenerationPanel";
import { StructuredPrototypeInspector } from "./StructuredPrototypeInspector";
import { StructuredPrototypePageRail } from "./StructuredPrototypePageRail";
import {
  StructuredPrototypePalette,
  type StructuredPrototypePaletteType,
} from "./StructuredPrototypePalette";
import { StructuredPrototypePreview } from "./StructuredPrototypePreview";
import { useStructuredPrototypeStudio } from "./useStructuredPrototypeStudio";

interface Props {
  projectId: string;
}

type StudioMode = "design" | "flow";
type StudioViewport = "desktop" | "tablet" | "mobile";
type InspectorTab = "ai" | "properties";
type MobilePanel = "left" | "canvas" | "right";

interface PaletteDragData {
  kind: "palette";
  nodeType: StructuredPrototypePaletteType;
}

interface NodeDragData {
  kind: "node";
  nodeId: string;
}

function isPaletteType(value: unknown): value is StructuredPrototypePaletteType {
  return ["Stack", "Form", "Text", "Input", "Button", "Table"].includes(String(value));
}

function readPaletteDragData(value: unknown): PaletteDragData | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  if (!("kind" in value) || !("nodeType" in value)) return null;
  return value.kind === "palette" && isPaletteType(value.nodeType)
    ? { kind: "palette", nodeType: value.nodeType }
    : null;
}

function readNodeDragData(value: unknown): NodeDragData | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  if (!("kind" in value) || !("nodeId" in value)) return null;
  return value.kind === "node" && typeof value.nodeId === "string"
    ? { kind: "node", nodeId: value.nodeId }
    : null;
}

export function StructuredPrototypeStudioPage({ projectId }: Props) {
  const { t } = useI18n();
  const controller = useStructuredPrototypeStudio(projectId);
  const [mode, setMode] = useState<StudioMode>("design");
  const [viewport, setViewport] = useState<StudioViewport>("desktop");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("ai");
  const [manualPageId, setManualPageId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("canvas");
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const document = controller.draft?.document ?? null;
  const runtime = controller.runtime;
  const runtimeBindings = useMemo(
    () => (document ? deriveProcurementRuntimeBindings(document) : null),
    [document],
  );
  const activePage = useMemo(() => {
    if (!document || !runtime) return null;
    const targetId = manualPageId ?? runtime.state.currentPageId;
    return document.pages.find((page) => page.id === targetId) ?? document.pages[0] ?? null;
  }, [document, manualPageId, runtime]);
  const selectedNode =
    activePage && selectedNodeId
      ? findStructuredPrototypeNode(activePage.root, selectedNodeId)
      : null;

  if (controller.loading && (!controller.draft || !runtime)) {
    return (
      <div className="grid min-h-[100dvh] place-items-center bg-[#eef1ef] text-sm text-[#62706b]">
        {t("prototype.structured.loading")}
      </div>
    );
  }
  if (!controller.draft && !runtime && !controller.error) {
    return (
      <StructuredPrototypeGenerationPanel
        projectId={projectId}
        onAccepted={controller.adoptAiDraft}
      />
    );
  }
  if (!controller.draft || !runtime || !document || !activePage || !runtimeBindings) {
    return (
      <div className="grid min-h-[100dvh] place-items-center bg-[#eef1ef] p-6">
        <div className="max-w-md border border-[#d9dfdc] bg-white p-6 text-center">
          <p className="text-sm leading-6 text-[#8c1d31]">
            {controller.error ?? t("prototype.structured.loadFailed")}
          </p>
          <button
            type="button"
            className="mt-4 min-h-10 bg-[#126b5f] px-4 text-sm font-semibold text-white"
            onClick={() => void controller.retry()}
          >
            {t("prototype.structured.retry")}
          </button>
        </div>
      </div>
    );
  }

  const runEvents = async (events: RuntimeEvent[]) => {
    setInteractionError(null);
    const applied = await controller.sendRuntimeEvents(events);
    if (applied) setManualPageId(null);
  };

  const submitRequest = async () => {
    const title = formValues[runtimeBindings.titleInputNodeId]?.trim() ?? "";
    const amountValue = formValues[runtimeBindings.amountInputNodeId]?.trim() ?? "";
    const amount = Number(amountValue);
    if (!title || !Number.isSafeInteger(amount) || amount < 1) {
      setInteractionError(t("prototype.structured.form.invalid"));
      return;
    }
    await runEvents([
      {
        kind: "fieldValueCommitted",
        nodeId: runtimeBindings.titleInputNodeId,
        formId: runtimeBindings.formId,
        fieldId: runtimeBindings.titleFormFieldId,
        value: { type: "string", value: title },
      },
      {
        kind: "fieldValueCommitted",
        nodeId: runtimeBindings.amountInputNodeId,
        formId: runtimeBindings.formId,
        fieldId: runtimeBindings.amountFormFieldId,
        value: { type: "integer", value: amount },
      },
      {
        kind: "nodeActivated",
        nodeId: runtimeBindings.submitNodeId,
        event: "submit",
      },
    ]);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const over = event.over;
    if (!over || activePage.root.type !== "Stack") return;
    const children = activePage.root.children;
    const overIndex = children.findIndex((child) => child.id === String(over.id));
    const targetIndex = overIndex >= 0 ? overIndex : children.length;
    const palette = readPaletteDragData(event.active.data.current);
    if (palette) {
      const key = `new-${palette.nodeType.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}`;
      void controller.applyCommands(
        insertPaletteNodeBatch(
          activePage.root.id,
          targetIndex,
          createPaletteNode(palette.nodeType, key, runtimeBindings.formId),
        ),
      );
      return;
    }
    const dragged = readNodeDragData(event.active.data.current);
    if (!dragged) return;
    const sourceIndex = children.findIndex((child) => child.id === dragged.nodeId);
    if (sourceIndex < 0 || sourceIndex === targetIndex) return;
    void controller.applyCommands(moveNodeBatch(dragged.nodeId, activePage.root.id, targetIndex));
  };

  const insertPaletteNode = (type: StructuredPrototypePaletteType) => {
    if (activePage.root.type !== "Stack") return;
    const key = `new-${type.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}`;
    void controller.applyCommands(
      insertPaletteNodeBatch(
        activePage.root.id,
        activePage.root.children.length,
        createPaletteNode(type, key, runtimeBindings.formId),
      ),
    );
    setMobilePanel("canvas");
  };

  const activateRow = (entity: RuntimeEntity) => {
    void runEvents([
      {
        kind: "tableRowActivated",
        nodeId: runtimeBindings.requestTableNodeId,
        entityRef: {
          type: "entityRef",
          schemaId: entity.schemaId,
          entityId: entity.id,
        },
      },
    ]);
  };

  const roleLabels = document.runtime.roles;
  const paletteLabels = {
    Stack: t("prototype.structured.palette.stack"),
    Form: t("prototype.structured.palette.form"),
    Text: t("prototype.structured.palette.text"),
    Input: t("prototype.structured.palette.input"),
    Button: t("prototype.structured.palette.button"),
    Table: t("prototype.structured.palette.table"),
  };
  const visibleError = interactionError ?? controller.error;

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <div className="grid min-h-[100dvh] bg-[#eef1ef] pb-14 text-[#17201d] lg:h-[100dvh] lg:grid-rows-[58px_minmax(0,1fr)] lg:overflow-hidden lg:pb-0">
        <header className="flex min-h-[58px] flex-wrap items-center gap-2 border-b border-[#d9dfdc] bg-white px-3 py-2 shadow-sm sm:flex-nowrap sm:py-0">
          <div className="flex min-w-[150px] flex-1 items-center gap-2">
            <Link
              href={`/projects/${projectId}/prototypes`}
              className="grid size-8 shrink-0 place-items-center bg-[#17201d] text-white"
              aria-label={t("prototype.structured.back")}
            >
              <Undo2 size={15} aria-hidden />
            </Link>
            <div className="min-w-0">
              <div className="text-xs font-bold">{t("prototype.structured.brand")}</div>
              <div className="truncate text-[10px] text-[#62706b]">{document.title}</div>
            </div>
          </div>
          <div className="inline-grid shrink-0 grid-cols-2 border border-[#d9dfdc] bg-[#ecefed] p-1">
            {(["design", "flow"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={cn(
                  "min-h-8 min-w-18 px-3 text-xs font-semibold",
                  mode === value ? "bg-white text-[#17201d] shadow-sm" : "text-[#62706b]",
                )}
                onClick={() => setMode(value)}
                aria-pressed={mode === value}
              >
                {t(`prototype.structured.mode.${value}`)}
              </button>
            ))}
          </div>
          <div className="order-3 flex w-full min-w-0 items-center justify-between gap-2 sm:order-none sm:w-auto sm:flex-1 sm:justify-end">
            <span className="hidden text-[10px] text-[#62706b] xl:inline">
              {controller.saving
                ? t("prototype.structured.saving")
                : t("prototype.structured.saved")}
            </span>
            <select
              className="min-h-9 max-w-32 border border-[#c9d2ce] bg-white px-2 text-xs"
              aria-label={t("prototype.structured.role.label")}
              value={runtime.state.actorRoleId}
              disabled={controller.saving}
              onChange={(event) =>
                void runEvents([{ kind: "switchSimulatedRole", roleId: event.target.value }])
              }
            >
              {roleLabels.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="grid size-9 place-items-center border border-[#c9d2ce] bg-white text-[#126b5f] disabled:opacity-45"
              onClick={() => void controller.checkpointRuntime()}
              disabled={controller.saving}
              aria-label={t("prototype.structured.checkpoint")}
              title={t("prototype.structured.checkpoint")}
            >
              <Save size={15} aria-hidden />
            </button>
            <button
              type="button"
              className="inline-flex min-h-9 items-center justify-center gap-2 bg-[#126b5f] px-3 text-xs font-semibold text-white disabled:opacity-45"
              onClick={() => void controller.publish()}
              disabled={controller.saving}
              aria-label={t("prototype.structured.publish")}
              title={t("prototype.structured.publish")}
            >
              <CloudUpload size={15} aria-hidden />
              <span className="hidden sm:inline">{t("prototype.structured.publish")}</span>
            </button>
            {controller.publication && (
              <Link
                href={controller.publication.sharePath}
                target="_blank"
                rel="noreferrer"
                className="grid size-9 place-items-center border border-[#c9d2ce] bg-white text-[#126b5f]"
                aria-label={t("prototype.structured.openPublished")}
                title={t("prototype.structured.openPublished")}
              >
                <ExternalLink size={15} aria-hidden />
              </Link>
            )}
          </div>
        </header>

        <main className="grid min-h-0 grid-cols-1 lg:grid-cols-[240px_minmax(440px,1fr)_300px]">
          <aside
            className={cn(
              "min-h-0 grid-rows-[44px_minmax(130px,1fr)_44px_minmax(180px,1fr)] border-r border-[#d9dfdc] bg-white",
              mobilePanel === "left" ? "grid" : "hidden lg:grid",
            )}
          >
            <div className="flex items-center justify-between border-b border-[#d9dfdc] px-3 text-xs font-bold uppercase">
              {t("prototype.structured.pages")}
              <span className="font-normal text-[#62706b]">{document.pages.length}</span>
            </div>
            <StructuredPrototypePageRail
              pages={document.pages}
              activePageId={activePage.id}
              onSelect={(pageId) => {
                setManualPageId(pageId);
                setMobilePanel("canvas");
              }}
            />
            <div className="flex items-center justify-between border-y border-[#d9dfdc] px-3 text-xs font-bold uppercase">
              {t("prototype.structured.components")}
              <span className="font-normal text-[#62706b]">6</span>
            </div>
            <div className="min-h-0 overflow-auto">
              <StructuredPrototypePalette
                labels={paletteLabels}
                disabled={controller.saving}
                onInsert={insertPaletteNode}
              />
            </div>
          </aside>

          <section
            className={cn(
              "min-h-0 grid-rows-[44px_minmax(0,1fr)]",
              mobilePanel === "canvas" ? "grid" : "hidden lg:grid",
            )}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[#d9dfdc] bg-white px-3">
              <div className="min-w-0 truncate text-xs text-[#62706b]">
                {mode === "design"
                  ? t("prototype.structured.mode.design")
                  : t("prototype.structured.mode.flow")}
                <span className="mx-2">/</span>
                <strong className="text-[#17201d]">{activePage.title}</strong>
                <span className="ml-2 border border-[#d9dfdc] bg-[#f7f8f7] px-2 py-1 text-[10px]">
                  doc {controller.draft.headSequenceNo}
                </span>
              </div>
              {visibleError && (
                <span className="min-w-0 max-w-64 truncate text-[10px] text-[#8c1d31]">
                  {visibleError}
                </span>
              )}
              {mode === "design" && (
                <div className="hidden grid-cols-3 border border-[#d9dfdc] bg-[#ecefed] p-1 sm:grid">
                  {(["desktop", "tablet", "mobile"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      className={cn(
                        "min-h-7 px-3 text-[10px] font-semibold",
                        viewport === value ? "bg-white text-[#17201d] shadow-sm" : "text-[#62706b]",
                      )}
                      onClick={() => setViewport(value)}
                      aria-pressed={viewport === value}
                    >
                      {t(`prototype.structured.viewport.${value}`)}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {mode === "flow" ? (
              <StructuredPrototypeFlow document={document} />
            ) : (
              <StructuredPrototypePreview
                document={document}
                page={activePage}
                runtimeState={runtime.state}
                viewModel={runtime.viewModel}
                runtimeBindings={runtimeBindings}
                viewport={viewport}
                selectedNodeId={selectedNodeId}
                formValues={formValues}
                disabled={controller.saving}
                onPageSelect={setManualPageId}
                onSelectNode={(nodeId) => {
                  setSelectedNodeId(nodeId);
                  setInspectorTab("properties");
                  setMobilePanel("right");
                }}
                onFormValue={(nodeId, value) =>
                  setFormValues((current) => ({ ...current, [nodeId]: value }))
                }
                onSubmit={() => void submitRequest()}
                onApprove={() =>
                  void runEvents([
                    {
                      kind: "nodeActivated",
                      nodeId: runtimeBindings.approveNodeId,
                      event: "click",
                    },
                  ])
                }
                onRowActivate={activateRow}
              />
            )}
          </section>

          <aside
            className={cn(
              "min-h-0 grid-rows-[44px_minmax(0,1fr)] border-l border-[#d9dfdc] bg-white",
              mobilePanel === "right" ? "grid" : "hidden lg:grid",
            )}
          >
            <div className="grid grid-cols-2 border-b border-[#d9dfdc] bg-[#ecefed] p-1">
              {(["ai", "properties"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={cn(
                    "min-h-8 text-xs font-semibold",
                    inspectorTab === tab ? "bg-white text-[#17201d] shadow-sm" : "text-[#62706b]",
                  )}
                  onClick={() => setInspectorTab(tab)}
                  aria-selected={inspectorTab === tab}
                  role="tab"
                >
                  {t(`prototype.structured.inspector.${tab}`)}
                </button>
              ))}
            </div>
            <div className="min-h-0 overflow-auto">
              {inspectorTab === "properties" ? (
                <StructuredPrototypeInspector
                  node={selectedNode}
                  disabled={controller.saving}
                  onApply={controller.applyCommands}
                />
              ) : (
                <StructuredPrototypeAiPanel
                  projectId={projectId}
                  draft={controller.draft}
                  pageId={activePage.id}
                  selectedNodeId={selectedNodeId}
                  viewport={viewport}
                  disabled={controller.saving}
                  onDraftApplied={controller.adoptAiDraft}
                />
              )}
            </div>
          </aside>
        </main>
        <nav
          className="fixed inset-x-0 bottom-0 z-50 grid h-14 grid-cols-3 border-t border-[#d9dfdc] bg-white p-1 lg:hidden"
          aria-label={t("prototype.structured.mobile.navigation")}
        >
          {[
            { panel: "left" as const, label: t("prototype.structured.pages"), icon: Files },
            {
              panel: "canvas" as const,
              label: t("prototype.structured.canvas"),
              icon: PanelsTopLeft,
            },
            {
              panel: "right" as const,
              label: t("prototype.structured.inspector.ai"),
              icon: MessageSquare,
            },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.panel}
                type="button"
                className={cn(
                  "inline-flex items-center justify-center gap-2 text-xs font-semibold",
                  mobilePanel === item.panel ? "bg-[#e1f1ed] text-[#126b5f]" : "text-[#62706b]",
                )}
                onClick={() => setMobilePanel(item.panel)}
                aria-pressed={mobilePanel === item.panel}
              >
                <Icon size={15} aria-hidden />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>
    </DndContext>
  );
}
