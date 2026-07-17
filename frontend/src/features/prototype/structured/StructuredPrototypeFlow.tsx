"use client";

import { useCallback, useEffect, useMemo, useRef, type MouseEvent as ReactMouseEvent } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeDragHandler,
  type NodeMouseHandler,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Minus, Plus, Scan } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import {
  normalizeStructuredPrototypeFlowNodePosition,
  projectStructuredPrototypeFlow,
  resolveStructuredPrototypePendingFlowConnection,
  type StructuredPrototypeFlowEdgeData,
  type StructuredPrototypeFlowNodeData,
} from "./structuredPrototypeFlowProjection";
import type { StructuredPrototypePendingRuleConnection } from "./structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "./types";

interface Props {
  document: StructuredPrototypeDocument;
  disabled: boolean;
  saving: boolean;
  error: string | null;
  selectedPageId: string | null;
  selectedRuleId: string | null;
  onNodePositionChange: (flowNodeId: string, x: number, y: number) => Promise<boolean>;
  onPageSelect: (pageId: string) => void;
  onRuleSelect: (ruleId: string) => void;
  onConnectPages: (connection: StructuredPrototypePendingRuleConnection) => void;
}

function StructuredPrototypePageFlowNode({
  data,
  selected,
  dragging,
}: NodeProps<StructuredPrototypeFlowNodeData>) {
  const { t } = useI18n();
  return (
    <article
      className={cn(
        "w-60 border bg-surface-raised text-foreground shadow-sm transition-[border-color,box-shadow] motion-reduce:transition-none",
        selected ? "border-brand shadow-md ring-2 ring-brand/20" : "border-border-muted",
        dragging && "cursor-grabbing shadow-lg",
      )}
      data-prototype-flow-node={data.pageId}
      data-prototype-flow-node-selected={selected ? "true" : "false"}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable
        aria-label={t("prototype.structured.flow.connectTarget")}
        className="!size-2.5 !border-2 !border-surface-raised !bg-brand"
      />
      <div className="border-b border-border-subtle px-3 py-2.5">
        <h3 className="truncate text-sm font-bold">{data.title}</h3>
        <p className="mt-1 truncate font-mono text-[10px] text-text-muted">{data.route}</p>
      </div>
      <dl className="grid grid-cols-2 divide-x divide-border-subtle text-[10px] text-text-muted">
        <div className="flex items-center gap-1.5 px-3 py-2">
          <ArrowDownToLine size={12} aria-hidden />
          <dt>{t("prototype.structured.flow.incoming")}</dt>
          <dd className="ml-auto font-mono font-semibold text-foreground">{data.incomingCount}</dd>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-2">
          <ArrowUpFromLine size={12} aria-hidden />
          <dt>{t("prototype.structured.flow.outgoing")}</dt>
          <dd className="ml-auto font-mono font-semibold text-foreground">{data.outgoingCount}</dd>
        </div>
      </dl>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable
        aria-label={t("prototype.structured.flow.connectSource")}
        className="!size-2.5 !border-2 !border-surface-raised !bg-brand"
      />
    </article>
  );
}

const NODE_TYPES = { prototypePage: StructuredPrototypePageFlowNode };

function StructuredPrototypeFlowViewportControls() {
  const { t } = useI18n();
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const controls = [
    {
      key: "zoomIn",
      label: t("prototype.structured.flow.zoomIn"),
      icon: Plus,
      action: () => zoomIn({ duration: 160 }),
    },
    {
      key: "zoomOut",
      label: t("prototype.structured.flow.zoomOut"),
      icon: Minus,
      action: () => zoomOut({ duration: 160 }),
    },
    {
      key: "fit",
      label: t("prototype.structured.flow.fit"),
      icon: Scan,
      action: () => fitView({ duration: 160, padding: 0.2 }),
    },
  ];
  return (
    <Panel position="bottom-right" className="!m-3 grid gap-1">
      {controls.map((control) => {
        const Icon = control.icon;
        return (
          <button
            key={control.key}
            type="button"
            className="grid size-8 cursor-pointer place-items-center border border-border-muted bg-surface-raised text-text-muted shadow-sm hover:border-border-strong hover:text-foreground"
            onClick={control.action}
            aria-label={control.label}
            title={control.label}
          >
            <Icon size={14} aria-hidden />
          </button>
        );
      })}
    </Panel>
  );
}

export function StructuredPrototypeFlow({
  document,
  disabled,
  saving,
  error,
  selectedPageId,
  selectedRuleId,
  onNodePositionChange,
  onPageSelect,
  onRuleSelect,
  onConnectPages,
}: Props) {
  const { t } = useI18n();
  const projection = useMemo(() => projectStructuredPrototypeFlow(document), [document]);
  const projectedEdges = useMemo(
    () =>
      projection.edges.map((edge) => ({
        ...edge,
        selected: edge.data?.ruleId === selectedRuleId,
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--color-brand)" },
        style: {
          stroke: "var(--color-brand)",
          strokeWidth: edge.data?.ruleId === selectedRuleId ? 3 : 2,
        },
      })),
    [projection.edges, selectedRuleId],
  );
  const projectedNodes = useMemo(
    () =>
      projection.nodes.map((node) => ({
        ...node,
        selected: node.id === selectedPageId,
      })),
    [projection.nodes, selectedPageId],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(projectedNodes);
  const authoritativeNodesRef = useRef(projectedNodes);
  useEffect(() => {
    authoritativeNodesRef.current = projectedNodes;
    setNodes(projectedNodes);
  }, [projectedNodes, setNodes]);

  const handleConnect = useCallback(
    (connection: Connection): void => {
      if (disabled) return;
      const pending = resolveStructuredPrototypePendingFlowConnection(connection);
      if (pending !== null) onConnectPages(pending);
    },
    [disabled, onConnectPages],
  );
  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => onPageSelect(node.id),
    [onPageSelect],
  );
  const handleEdgeClick = useCallback(
    (_event: ReactMouseEvent, edge: Edge<StructuredPrototypeFlowEdgeData>) => {
      if (edge.data === undefined) {
        throw new Error(`structured prototype flow edge ${edge.id} has no rule projection`);
      }
      onRuleSelect(edge.data.ruleId);
    },
    [onRuleSelect],
  );

  const handleNodeDragStop = useCallback<NodeDragHandler>(
    (_event, node) => {
      if (disabled) return;
      const position = normalizeStructuredPrototypeFlowNodePosition(node.position);
      setNodes((current) =>
        current.map((candidate) =>
          candidate.id === node.id ? { ...candidate, position } : candidate,
        ),
      );
      void onNodePositionChange(node.id, position.x, position.y).then((applied) => {
        if (!applied) setNodes(authoritativeNodesRef.current);
      });
    },
    [disabled, onNodePositionChange, setNodes],
  );

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] bg-background/35">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-4 py-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-bold text-foreground">{document.title}</h2>
          <p className="mt-1 text-xs text-text-muted">
            {t("prototype.structured.flow.summary", {
              pages: document.pages.length,
              rules: document.runtime.rules.length,
            })}
          </p>
        </div>
        <span
          className={cn(
            "inline-flex min-w-0 items-center gap-2 text-xs font-semibold",
            error === null ? "text-status-done" : "max-w-md text-status-failed",
          )}
          role="status"
          aria-live="polite"
        >
          {error === null && <CheckCircle2 size={15} aria-hidden />}
          <span className="truncate">
            {error ??
              t(saving ? "prototype.structured.flow.saving" : "prototype.structured.flow.saved")}
          </span>
        </span>
      </header>
      <div className="min-h-0" data-prototype-flow-disabled={disabled ? "true" : "false"}>
        <ReactFlow
          nodes={nodes}
          edges={projectedEdges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onNodeDragStop={handleNodeDragStop}
          onNodeClick={handleNodeClick}
          onEdgeClick={handleEdgeClick}
          onConnect={handleConnect}
          nodesDraggable={!disabled}
          nodesConnectable={!disabled}
          nodesFocusable
          edgesUpdatable={false}
          edgesFocusable
          elementsSelectable
          deleteKeyCode={null}
          panOnDrag
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="var(--color-border-muted)"
          />
          <StructuredPrototypeFlowViewportControls />
        </ReactFlow>
      </div>
    </div>
  );
}
