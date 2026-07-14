"use client";

import { useState } from "react";
import { Save } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";

import type {
  StructuredPrototypeCommandBatch,
  StructuredPrototypeLayoutItem,
  StructuredPrototypeNode,
  StructuredPrototypeNodePropertyUpdate,
} from "./types";

interface Props {
  node: StructuredPrototypeNode | null;
  disabled: boolean;
  onApply: (batch: StructuredPrototypeCommandBatch) => Promise<boolean>;
}

export interface StructuredPrototypeInspectorDraft {
  content: string;
  buttonVariant: "primary" | "secondary" | "danger" | "ghost";
  visibility: "visible" | "hidden";
  grow: number;
  alignSelf: StructuredPrototypeLayoutItem["alignSelf"];
}

function editableValue(node: StructuredPrototypeNode): string | null {
  if (node.type === "Text") return node.content;
  if (node.type === "Input") return node.label;
  if (node.type === "Button") return node.label;
  return null;
}

function propertyUpdate(
  node: StructuredPrototypeNode,
  value: string,
): StructuredPrototypeNodePropertyUpdate | null {
  if (node.type === "Text") return { kind: "textContent", content: value };
  if (node.type === "Input" || node.type === "Button") return { kind: "label", label: value };
  return null;
}

export function buildStructuredPrototypeInspectorBatch(
  node: StructuredPrototypeNode,
  draft: StructuredPrototypeInspectorDraft,
): StructuredPrototypeCommandBatch | null {
  const commands: StructuredPrototypeCommandBatch["commands"] = [];
  const initialContent = editableValue(node);
  const update = propertyUpdate(node, draft.content);
  if (update && draft.content !== initialContent) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update,
    });
  }
  if (node.type === "Button" && draft.buttonVariant !== node.variant) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "buttonVariant", variant: draft.buttonVariant },
    });
  }
  if (draft.visibility !== node.visibility) {
    commands.push({
      kind: "setNodeProperty",
      node: { kind: "existing", nodeId: node.id },
      update: { kind: "visibility", visibility: draft.visibility },
    });
  }
  if (draft.grow !== node.layoutItem.grow || draft.alignSelf !== node.layoutItem.alignSelf) {
    commands.push({
      kind: "setNodeLayout",
      node: { kind: "existing", nodeId: node.id },
      update: {
        grow: draft.grow,
        alignSelf: draft.alignSelf,
      },
    });
  }
  if (commands.length === 0) return null;
  return {
    commandContractVersion: 1,
    summary: `Edit ${node.type} properties`,
    commands,
  };
}

function EditableInspector({ node, disabled, onApply }: Props & { node: StructuredPrototypeNode }) {
  const { t } = useI18n();
  const initialValue = editableValue(node);
  const [value, setValue] = useState(initialValue ?? "");
  const [variant, setVariant] = useState(node.type === "Button" ? node.variant : "primary");
  const [visibility, setVisibility] = useState(node.visibility);
  const [grow, setGrow] = useState(node.layoutItem.grow);
  const [alignSelf, setAlignSelf] = useState(node.layoutItem.alignSelf);

  const save = async () => {
    const batch = buildStructuredPrototypeInspectorBatch(node, {
      content: value,
      buttonVariant: variant,
      visibility,
      grow,
      alignSelf,
    });
    if (batch) await onApply(batch);
  };

  return (
    <div className="grid gap-5 p-4">
      <div>
        <div className="text-xs font-bold uppercase text-[#62706b]">{node.type}</div>
        <div className="mt-1 truncate text-sm font-semibold text-[#17201d]">{node.name}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-[#7b8782]">{node.id}</div>
      </div>
      {initialValue !== null && (
        <label className="grid gap-2 text-xs font-semibold text-[#39443f]">
          {t("prototype.structured.inspector.content")}
          <textarea
            className="min-h-28 resize-y border border-[#c9d2ce] bg-white p-3 text-sm font-normal text-[#17201d] outline-none focus:border-[#126b5f] focus:ring-2 focus:ring-[#126b5f]/15"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={disabled}
          />
        </label>
      )}
      {node.type === "Button" && (
        <label className="grid gap-2 text-xs font-semibold text-[#39443f]">
          {t("prototype.structured.inspector.variant")}
          <select
            className="min-h-10 border border-[#c9d2ce] bg-white px-3 text-sm font-normal text-[#17201d]"
            value={variant}
            onChange={(event) =>
              setVariant(event.target.value as "primary" | "secondary" | "danger" | "ghost")
            }
            disabled={disabled}
          >
            <option value="primary">Primary</option>
            <option value="secondary">Secondary</option>
            <option value="danger">Danger</option>
            <option value="ghost">Ghost</option>
          </select>
        </label>
      )}
      <label className="grid gap-2 text-xs font-semibold text-[#39443f]">
        {t("prototype.structured.inspector.visibility")}
        <select
          className="min-h-10 border border-[#c9d2ce] bg-white px-3 text-sm font-normal text-[#17201d]"
          value={visibility}
          onChange={(event) => setVisibility(event.target.value as "visible" | "hidden")}
          disabled={disabled}
        >
          <option value="visible">{t("prototype.structured.inspector.visible")}</option>
          <option value="hidden">{t("prototype.structured.inspector.hidden")}</option>
        </select>
      </label>
      <label className="grid gap-2 text-xs font-semibold text-[#39443f]">
        {t("prototype.structured.inspector.grow")}
        <input
          className="min-h-10 border border-[#c9d2ce] bg-white px-3 text-sm font-normal text-[#17201d]"
          type="number"
          min={0}
          max={12}
          step={1}
          value={grow}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isSafeInteger(next) && next >= 0 && next <= 12) setGrow(next);
          }}
          disabled={disabled}
        />
      </label>
      <label className="grid gap-2 text-xs font-semibold text-[#39443f]">
        {t("prototype.structured.inspector.alignSelf")}
        <select
          className="min-h-10 border border-[#c9d2ce] bg-white px-3 text-sm font-normal text-[#17201d]"
          value={alignSelf}
          onChange={(event) =>
            setAlignSelf(event.target.value as StructuredPrototypeLayoutItem["alignSelf"])
          }
          disabled={disabled}
        >
          {(["auto", "start", "center", "end", "stretch"] as const).map((value) => (
            <option key={value} value={value}>
              {t(`prototype.structured.inspector.alignSelf.${value}`)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="inline-flex min-h-10 items-center justify-center gap-2 bg-[#126b5f] px-4 text-sm font-semibold text-white hover:bg-[#0b554b] disabled:cursor-not-allowed disabled:opacity-45"
        onClick={() => void save()}
        disabled={disabled}
      >
        <Save size={15} aria-hidden />
        {t("prototype.structured.inspector.save")}
      </button>
    </div>
  );
}

export function StructuredPrototypeInspector(props: Props) {
  const { t } = useI18n();
  if (!props.node) {
    return (
      <div className="grid min-h-56 place-items-center p-6 text-center text-sm text-[#62706b]">
        {t("prototype.structured.inspector.empty")}
      </div>
    );
  }
  return <EditableInspector key={props.node.id} {...props} node={props.node} />;
}
