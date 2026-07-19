"use client";

import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Copy, FileText, GripVertical, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { readStructuredPrototypePageDragData } from "./structuredPrototypeDrag";
import type { StructuredPrototypePage } from "./types";

interface Props {
  pages: StructuredPrototypePage[];
  activePageId: string;
  externalError: string | null;
  dragDisabled: boolean;
  selectionDisabled: boolean;
  mutationDisabled: boolean;
  onSelect: (pageId: string) => void;
  onAdd: () => Promise<boolean>;
  onDuplicate: (pageId: string, title: string) => Promise<boolean>;
  onRename: (pageId: string, title: string) => Promise<boolean>;
  onDelete: (pageId: string) => Promise<boolean>;
}

export type StructuredPrototypePageDropIndicator = "top" | "bottom";

export function resolveStructuredPrototypePageDropIndicator(
  activeIndex: number | null,
  targetIndex: number,
): StructuredPrototypePageDropIndicator | null {
  if (activeIndex === null || activeIndex === targetIndex) return null;
  return activeIndex < targetIndex ? "bottom" : "top";
}

function SortablePageRailItem({
  page,
  index,
  activePageId,
  externalError,
  dragDisabled,
  selectionDisabled,
  mutationDisabled,
  deleteDisabled,
  actionPending,
  onSelect,
  onDuplicate,
  onRename,
  onRequestDelete,
}: {
  page: StructuredPrototypePage;
  index: number;
  activePageId: string;
  externalError: string | null;
  dragDisabled: boolean;
  selectionDisabled: boolean;
  mutationDisabled: boolean;
  deleteDisabled: boolean;
  actionPending: boolean;
  onSelect: (pageId: string) => void;
  onDuplicate: (pageId: string, title: string) => Promise<boolean>;
  onRename: (pageId: string, title: string) => Promise<boolean>;
  onRequestDelete: (pageId: string) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(page.title);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [renamePending, setRenamePending] = useState(false);
  const {
    active,
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
    isOver,
  } = useSortable({
    id: `page:${page.id}`,
    data: { kind: "page", pageId: page.id, index },
    disabled: dragDisabled,
  });
  const activePage = readStructuredPrototypePageDragData(active?.data.current);
  const dropIndicator = isOver
    ? resolveStructuredPrototypePageDropIndicator(activePage?.index ?? null, index)
    : null;
  const controlsDisabled = mutationDisabled || actionPending || renamePending;

  const beginRename = (): void => {
    setTitle(page.title);
    setRenameError(null);
    setEditing(true);
  };

  const cancelRename = (): void => {
    setTitle(page.title);
    setRenameError(null);
    setEditing(false);
  };

  const commitRename = async (): Promise<void> => {
    const normalized = title.trim();
    if (normalized.length === 0) {
      setRenameError(t("prototype.structured.pages.nameRequired"));
      return;
    }
    if (normalized === page.title) {
      cancelRename();
      return;
    }
    setRenamePending(true);
    setRenameError(null);
    try {
      const renamed = await onRename(page.id, normalized);
      if (renamed) cancelRename();
      else setRenameError(t("prototype.structured.pages.renameFailed"));
    } catch (error) {
      console.error("structured prototype page rename failed:", error);
      setRenameError(t("prototype.structured.pages.renameFailed"));
    } finally {
      setRenamePending(false);
    }
  };

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "relative border-l-2 transition-colors motion-reduce:transition-none",
        page.id === activePageId
          ? "border-brand bg-brand-bg"
          : "border-transparent bg-transparent hover:bg-surface-hover",
        isDragging && "opacity-35",
      )}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-prototype-page-drop-indicator={dropIndicator ?? "none"}
      data-prototype-page-id={page.id}
    >
      {dropIndicator !== null && (
        <span
          className={cn(
            "pointer-events-none absolute inset-x-0 z-20 h-0.5 bg-brand",
            dropIndicator === "top" ? "top-0" : "bottom-0",
          )}
          data-prototype-page-drop-indicator-line={dropIndicator}
          aria-hidden
        />
      )}
      <div className="grid min-h-12 grid-cols-[minmax(0,1fr)_28px_28px_28px_28px] items-stretch">
        {editing ? (
          <label className="flex min-w-0 items-center gap-2 px-2 py-1.5">
            <FileText size={14} className="shrink-0 text-text-faint" aria-hidden />
            <input
              autoFocus
              className={cn(
                "h-8 min-w-0 flex-1 border bg-surface-input px-2 text-xs text-foreground outline-none",
                renameError === null
                  ? "border-border-muted focus:border-brand"
                  : "border-status-failed",
              )}
              value={title}
              disabled={controlsDisabled}
              onChange={(event) => {
                setTitle(event.target.value);
                setRenameError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void commitRename();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  cancelRename();
                }
              }}
              aria-label={t("prototype.structured.pages.renameInput", { name: page.title })}
              aria-invalid={renameError !== null}
            />
          </label>
        ) : (
          <button
            type="button"
            className="grid min-h-12 min-w-0 cursor-pointer grid-cols-[22px_minmax(0,1fr)] items-center gap-2 px-2 py-1.5 text-left disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => onSelect(page.id)}
            onDoubleClick={() => {
              if (!controlsDisabled) beginRename();
            }}
            disabled={selectionDisabled}
            aria-current={page.id === activePageId ? "page" : undefined}
            aria-label={t("prototype.structured.pages.select", { name: page.title })}
          >
            <span className="grid size-6 place-items-center text-text-faint">
              <FileText size={15} aria-hidden />
            </span>
            <span className="min-w-0">
              <strong className="block truncate text-xs font-semibold text-foreground">
                {page.title}
              </strong>
              <span className="mt-0.5 block truncate text-[10px] text-text-muted">
                {page.route}
              </span>
            </span>
          </button>
        )}
        <button
          type="button"
          className="grid size-7 self-center cursor-pointer place-items-center text-text-faint hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
          onClick={beginRename}
          disabled={controlsDisabled}
          aria-label={t("prototype.structured.pages.rename", { name: page.title })}
          title={t("prototype.structured.pages.rename", { name: page.title })}
        >
          <Pencil size={13} aria-hidden />
        </button>
        <button
          type="button"
          className="grid size-7 self-center cursor-pointer place-items-center text-text-faint hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => void onDuplicate(page.id, page.title)}
          disabled={controlsDisabled}
          aria-label={t("prototype.structured.pages.duplicate", { name: page.title })}
          title={t("prototype.structured.pages.duplicate", { name: page.title })}
        >
          <Copy size={13} aria-hidden />
        </button>
        <button
          type="button"
          className="grid size-7 self-center cursor-pointer place-items-center text-text-faint hover:text-status-failed disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => onRequestDelete(page.id)}
          disabled={controlsDisabled || deleteDisabled}
          aria-label={t(
            deleteDisabled
              ? "prototype.structured.pages.deleteLast"
              : "prototype.structured.pages.delete",
            { name: page.title },
          )}
          title={t(
            deleteDisabled
              ? "prototype.structured.pages.deleteLast"
              : "prototype.structured.pages.delete",
            { name: page.title },
          )}
        >
          <Trash2 size={13} aria-hidden />
        </button>
        <button
          ref={setActivatorNodeRef}
          type="button"
          className="grid size-7 self-center cursor-grab place-items-center text-text-faint hover:text-foreground active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-45"
          disabled={dragDisabled}
          {...attributes}
          {...listeners}
          aria-label={t("prototype.structured.canvas.drag", { name: page.title })}
          title={t("prototype.structured.canvas.drag", { name: page.title })}
        >
          <GripVertical size={14} aria-hidden />
        </button>
      </div>
      {editing && renameError !== null && (
        <p
          className="border-t border-status-failed/30 px-3 py-1 text-[10px] text-status-failed"
          role="alert"
        >
          {externalError ?? renameError}
        </p>
      )}
    </div>
  );
}

export function StructuredPrototypePageRail({
  pages,
  activePageId,
  externalError,
  dragDisabled,
  selectionDisabled,
  mutationDisabled,
  onSelect,
  onAdd,
  onDuplicate,
  onRename,
  onDelete,
}: Props) {
  const { t } = useI18n();
  const [pendingAction, setPendingAction] = useState<"add" | "duplicate" | "delete" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletePageId, setDeletePageId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deletePage = pages.find((page) => page.id === deletePageId) ?? null;
  const actionPending = pendingAction !== null;

  const runAction = async (
    kind: "add" | "duplicate" | "delete",
    action: () => Promise<boolean>,
    failureMessage: string,
  ): Promise<boolean> => {
    if (pendingAction !== null) return false;
    setPendingAction(kind);
    setActionError(null);
    try {
      const applied = await action();
      if (!applied) setActionError(failureMessage);
      return applied;
    } catch (error) {
      console.error(`structured prototype page ${kind} failed:`, error);
      setActionError(failureMessage);
      return false;
    } finally {
      setPendingAction(null);
    }
  };

  const duplicatePage = async (pageId: string, title: string): Promise<boolean> =>
    runAction(
      "duplicate",
      () => onDuplicate(pageId, title),
      t("prototype.structured.pages.duplicateFailed"),
    );

  const renamePage = async (pageId: string, title: string): Promise<boolean> => {
    setActionError(null);
    return onRename(pageId, title);
  };

  const confirmDelete = async (): Promise<void> => {
    if (deletePage === null) return;
    setDeleteError(null);
    const deleted = await runAction(
      "delete",
      () => onDelete(deletePage.id),
      t("prototype.structured.pages.deleteFailed"),
    );
    if (deleted) {
      setDeletePageId(null);
      return;
    }
    setDeleteError(t("prototype.structured.pages.deleteFailed"));
  };

  return (
    <div className="grid min-h-0 grid-rows-[36px_minmax(0,1fr)]">
      <div className="flex items-center justify-end border-b border-border-subtle px-2">
        <button
          type="button"
          className="grid size-7 cursor-pointer place-items-center text-text-muted hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => void runAction("add", onAdd, t("prototype.structured.pages.addFailed"))}
          disabled={mutationDisabled || actionPending}
          aria-label={t("prototype.structured.pages.add")}
          title={t("prototype.structured.pages.add")}
        >
          <Plus size={14} aria-hidden />
        </button>
      </div>
      <div className="min-h-0 overflow-auto">
        {actionError !== null && (
          <p
            className="border-b border-status-failed/30 px-3 py-1.5 text-[10px] text-status-failed"
            role="alert"
          >
            {externalError ?? actionError}
          </p>
        )}
        <SortableContext
          items={pages.map((page) => `page:${page.id}`)}
          strategy={verticalListSortingStrategy}
        >
          {pages.map((page, index) => (
            <SortablePageRailItem
              key={page.id}
              page={page}
              index={index}
              activePageId={activePageId}
              externalError={externalError}
              dragDisabled={dragDisabled}
              selectionDisabled={selectionDisabled}
              mutationDisabled={mutationDisabled}
              deleteDisabled={pages.length === 1}
              actionPending={actionPending}
              onSelect={(pageId) => {
                setActionError(null);
                onSelect(pageId);
              }}
              onDuplicate={duplicatePage}
              onRename={renamePage}
              onRequestDelete={(pageId) => {
                setActionError(null);
                setDeleteError(null);
                setDeletePageId(pageId);
              }}
            />
          ))}
        </SortableContext>
      </div>
      <ConfirmDialog
        open={deletePage !== null}
        onOpenChange={(open) => {
          if (open || pendingAction === "delete") return;
          setDeletePageId(null);
          setDeleteError(null);
        }}
        title={
          deletePage === null
            ? t("prototype.structured.pages.deleteTitle", { name: "" })
            : t("prototype.structured.pages.deleteTitle", { name: deletePage.title })
        }
        description={
          deletePage === null
            ? ""
            : `${t("prototype.structured.pages.deleteDescription", { name: deletePage.title })}${
                deleteError === null ? "" : ` ${externalError ?? deleteError}`
              }`
        }
        confirmText={t("prototype.structured.pages.deleteConfirm")}
        cancelText={t("prototype.structured.deleteCancel")}
        onConfirm={() => void confirmDelete()}
        isLoading={pendingAction === "delete"}
        loadingMotionPhase="tool"
        loadingDensity="prototype-page-delete"
        variant="destructive"
      />
    </div>
  );
}
