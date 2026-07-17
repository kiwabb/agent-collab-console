"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type WheelEvent,
} from "react";
import { Menu, UserRound } from "lucide-react";

import { isKeyboardShortcutEditableTarget } from "@/hooks/useKeyboardShortcuts";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import type { PrototypeRuntimeState, RuntimeEntity, RuntimeViewModel } from "../runtime/types";
import {
  resolvePrototypeShellTheme,
  structuredPrototypeShowsRoleControl,
} from "./prototypeRendererCore";
import {
  StructuredPrototypeCanvas,
  type StructuredPrototypeMarqueeGestureEvent,
  type StructuredPrototypeNodeSelectionIntent,
  type StructuredPrototypeResizeGestureEvent,
} from "./StructuredPrototypeCanvas";
import type { StructuredPrototypeNodeSelection } from "./structuredPrototypeSelection";
import type { StructuredPrototypeGroupTransformItem } from "./structuredPrototypeGroupTransform";
import type {
  StructuredPrototypeFreeformMoveEvidenceCapture,
  StructuredPrototypeFreeformMoveGestureEvent,
} from "./useStructuredPrototypeFreeformMove";
import {
  normalizeStructuredPrototypeWheelDelta,
  resolveStructuredPrototypeFitScale,
  resolveStructuredPrototypeWheelScale,
  resolveStructuredPrototypeZoomAtPoint,
  type StructuredPrototypePoint,
} from "./structuredPrototypeViewportTransform";
import type { StructuredPrototypeInteraction } from "./structuredPrototypeInteraction";
import type { StructuredPrototypeDocument, StructuredPrototypePage } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  page: StructuredPrototypePage;
  runtimeState: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
  viewport: "desktop" | "tablet" | "mobile";
  zoom: StructuredPrototypePreviewZoom;
  viewResetKey: number;
  editing: boolean;
  dragGestureActive: boolean;
  activeInteractionKind: StructuredPrototypeInteraction["kind"];
  onZoomChange: (zoom: StructuredPrototypePreviewZoom) => void;
  selection: StructuredPrototypeNodeSelection;
  formValues: Record<string, string>;
  disabled: boolean;
  dragDisabled: boolean;
  resizeDisabled: boolean;
  gridSnappingEnabled: boolean;
  onPageSelect: (pageId: string) => void;
  onSelectNode: (nodeId: string, intent: StructuredPrototypeNodeSelectionIntent) => void;
  onSelectionChange: (selection: StructuredPrototypeNodeSelection) => void;
  onMarqueeGestureChange: (event: StructuredPrototypeMarqueeGestureEvent) => number | null;
  onFreeformMoveNode: (
    nodeId: string,
    x: number,
    y: number,
    evidence: StructuredPrototypeFreeformMoveEvidenceCapture,
  ) => Promise<boolean>;
  onFreeformMoveError: (error: unknown) => void;
  onFreeformMoveGestureChange: (
    event: StructuredPrototypeFreeformMoveGestureEvent,
  ) => number | null;
  onFreeformGroupArrange: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onFreeformSelectionNudge: (
    items: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onResizeNode: (
    nodeId: string,
    widthPx: number,
    heightPx: number,
    position?: { x: number; y: number },
    groupItems?: readonly StructuredPrototypeGroupTransformItem[],
  ) => Promise<boolean>;
  onResizeError: (error: unknown) => void;
  onResizeGestureChange: (event: StructuredPrototypeResizeGestureEvent) => number | null;
  onPanGestureStart: (pointerId: number) => number | null;
  onPanGestureEnd: (sessionId: number) => void;
  onFormValue: (nodeId: string, value: string) => void;
  onNodeActivate: (nodeId: string, event: "click" | "submit") => void;
  onRowActivate: (nodeId: string, entity: RuntimeEntity) => void;
}

const FIXED_VIEWPORT_WIDTH = { tablet: 760, mobile: 390 } as const;
const PREVIEW_FIT_PADDING = 32;
const PREVIEW_MIN_INTERACTIVE_SCALE = 0.01;
const PREVIEW_MAX_INTERACTIVE_SCALE = 2;
const PREVIEW_WHEEL_ZOOM_INTENSITY = 0.0015;
const PREVIEW_MIN_FRAME_HEIGHT = 610;

export type StructuredPrototypePreviewZoom = "fit" | number;

export function resolveStructuredPrototypeEffectivePreviewScale({
  zoom,
  computedFitScale,
  frozenFitScale,
}: {
  zoom: StructuredPrototypePreviewZoom;
  computedFitScale: number;
  frozenFitScale: number | null;
}): number {
  return zoom === "fit" ? (frozenFitScale ?? computedFitScale) : zoom;
}

function previewTheme(document: StructuredPrototypeDocument): CSSProperties {
  const theme = resolvePrototypeShellTheme(document);
  const style: CSSProperties & Record<`--prototype-${string}`, string> = {
    colorScheme: document.settings.theme === "system" ? "light dark" : document.settings.theme,
    "--prototype-accent": theme.accent,
    "--prototype-accent-text": theme.accentText,
    "--prototype-navigation-background": theme.navigationBackground,
    "--prototype-navigation-text": theme.navigationText,
    "--prototype-content-background": theme.contentBackground,
    "--prototype-content-text": theme.contentText,
    "--prototype-surface": theme.surface,
    "--prototype-surface-text": theme.surfaceText,
    "--prototype-text": "var(--prototype-content-text)",
  };
  document.tokens.colors.forEach((token, index) => {
    style[`--prototype-color-${index}`] = token.value;
  });
  document.tokens.spacing.forEach((token, index) => {
    style[`--prototype-space-${index}`] = token.value;
  });
  return style;
}

export function StructuredPrototypePreview({
  document,
  page,
  runtimeState,
  viewModel,
  viewport,
  zoom,
  viewResetKey,
  editing,
  dragGestureActive,
  activeInteractionKind,
  onZoomChange,
  selection,
  formValues,
  disabled,
  dragDisabled,
  resizeDisabled,
  gridSnappingEnabled,
  onPageSelect,
  onSelectNode,
  onSelectionChange,
  onMarqueeGestureChange,
  onFreeformMoveNode,
  onFreeformMoveError,
  onFreeformMoveGestureChange,
  onFreeformGroupArrange,
  onFreeformSelectionNudge,
  onResizeNode,
  onResizeError,
  onResizeGestureChange,
  onPanGestureStart,
  onPanGestureEnd,
  onFormValue,
  onNodeActivate,
  onRowActivate,
}: Props) {
  const { t } = useI18n();
  const previewHostRef = useRef<HTMLDivElement | null>(null);
  const previewFrameRef = useRef<HTMLDivElement | null>(null);
  const panStateRef = useRef<{
    sessionId: number;
    pointerId: number;
    lastX: number;
    lastY: number;
  } | null>(null);
  const panGestureEndRef = useRef(onPanGestureEnd);
  const zoomChangeRef = useRef(onZoomChange);
  const activeResizeSessionIdRef = useRef<number | null>(null);
  const wheelAccumulatorRef = useRef<{
    deltaY: number;
    pointerFromViewportCenter: StructuredPrototypePoint | null;
    frameId: number | null;
  }>({ deltaY: 0, pointerFromViewportCenter: null, frameId: null });
  const [previewHostSize, setPreviewHostSize] = useState({ width: 0, height: 0 });
  const [previewFrameHeight, setPreviewFrameHeight] = useState(PREVIEW_MIN_FRAME_HEIGHT);
  const [frozenFitScale, setFrozenFitScale] = useState<number | null>(null);
  const [frozenFrameHeight, setFrozenFrameHeight] = useState<number | null>(null);
  const [viewportTransformReleasePending, setViewportTransformReleasePending] = useState(false);
  const [resizeGestureActive, setResizeGestureActive] = useState(false);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [spacePressed, setSpacePressed] = useState(false);
  const role = document.runtime.roles.find(
    (candidate) => candidate.id === runtimeState.actorRoleId,
  );
  const notification = runtimeState.notifications.at(-1);
  const shell = document.settings.shell;
  const viewportWidth =
    viewport === "desktop" ? page.viewport.width : FIXED_VIEWPORT_WIDTH[viewport];
  useLayoutEffect(() => {
    panGestureEndRef.current = onPanGestureEnd;
  }, [onPanGestureEnd]);
  useLayoutEffect(() => {
    const host = previewHostRef.current;
    if (host === null || typeof ResizeObserver === "undefined") return;
    const updateHostSize = () =>
      setPreviewHostSize({ width: host.clientWidth, height: host.clientHeight });
    updateHostSize();
    const observer = new ResizeObserver(updateHostSize);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const frame = previewFrameRef.current;
    if (frame === null || typeof ResizeObserver === "undefined") return;
    const updateFrameHeight = () =>
      setPreviewFrameHeight(Math.max(PREVIEW_MIN_FRAME_HEIGHT, frame.scrollHeight));
    updateFrameHeight();
    const observer = new ResizeObserver(updateFrameHeight);
    observer.observe(frame);
    return () => observer.disconnect();
  }, [page.id, viewResetKey, viewport]);
  const computedFitScale = useMemo(
    () =>
      resolveStructuredPrototypeFitScale({
        hostWidth: previewHostSize.width,
        hostHeight: previewHostSize.height,
        viewportWidth,
        viewportHeight: page.viewport.height,
        measuredContentHeight: previewFrameHeight,
        padding: PREVIEW_FIT_PADDING,
      }),
    [
      page.viewport.height,
      previewFrameHeight,
      previewHostSize.height,
      previewHostSize.width,
      viewportWidth,
    ],
  );
  const previewScale = resolveStructuredPrototypeEffectivePreviewScale({
    zoom,
    computedFitScale,
    frozenFitScale,
  });
  const previewScaleRef = useRef(previewScale);
  const cancelWheelZoom = useCallback((): void => {
    const accumulator = wheelAccumulatorRef.current;
    if (accumulator.frameId !== null) {
      globalThis.window.cancelAnimationFrame(accumulator.frameId);
    }
    accumulator.deltaY = 0;
    accumulator.pointerFromViewportCenter = null;
    accumulator.frameId = null;
  }, []);
  useLayoutEffect(() => {
    previewScaleRef.current = previewScale;
    zoomChangeRef.current = onZoomChange;
  }, [onZoomChange, previewScale]);
  const computedFrameHeight = Math.max(page.viewport.height, previewFrameHeight);
  const frameHeight = frozenFrameHeight ?? computedFrameHeight;
  const transformGestureActive = dragGestureActive || resizeGestureActive;
  const interactionBlocked = disabled || activeInteractionKind !== "idle" || resizeGestureActive;
  const handleResizeGestureChange = useCallback(
    (event: StructuredPrototypeResizeGestureEvent): number | null => {
      if (event.phase === "start") {
        const sessionId = onResizeGestureChange(event);
        if (sessionId === null) return null;
        activeResizeSessionIdRef.current = sessionId;
        setResizeGestureActive(true);
        setViewportTransformReleasePending(false);
        setFrozenFitScale(zoom === "fit" ? event.previewScale : null);
        setFrozenFrameHeight(computedFrameHeight);
        return sessionId;
      }
      if (activeResizeSessionIdRef.current !== event.sessionId) return null;
      if (event.phase === "end") {
        activeResizeSessionIdRef.current = null;
        setResizeGestureActive(false);
        if (!dragGestureActive) setViewportTransformReleasePending(true);
      }
      return onResizeGestureChange(event);
    },
    [computedFrameHeight, dragGestureActive, onResizeGestureChange, zoom],
  );
  useLayoutEffect(() => {
    if (dragGestureActive) {
      setViewportTransformReleasePending(false);
      setFrozenFitScale((current) => current ?? (zoom === "fit" ? previewScale : null));
      setFrozenFrameHeight((current) => current ?? computedFrameHeight);
      return;
    }
    if (resizeGestureActive) return;
    if (frozenFrameHeight !== null || frozenFitScale !== null) {
      setViewportTransformReleasePending(true);
    }
  }, [
    computedFrameHeight,
    dragGestureActive,
    frozenFitScale,
    frozenFrameHeight,
    previewScale,
    resizeGestureActive,
    zoom,
  ]);
  useLayoutEffect(() => {
    if (!viewportTransformReleasePending || transformGestureActive) return;
    const frame = previewFrameRef.current;
    if (frame !== null) {
      setPreviewFrameHeight(Math.max(PREVIEW_MIN_FRAME_HEIGHT, frame.scrollHeight));
    }
    setFrozenFitScale(null);
    setFrozenFrameHeight(null);
    setViewportTransformReleasePending(false);
  }, [transformGestureActive, viewportTransformReleasePending]);
  const scaledFrameWidth = viewportWidth * previewScale;
  const scaledFrameHeight = frameHeight * previewScale;
  const finishPan = useCallback(
    (pointerId: number | null, releaseCapture = true, updateState = true): void => {
      const currentPan = panStateRef.current;
      if (currentPan === null || (pointerId !== null && currentPan.pointerId !== pointerId)) return;
      panStateRef.current = null;
      const host = previewHostRef.current;
      if (releaseCapture && host?.hasPointerCapture(currentPan.pointerId)) {
        host.releasePointerCapture(currentPan.pointerId);
      }
      panGestureEndRef.current(currentPan.sessionId);
      if (updateState) setIsPanning(false);
    },
    [],
  );
  useEffect(() => {
    cancelWheelZoom();
    finishPan(null);
    setPan({ x: 0, y: 0 });
  }, [cancelWheelZoom, finishPan, page.id, viewport]);
  useEffect(() => {
    if (zoom !== "fit") return;
    cancelWheelZoom();
    finishPan(null);
    setPan({ x: 0, y: 0 });
  }, [cancelWheelZoom, finishPan, viewResetKey, zoom]);
  useEffect(() => {
    if (interactionBlocked) cancelWheelZoom();
  }, [cancelWheelZoom, interactionBlocked]);
  useEffect(() => () => cancelWheelZoom(), [cancelWheelZoom]);
  useEffect(() => {
    if (typeof globalThis.document === "undefined") return;

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        finishPan(null);
        return;
      }
      if (event.code !== "Space" || isKeyboardShortcutEditableTarget(event.target)) return;
      setSpacePressed(true);
    };
    const handleKeyUp = (event: KeyboardEvent): void => {
      if (event.code !== "Space") return;
      setSpacePressed(false);
    };
    const handleBlur = (): void => {
      setSpacePressed(false);
      finishPan(null);
    };
    globalThis.document.addEventListener("keydown", handleKeyDown);
    globalThis.document.addEventListener("keyup", handleKeyUp);
    globalThis.window.addEventListener("blur", handleBlur);
    return () => {
      globalThis.document.removeEventListener("keydown", handleKeyDown);
      globalThis.document.removeEventListener("keyup", handleKeyUp);
      globalThis.window.removeEventListener("blur", handleBlur);
      finishPan(null, true, false);
    };
  }, [finishPan]);
  const handleWheel = (event: WheelEvent<HTMLDivElement>): void => {
    event.preventDefault();
    if (interactionBlocked) return;
    const host = previewHostRef.current;
    if (host === null) return;
    const deltaY = normalizeStructuredPrototypeWheelDelta({
      deltaY: event.deltaY,
      deltaMode: event.deltaMode,
      pageHeight: Math.max(1, host.clientHeight),
    });
    if (deltaY === 0) return;
    const rect = host.getBoundingClientRect();
    const accumulator = wheelAccumulatorRef.current;
    accumulator.deltaY += deltaY;
    accumulator.pointerFromViewportCenter = {
      x: event.clientX - (rect.left + rect.width / 2),
      y: event.clientY - (rect.top + rect.height / 2),
    };
    if (accumulator.frameId !== null) return;
    accumulator.frameId = globalThis.window.requestAnimationFrame(() => {
      accumulator.frameId = null;
      const accumulatedDeltaY = accumulator.deltaY;
      const pointerFromViewportCenter = accumulator.pointerFromViewportCenter;
      accumulator.deltaY = 0;
      accumulator.pointerFromViewportCenter = null;
      if (pointerFromViewportCenter === null || accumulatedDeltaY === 0) return;
      const currentScale = previewScaleRef.current;
      const nextScale = resolveStructuredPrototypeWheelScale({
        currentScale,
        normalizedDeltaY: accumulatedDeltaY,
        minimumScale: PREVIEW_MIN_INTERACTIVE_SCALE,
        maximumScale: PREVIEW_MAX_INTERACTIVE_SCALE,
        intensity: PREVIEW_WHEEL_ZOOM_INTENSITY,
      });
      if (nextScale === currentScale) return;
      setPan((current) =>
        resolveStructuredPrototypeZoomAtPoint({
          pan: current,
          pointerFromViewportOrigin: pointerFromViewportCenter,
          currentScale,
          nextScale,
        }),
      );
      previewScaleRef.current = nextScale;
      zoomChangeRef.current(nextScale);
    });
  };
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    const target = event.target instanceof Element ? event.target : null;
    const startedOnPreviewBackdrop = target === event.currentTarget;
    const shouldPan =
      event.button === 1 || spacePressed || (event.button === 0 && startedOnPreviewBackdrop);
    if (!shouldPan || interactionBlocked) return;
    const sessionId = onPanGestureStart(event.pointerId);
    if (sessionId === null) return;
    event.preventDefault();
    panStateRef.current = {
      sessionId,
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsPanning(true);
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>): void => {
    const currentPan = panStateRef.current;
    if (currentPan === null || currentPan.pointerId !== event.pointerId) return;
    event.preventDefault();
    const deltaX = event.clientX - currentPan.lastX;
    const deltaY = event.clientY - currentPan.lastY;
    currentPan.lastX = event.clientX;
    currentPan.lastY = event.clientY;
    setPan((value) => ({ x: value.x + deltaX, y: value.y + deltaY }));
  };
  const stopPanning = (event: PointerEvent<HTMLDivElement>): void => {
    finishPan(event.pointerId);
  };
  const sidebarExpanded = shell.kind === "sidebar" && viewportWidth >= shell.expandedMinWidth;
  const sidebarWidth = shell.kind === "sidebar" ? shell.navigationWidth : 0;
  const showRoleControl = structuredPrototypeShowsRoleControl(document);
  const NavigationContainer = sidebarExpanded ? "aside" : "header";
  return (
    <div
      ref={previewHostRef}
      className={cn(
        "grid h-full min-h-0 place-items-center overflow-hidden bg-background/35 p-3 touch-none select-none sm:p-4",
        isPanning ? "cursor-grabbing" : spacePressed ? "cursor-grab" : "cursor-default",
      )}
      aria-label={t("prototype.structured.preview.viewport")}
      data-prototype-wheel-input="normalized-raf"
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopPanning}
      onPointerCancel={stopPanning}
      onLostPointerCapture={(event) => finishPan(event.pointerId, false)}
    >
      <div
        data-prototype-preview-pan={`${Math.round(pan.x)},${Math.round(pan.y)}`}
        style={{
          width: `${scaledFrameWidth}px`,
          height: `${scaledFrameHeight}px`,
          transform: `translate(${pan.x}px, ${pan.y}px)`,
        }}
      >
        <div
          ref={previewFrameRef}
          className={cn(
            "min-h-[610px] overflow-hidden rounded-sm border border-[color-mix(in_srgb,var(--prototype-surface-text)_18%,transparent)] bg-[var(--prototype-surface)] text-[var(--prototype-surface-text)]",
            editing
              ? "transition-none"
              : "transition-[transform,width] motion-reduce:transition-none",
          )}
          data-prototype-theme={document.settings.theme}
          data-prototype-shell={shell.kind}
          data-prototype-viewport-width={viewportWidth}
          data-prototype-preview-zoom={zoom}
          data-prototype-preview-scale={previewScale.toFixed(2)}
          data-prototype-preview-scale-frozen={
            frozenFrameHeight !== null || frozenFitScale !== null ? "true" : "false"
          }
          style={{
            ...previewTheme(document),
            width: `${viewportWidth}px`,
            minWidth: `${viewportWidth}px`,
            minHeight: `${Math.max(PREVIEW_MIN_FRAME_HEIGHT, page.viewport.height)}px`,
            transform: `scale(${previewScale})`,
            transformOrigin: "top left",
          }}
        >
          <div className="grid min-h-9 grid-cols-[auto_minmax(0,1fr)] items-center gap-3 border-b border-[color-mix(in_srgb,var(--prototype-surface-text)_15%,transparent)] bg-[color-mix(in_srgb,var(--prototype-surface)_94%,var(--prototype-surface-text))] px-3">
            <div className="flex gap-1.5" aria-hidden>
              <span className="size-2 rounded-full bg-[#b8c3be]" />
              <span className="size-2 rounded-full bg-[#b8c3be]" />
              <span className="size-2 rounded-full bg-[#b8c3be]" />
            </div>
            <div className="truncate border border-[color-mix(in_srgb,var(--prototype-surface-text)_12%,transparent)] bg-[var(--prototype-surface)] px-3 py-1 text-[10px] text-[color-mix(in_srgb,var(--prototype-surface-text)_68%,transparent)]">
              prototype.local{page.route}
            </div>
          </div>
          <div
            className={cn("min-h-[570px]", sidebarExpanded ? "grid" : "flex flex-col")}
            style={
              sidebarExpanded
                ? { gridTemplateColumns: `${sidebarWidth}px minmax(0, 1fr)` }
                : undefined
            }
          >
            <NavigationContainer
              className={cn(
                "bg-[var(--prototype-navigation-background)] text-[var(--prototype-navigation-text)]",
                sidebarExpanded
                  ? "flex min-h-[570px] flex-col p-4"
                  : "flex min-h-14 items-center gap-3 px-4 py-2",
              )}
            >
              <div className="shrink-0 text-base font-bold">{shell.title}</div>
              <nav
                className={cn(
                  "gap-1",
                  sidebarExpanded ? "mt-6 grid" : "flex min-w-0 flex-1 overflow-x-auto",
                )}
                aria-label={t("prototype.structured.preview.navigation")}
              >
                {document.navigation.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={cn(
                      "min-h-10 shrink-0 px-3 text-left text-xs",
                      item.targetPageId === page.id
                        ? "bg-[var(--prototype-accent)] font-semibold text-[var(--prototype-accent-text)]"
                        : "opacity-75 hover:opacity-100",
                    )}
                    onClick={() => onPageSelect(item.targetPageId)}
                    aria-current={item.targetPageId === page.id ? "page" : undefined}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
              {showRoleControl && (
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 text-[10px] font-semibold",
                    sidebarExpanded ? "mt-auto" : "ml-auto",
                  )}
                >
                  <UserRound size={12} aria-hidden />
                  {t("prototype.structured.role.simulated", { role: role?.label ?? "-" })}
                </span>
              )}
            </NavigationContainer>
            <section className="min-w-0 bg-[var(--prototype-content-background)] text-[var(--prototype-content-text)]">
              <header className="flex min-h-12 items-center justify-between border-b border-[color-mix(in_srgb,var(--prototype-surface-text)_12%,transparent)] bg-[var(--prototype-surface)] px-4 text-[var(--prototype-surface-text)]">
                <div className="flex items-center gap-2 text-xs opacity-70">
                  {!sidebarExpanded && <Menu size={15} aria-hidden />}
                  {page.title}
                </div>
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
                document={document}
                page={page}
                runtimeState={runtimeState}
                viewModel={viewModel}
                viewportWidth={viewportWidth}
                previewScale={previewScale}
                editing={editing}
                selection={selection}
                formValues={formValues}
                disabled={disabled}
                dragDisabled={dragDisabled}
                resizeDisabled={resizeDisabled}
                gridSnappingEnabled={gridSnappingEnabled}
                marqueeDisabled={interactionBlocked || spacePressed}
                onSelect={onSelectNode}
                onSelectionChange={onSelectionChange}
                onMarqueeGestureChange={onMarqueeGestureChange}
                onFreeformMoveNode={onFreeformMoveNode}
                onFreeformMoveError={onFreeformMoveError}
                onFreeformMoveGestureChange={onFreeformMoveGestureChange}
                onFreeformGroupArrange={onFreeformGroupArrange}
                onFreeformSelectionNudge={onFreeformSelectionNudge}
                onResizeNode={onResizeNode}
                onResizeError={onResizeError}
                onResizeGestureChange={handleResizeGestureChange}
                onFormValue={onFormValue}
                onNodeActivate={onNodeActivate}
                onRowActivate={onRowActivate}
              />
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
