"use client";

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Check, GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";

import type { PrototypeRuntimeState, RuntimeEntity, RuntimeViewModel } from "../runtime/types";
import {
  type ProcurementRuntimeBindings,
  runtimeEntityFieldText,
  runtimeNodeRows,
  runtimeNodeText,
  runtimeNodeVisible,
} from "./structuredPrototypeDerived";
import type {
  StructuredPrototypeNode,
  StructuredPrototypePage,
  StructuredPrototypeTableNode,
} from "./types";

interface Props {
  page: StructuredPrototypePage;
  runtimeState: PrototypeRuntimeState | null;
  viewModel: RuntimeViewModel | null;
  runtimeBindings: ProcurementRuntimeBindings;
  selectedNodeId: string | null;
  formValues: Record<string, string>;
  disabled: boolean;
  onSelect: (nodeId: string) => void;
  onFormValue: (nodeId: string, value: string) => void;
  onSubmit: () => void;
  onApprove: () => void;
  onRowActivate: (entity: RuntimeEntity) => void;
}

interface NodeRendererProps extends Omit<Props, "page"> {
  node: StructuredPrototypeNode;
}

function toneClass(tone: "default" | "muted" | "success" | "warning" | "danger"): string {
  if (tone === "success") return "text-[#237a45]";
  if (tone === "warning") return "text-[#9a5b13]";
  if (tone === "danger") return "text-[#b4233a]";
  if (tone === "muted") return "text-[#62706b]";
  return "text-[#17201d]";
}

function runtimeStatusLabel(value: string): string {
  if (value === "pending") return "待审批";
  if (value === "approved") return "已通过";
  if (value === "not-selected") return "未选择申请";
  return value;
}

function RuntimeTable({
  node,
  viewModel,
  runtimeBindings,
  onRowActivate,
  disabled,
}: {
  node: StructuredPrototypeTableNode;
  viewModel: RuntimeViewModel | null;
  runtimeBindings: ProcurementRuntimeBindings;
  onRowActivate: (entity: RuntimeEntity) => void;
  disabled: boolean;
}) {
  const rows = runtimeNodeRows(viewModel, node.id);
  if (rows) {
    return (
      <div className="overflow-x-auto border border-[#d9dfdc] bg-white">
        <table className="w-full min-w-[520px] border-collapse text-left text-xs">
          <thead className="bg-[#f7f8f7] text-[#62706b]">
            <tr>
              <th className="px-3 py-2 font-semibold">申请事项</th>
              <th className="px-3 py-2 font-semibold">金额</th>
              <th className="px-3 py-2 font-semibold">状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((entity) => {
              const title = runtimeEntityFieldText(entity, runtimeBindings.titleEntityFieldId);
              const amount = runtimeEntityFieldText(entity, runtimeBindings.amountEntityFieldId);
              const status = runtimeEntityFieldText(entity, runtimeBindings.statusEntityFieldId);
              return (
                <tr key={entity.id} className="border-t border-[#e6eae8]">
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="font-semibold text-[#126b5f] hover:underline disabled:text-[#62706b]"
                      onClick={() => onRowActivate(entity)}
                      disabled={disabled}
                    >
                      {title}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-[#39443f]">¥ {amount}</td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 px-2 py-1 font-medium",
                        status === "approved"
                          ? "bg-[#e9f4ec] text-[#237a45]"
                          : "bg-[#fff2d8] text-[#9a5b13]",
                      )}
                    >
                      {status === "approved" && <Check size={12} aria-hidden />}
                      {runtimeStatusLabel(status)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="px-4 py-12 text-center text-sm text-[#62706b]">暂无采购申请</div>
        )}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border border-[#d9dfdc] bg-white">
      <table className="w-full border-collapse text-left text-xs">
        <thead className="bg-[#f7f8f7] text-[#62706b]">
          <tr>
            {node.columns.map((column) => (
              <th key={column.key} className="px-3 py-2 font-semibold">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {node.rows.map((row) => (
            <tr key={row.id} className="border-t border-[#e6eae8]">
              {row.cells.map((cell) => (
                <td key={cell.columnKey} className="px-3 py-2">
                  {cell.value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NodeRenderer({
  node,
  runtimeState,
  viewModel,
  runtimeBindings,
  selectedNodeId,
  formValues,
  disabled,
  onSelect,
  onFormValue,
  onSubmit,
  onApprove,
  onRowActivate,
}: NodeRendererProps) {
  if (node.visibility === "hidden" || !runtimeNodeVisible(viewModel, node.id)) return null;
  const select = (event: React.MouseEvent) => {
    event.stopPropagation();
    onSelect(node.id);
  };
  if (node.type === "Stack") {
    return (
      <div
        className={cn(
          "flex min-w-0",
          node.direction === "column" ? "flex-col" : "flex-row flex-wrap",
        )}
        style={{
          gap: node.gap,
          padding: `${node.padding.top}px ${node.padding.right}px ${node.padding.bottom}px ${node.padding.left}px`,
        }}
        onClick={select}
      >
        {node.children.map((child) => (
          <NodeRenderer
            key={child.id}
            node={child}
            runtimeState={runtimeState}
            viewModel={viewModel}
            runtimeBindings={runtimeBindings}
            selectedNodeId={selectedNodeId}
            formValues={formValues}
            disabled={disabled}
            onSelect={onSelect}
            onFormValue={onFormValue}
            onSubmit={onSubmit}
            onApprove={onApprove}
            onRowActivate={onRowActivate}
          />
        ))}
      </div>
    );
  }
  if (node.type === "Form") {
    return (
      <form
        className="grid border border-[#d9dfdc] bg-white p-5"
        style={{ gap: node.gap }}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        onClick={select}
      >
        {node.children.map((child) => (
          <NodeRenderer
            key={child.id}
            node={child}
            runtimeState={runtimeState}
            viewModel={viewModel}
            runtimeBindings={runtimeBindings}
            selectedNodeId={selectedNodeId}
            formValues={formValues}
            disabled={disabled}
            onSelect={onSelect}
            onFormValue={onFormValue}
            onSubmit={onSubmit}
            onApprove={onApprove}
            onRowActivate={onRowActivate}
          />
        ))}
      </form>
    );
  }
  if (node.type === "Text") {
    const text = runtimeNodeText(viewModel, node.id, node.content);
    if (node.semantic === "heading") {
      return (
        <h2 className={cn("text-xl font-bold", toneClass(node.tone))} onClick={select}>
          {runtimeStatusLabel(text)}
        </h2>
      );
    }
    return (
      <p className={cn("text-sm", toneClass(node.tone))} onClick={select}>
        {runtimeStatusLabel(text)}
      </p>
    );
  }
  if (node.type === "Input") {
    return (
      <label className="grid gap-1.5 text-xs font-semibold text-[#39443f]" onClick={select}>
        {node.label}
        <input
          className="min-h-10 w-full border border-[#c9d2ce] bg-white px-3 text-sm text-[#17201d] outline-none focus:border-[#126b5f] focus:ring-2 focus:ring-[#126b5f]/15"
          type={node.inputType}
          placeholder={node.placeholder}
          required={node.required}
          disabled={disabled || node.disabled}
          value={formValues[node.id] ?? node.value}
          onChange={(event) => onFormValue(node.id, event.target.value)}
        />
      </label>
    );
  }
  if (node.type === "Button") {
    const action =
      node.id === runtimeBindings.submitNodeId
        ? onSubmit
        : node.id === runtimeBindings.approveNodeId
          ? onApprove
          : undefined;
    return (
      <button
        type={node.id === runtimeBindings.submitNodeId ? "submit" : "button"}
        className={cn(
          "inline-flex min-h-10 w-fit items-center justify-center px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-45",
          node.variant === "primary" && "bg-[#126b5f] text-white hover:bg-[#0b554b]",
          node.variant === "secondary" && "border border-[#c9d2ce] bg-white text-[#17201d]",
          node.variant === "danger" && "bg-[#b4233a] text-white",
          node.variant === "ghost" && "bg-transparent text-[#126b5f]",
        )}
        disabled={disabled || node.disabled}
        onClick={(event) => {
          select(event);
          if (node.id !== runtimeBindings.submitNodeId) action?.();
        }}
      >
        {node.label}
      </button>
    );
  }
  return (
    <div onClick={select}>
      <RuntimeTable
        node={node}
        viewModel={viewModel}
        runtimeBindings={runtimeBindings}
        onRowActivate={onRowActivate}
        disabled={disabled}
      />
    </div>
  );
}

function SortableCanvasNode({ node, ...props }: NodeRendererProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: node.id,
    data: { kind: "node", nodeId: node.id },
    disabled: props.disabled,
  });
  if (node.visibility === "hidden" || !runtimeNodeVisible(props.viewModel, node.id)) return null;
  return (
    <section
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "group relative border bg-white p-3",
        props.selectedNodeId === node.id
          ? "border-[#126b5f] shadow-[0_0_0_2px_rgba(18,107,95,0.13)]"
          : "border-transparent hover:border-[#b7c8c1]",
        isDragging && "opacity-50",
      )}
      data-node-id={node.id}
      tabIndex={0}
      aria-label={`${node.type}: ${node.name}`}
      onFocus={() => props.onSelect(node.id)}
    >
      <button
        type="button"
        className="absolute right-1 top-1 z-10 grid size-7 place-items-center border border-[#d9dfdc] bg-white text-[#62706b] opacity-0 shadow-sm group-hover:opacity-100 focus:opacity-100"
        aria-label={`拖动 ${node.name}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} aria-hidden />
      </button>
      <NodeRenderer node={node} {...props} />
    </section>
  );
}

export function StructuredPrototypeCanvas({ page, ...props }: Props) {
  const root = page.root;
  const { setNodeRef, isOver } = useDroppable({
    id: `container:${root.id}`,
    data: { kind: "container", parentId: root.id },
    disabled: props.disabled,
  });
  if (root.type !== "Stack" && root.type !== "Form") {
    return <NodeRenderer node={root} {...props} />;
  }
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "grid min-h-[430px] content-start gap-2 p-4 transition-colors",
        isOver && "bg-[#e1f1ed]/65",
      )}
      data-container-id={root.id}
    >
      <SortableContext
        items={root.children.map((child) => child.id)}
        strategy={verticalListSortingStrategy}
      >
        {root.children.map((node) => (
          <SortableCanvasNode key={node.id} node={node} {...props} />
        ))}
      </SortableContext>
      {root.children.length === 0 && (
        <div className="grid min-h-48 place-items-center border border-dashed border-[#b8c3be] text-sm text-[#62706b]">
          将组件拖到这里
        </div>
      )}
    </div>
  );
}
