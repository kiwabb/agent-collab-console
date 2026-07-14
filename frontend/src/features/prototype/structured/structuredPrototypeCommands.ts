import { STRUCTURED_PROTOTYPE_AUTO_LAYOUT } from "./procurementDocumentFixture";
import type { StructuredPrototypePaletteType } from "./StructuredPrototypePalette";
import type { NewStructuredPrototypeNode, StructuredPrototypeCommandBatch } from "./types";

export function createPaletteNode(
  type: StructuredPrototypePaletteType,
  newNodeKey: string,
  formDefinitionId: string,
): NewStructuredPrototypeNode {
  const common = {
    newNodeKey,
    name: `${type} component`,
    visibility: "visible" as const,
    layoutItem: STRUCTURED_PROTOTYPE_AUTO_LAYOUT,
    responsive: [],
  };
  if (type === "Stack") {
    return {
      ...common,
      type,
      direction: "column",
      gap: 12,
      align: "stretch",
      justify: "start",
      padding: { top: 12, right: 12, bottom: 12, left: 12 },
      children: [],
    };
  }
  if (type === "Form") {
    return {
      ...common,
      type,
      formDefinitionId,
      gap: 12,
      padding: { top: 12, right: 12, bottom: 12, left: 12 },
      children: [
        {
          ...common,
          newNodeKey: `${newNodeKey}-field`,
          type: "Input",
          name: "Form field",
          label: "字段",
          placeholder: "请输入内容",
          value: "",
          inputType: "text",
          required: false,
          disabled: false,
        },
      ],
    };
  }
  if (type === "Text") {
    return {
      ...common,
      type,
      content: "新文本",
      semantic: "body",
      tone: "default",
    };
  }
  if (type === "Input") {
    return {
      ...common,
      type,
      label: "输入框",
      placeholder: "请输入内容",
      value: "",
      inputType: "text",
      required: false,
      disabled: false,
    };
  }
  if (type === "Button") {
    return {
      ...common,
      type,
      label: "按钮",
      variant: "primary",
      size: "medium",
      disabled: false,
      iconName: null,
    };
  }
  return {
    ...common,
    type,
    columns: [{ key: "column", label: "列" }],
    rows: [],
    density: "comfortable",
  };
}

export function insertPaletteNodeBatch(
  parentId: string,
  index: number,
  node: NewStructuredPrototypeNode,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: `Insert ${node.type} component`,
    commands: [
      {
        kind: "insertNode",
        parent: { kind: "existing", nodeId: parentId },
        slot: null,
        index,
        node,
      },
    ],
  };
}

export function moveNodeBatch(
  nodeId: string,
  parentId: string,
  targetIndex: number,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Move component",
    commands: [
      {
        kind: "moveNode",
        node: { kind: "existing", nodeId },
        targetParent: { kind: "existing", nodeId: parentId },
        targetSlot: null,
        targetIndex,
      },
    ],
  };
}
