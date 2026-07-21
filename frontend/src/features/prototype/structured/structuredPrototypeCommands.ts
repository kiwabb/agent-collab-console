import type { RuntimeFormDefinition, RuntimeValue } from "../runtime/types";
import type { StructuredPrototypePaletteType } from "./StructuredPrototypePalette";
import type {
  StructuredPrototypeBehaviorRuleDefinition,
  StructuredPrototypeCommand,
  StructuredPrototypeFreeformPosition,
  NewStructuredPrototypeNode,
  StructuredPrototypeCommandBatch,
  StructuredPrototypeDocument,
  StructuredPrototypeFreeformNode,
  StructuredPrototypeLayoutItem,
} from "./types";
import { projectStructuredPrototypePageReorder } from "./structuredPrototypeDrag";
import { canonicalStructuredPrototypeFreeformValue } from "./structuredPrototypeFreeformGeometry";
import { normalizeStructuredPrototypeFlowPosition } from "./structuredPrototypeFlowProjection";
import type { StructuredPrototypeGroupTransformItem } from "./structuredPrototypeGroupTransform";
import type { StructuredPrototypeContainerNode } from "./structuredPrototypeNodes";

export const STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT = 100;

export type StructuredPrototypePageAllocationKind = "add" | "duplicate";

export function structuredPrototypePageAllocationKey(
  kind: StructuredPrototypePageAllocationKind,
  pageId: string,
): string {
  return `page-${kind}-${pageId.replaceAll("-", "")}`;
}

function normalizedCommandName(value: string, label: string): string {
  const normalized = value.trim();
  if (normalized.length === 0) {
    throw new Error(`${label} cannot be empty`);
  }
  if (normalized.length > 80) {
    throw new Error(`${label} cannot exceed 80 characters`);
  }
  return normalized;
}

const AUTO_LAYOUT_ITEM: StructuredPrototypeLayoutItem = {
  width: { unit: "auto", value: null },
  minWidth: null,
  maxWidth: null,
  height: { unit: "auto", value: null },
  minHeight: null,
  maxHeight: null,
  grow: 0,
  shrink: 1,
  alignSelf: "stretch",
};

export function createPaletteNode(
  type: StructuredPrototypePaletteType,
  newNodeKey: string,
  formDefinition: RuntimeFormDefinition | null,
  labels: Record<StructuredPrototypePaletteType, string>,
): NewStructuredPrototypeNode {
  const common = {
    newNodeKey,
    name: labels[type],
    visibility: "visible" as const,
    layoutItem: AUTO_LAYOUT_ITEM,
    responsive: [],
  };
  if (type === "Freeform") {
    return {
      ...common,
      type,
      layoutItem: {
        ...AUTO_LAYOUT_ITEM,
        width: { unit: "px", value: "960" },
        height: { unit: "px", value: "640" },
        shrink: 0,
        alignSelf: "start",
      },
      children: [],
    };
  }
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
  if (type === "Grid") {
    return {
      ...common,
      type,
      columns: 1,
      gap: 12,
      padding: { top: 12, right: 12, bottom: 12, left: 12 },
      columnOverrides: [{ minWidth: 768, columns: 2 }],
      children: [],
    };
  }
  if (type === "Form") {
    if (formDefinition === null) {
      throw new Error("a runtime form definition is required to insert a Form node");
    }
    return {
      ...common,
      type,
      name: `${labels.Form}: ${formDefinition.key}`,
      formDefinitionId: formDefinition.id,
      gap: 12,
      padding: { top: 12, right: 12, bottom: 12, left: 12 },
      children: formDefinition.fields.map((field) => ({
        ...common,
        newNodeKey: `${newNodeKey}-${field.key}`,
        type: "Input",
        name: `${labels.Input}: ${field.key}`,
        label: field.key,
        placeholder: "",
        value: String(field.initialValue.value),
        inputType: field.valueType === "integer" ? "number" : "text",
        required: field.required,
        disabled: false,
        formDefinitionId: formDefinition.id,
        formFieldId: field.id,
      })),
    };
  }
  if (type === "Text") {
    return {
      ...common,
      type,
      content: labels.Text,
      semantic: "body",
      tone: "default",
    };
  }
  if (type === "Input") {
    return {
      ...common,
      type,
      label: labels.Input,
      placeholder: "",
      value: "",
      inputType: "text",
      required: false,
      disabled: false,
      formDefinitionId: null,
      formFieldId: null,
    };
  }
  if (type === "Button") {
    return {
      ...common,
      type,
      label: labels.Button,
      variant: "primary",
      size: "medium",
      disabled: false,
      iconName: null,
    };
  }
  if (type === "Divider") {
    return {
      ...common,
      type,
      spacing: 12,
      tone: "default",
    };
  }
  if (type === "Badge") {
    return {
      ...common,
      type,
      label: "徽章",
      tone: "default",
      iconName: null,
    };
  }
  return {
    ...common,
    type,
    columns: [{ key: "column", label: labels.Table, fieldId: null }],
    rows: [],
    density: "comfortable",
  };
}

export function resolvePaletteFormDefinition(
  forms: RuntimeFormDefinition[],
  selectedFormId: string | null,
): RuntimeFormDefinition | null {
  if (selectedFormId !== null) {
    const selected = forms.find((form) => form.id === selectedFormId);
    if (selected) return selected;
  }
  return forms.length === 1 ? (forms[0] ?? null) : null;
}

export function insertPaletteNodeBatch(
  parent: StructuredPrototypeContainerNode,
  index: number,
  node: NewStructuredPrototypeNode,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeCommandBatch {
  if (parent.type === "Freeform" && (targetPosition === undefined || targetPosition === null)) {
    throw new Error("a position is required to insert a node into a Freeform container");
  }
  const flowLayoutItem = { ...node.layoutItem };
  delete flowLayoutItem.position;
  const positionedNode =
    targetPosition === undefined
      ? node
      : targetPosition === null
        ? { ...node, layoutItem: flowLayoutItem }
        : { ...node, layoutItem: { ...node.layoutItem, position: targetPosition } };
  return {
    commandContractVersion: 1,
    summary: `Insert ${node.type} component`,
    commands: [
      {
        kind: "insertNode",
        parent: { kind: "existing", nodeId: parent.id },
        slot: null,
        index,
        node: positionedNode,
      },
    ],
  };
}

export function moveNodeBatch(
  nodeId: string,
  parent: StructuredPrototypeContainerNode,
  targetIndex: number,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeCommandBatch {
  if (parent.type === "Freeform" && (targetPosition === undefined || targetPosition === null)) {
    throw new Error("a target position is required to move a node into a Freeform container");
  }
  return {
    commandContractVersion: 1,
    summary: "Move component",
    commands: [
      {
        kind: "moveNode",
        node: { kind: "existing", nodeId },
        targetParent: { kind: "existing", nodeId: parent.id },
        targetSlot: null,
        targetIndex,
        ...(targetPosition === undefined ? {} : { targetPosition }),
      },
    ],
  };
}

export interface StructuredPrototypePositionedMoveCommandItem {
  nodeId: string;
  x: number;
  y: number;
}

export type StructuredPrototypeFreeformMoveCommandItem =
  StructuredPrototypePositionedMoveCommandItem;

export function movePositionedSelectionBatch(
  parent: StructuredPrototypeContainerNode,
  items: readonly StructuredPrototypePositionedMoveCommandItem[],
  summary: string,
): StructuredPrototypeCommandBatch {
  if (items.length === 0 || items.length > STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT) {
    throw new Error(
      `a positioned move batch requires 1 to ${STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT} items`,
    );
  }
  const itemsById = new Map<string, StructuredPrototypePositionedMoveCommandItem>();
  for (const item of items) {
    if (itemsById.has(item.nodeId)) {
      throw new Error(`positioned move node is duplicated: ${item.nodeId}`);
    }
    itemsById.set(item.nodeId, item);
  }
  const commands = parent.children.flatMap((child, targetIndex) => {
    const item = itemsById.get(child.id);
    if (item === undefined) return [];
    return [
      {
        kind: "moveNode" as const,
        node: { kind: "existing" as const, nodeId: child.id },
        targetParent: { kind: "existing" as const, nodeId: parent.id },
        targetSlot: null,
        targetIndex,
        targetPosition: {
          x: canonicalStructuredPrototypeFreeformValue(item.x),
          y: canonicalStructuredPrototypeFreeformValue(item.y),
        },
      },
    ];
  });
  if (commands.length !== items.length) {
    throw new Error("every positioned move node must be a direct child of the target container");
  }
  return {
    commandContractVersion: 1,
    summary,
    commands,
  };
}

export function moveFreeformSelectionBatch(
  parent: StructuredPrototypeFreeformNode,
  items: readonly StructuredPrototypeFreeformMoveCommandItem[],
  summary: string,
): StructuredPrototypeCommandBatch {
  return movePositionedSelectionBatch(parent, items, summary);
}

export function setPositionedGroupLayoutBatch(
  items: readonly StructuredPrototypeGroupTransformItem[],
  mode: "position" | "frame",
  summary: string,
): StructuredPrototypeCommandBatch {
  if (items.length === 0 || items.length > STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT) {
    throw new Error(
      `a group layout batch requires 1 to ${STRUCTURED_PROTOTYPE_COMMAND_BATCH_LIMIT} items`,
    );
  }
  return {
    commandContractVersion: 1,
    summary,
    commands: items.map((item) => ({
      kind: "setNodeLayout",
      node: { kind: "existing", nodeId: item.nodeId },
      update: {
        ...(mode === "frame"
          ? {
              width: {
                unit: "px" as const,
                value: canonicalStructuredPrototypeFreeformValue(item.width),
              },
              height: {
                unit: "px" as const,
                value: canonicalStructuredPrototypeFreeformValue(item.height),
              },
            }
          : {}),
        position: {
          x: canonicalStructuredPrototypeFreeformValue(item.x),
          y: canonicalStructuredPrototypeFreeformValue(item.y),
        },
      },
    })),
  };
}

export function setFreeformGroupLayoutBatch(
  items: readonly StructuredPrototypeGroupTransformItem[],
  mode: "position" | "frame",
  summary: string,
): StructuredPrototypeCommandBatch {
  return setPositionedGroupLayoutBatch(items, mode, summary);
}

export function removeNodeBatch(nodeId: string): StructuredPrototypeCommandBatch {
  return removeNodesBatch([nodeId]);
}

export function removeNodesBatch(nodeIds: readonly string[]): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: nodeIds.length === 1 ? "Remove component" : `Remove ${nodeIds.length} components`,
    commands: nodeIds.map((nodeId) => ({ kind: "removeNode", nodeId })),
  };
}

export function updateNodeNameBatch(nodeId: string, name: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Rename component",
    commands: [
      { kind: "updateNodeName", nodeId, name: normalizedCommandName(name, "Component name") },
    ],
  };
}

export function reorderPageBatch(
  document: StructuredPrototypeDocument,
  pageId: string,
  targetIndex: number,
): StructuredPrototypeCommandBatch | null {
  const projected = projectStructuredPrototypePageReorder(document, pageId, targetIndex);
  if (projected === null) return null;
  const navigationCommands = resolveStructuredPrototypeNavigationReorderCommands(
    document.navigation.items,
    projected.navigation.items,
  );
  return {
    commandContractVersion: 1,
    summary: "Reorder page",
    commands: [{ kind: "reorderPage", pageId, targetIndex }, ...navigationCommands],
  };
}

export function addPageBatch(
  afterPageId: string,
  title: string,
  includeInNavigation: boolean,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Add page",
    commands: [
      {
        kind: "addPage",
        afterPageId,
        newPageKey: structuredPrototypePageAllocationKey("add", afterPageId),
        title: normalizedCommandName(title, "Page title"),
        includeInNavigation,
      },
    ],
  };
}

export function duplicatePageBatch(pageId: string, title: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Duplicate page",
    commands: [
      {
        kind: "duplicatePage",
        pageId,
        newPageKey: structuredPrototypePageAllocationKey("duplicate", pageId),
        title: normalizedCommandName(title, "Page title"),
      },
    ],
  };
}

export function renamePageBatch(pageId: string, title: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Rename page",
    commands: [{ kind: "renamePage", pageId, title: normalizedCommandName(title, "Page title") }],
  };
}

export function deletePageBatch(pageId: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Delete page",
    commands: [{ kind: "deletePage", pageId }],
  };
}

export function resolveStructuredPrototypeNavigationReorderCommands(
  current: StructuredPrototypeDocument["navigation"]["items"],
  target: StructuredPrototypeDocument["navigation"]["items"],
): StructuredPrototypeCommand[] {
  const workingIds = current.map((item) => item.id);
  const commands: StructuredPrototypeCommand[] = [];
  target.forEach((item, targetIndex) => {
    const sourceIndex = workingIds.indexOf(item.id);
    if (sourceIndex < 0 || sourceIndex === targetIndex) return;
    commands.push({ kind: "reorderNavigationItem", itemId: item.id, targetIndex });
    workingIds.splice(sourceIndex, 1);
    workingIds.splice(targetIndex, 0, item.id);
  });
  return commands;
}

export function setRuntimeFlowNodePositionBatch(
  flowNodeId: string,
  x: number,
  y: number,
): StructuredPrototypeCommandBatch {
  const position = normalizeStructuredPrototypeFlowPosition({ x, y });
  return {
    commandContractVersion: 1,
    summary: "Move flow node",
    commands: [
      {
        kind: "setRuntimeFlowNodePosition",
        flowNodeId,
        x: position.x,
        y: position.y,
      },
    ],
  };
}

export function setRuntimeEntityFieldBatch(
  scenarioId: string,
  schemaId: string,
  entityId: string,
  fieldId: string,
  value: RuntimeValue,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Edit runtime table cell",
    commands: [
      {
        kind: "setRuntimeEntityField",
        scenarioId,
        schemaId,
        entityId,
        fieldId,
        value,
      },
    ],
  };
}

export function addBehaviorRuleBatch(
  newRuleKey: string,
  definition: StructuredPrototypeBehaviorRuleDefinition,
): StructuredPrototypeCommandBatch {
  if (newRuleKey !== definition.key) {
    throw new Error("newRuleKey must match the behavior rule definition key");
  }
  return {
    commandContractVersion: 1,
    summary: "Add behavior rule",
    commands: [{ kind: "addBehaviorRule", newRuleKey, definition }],
  };
}

export function replaceBehaviorRuleBatch(
  ruleId: string,
  definition: StructuredPrototypeBehaviorRuleDefinition,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Replace behavior rule",
    commands: [{ kind: "replaceBehaviorRule", ruleId, definition }],
  };
}

export function removeBehaviorRuleBatch(ruleId: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Remove behavior rule",
    commands: [{ kind: "removeBehaviorRule", ruleId }],
  };
}

/**
 * Snapshot an existing page subtree as a reusable component definition. The
 * backend clones the subtree with fresh deterministic ids; the definition is a
 * detached template with no live link back to the source node.
 */
export function defineComponentBatch(key: string, nodeId: string): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Define component",
    commands: [{ kind: "defineComponent", key, sourceNode: { kind: "existing", nodeId } }],
  };
}

export function removeComponentDefinitionBatch(
  componentId: string,
): StructuredPrototypeCommandBatch {
  return {
    commandContractVersion: 1,
    summary: "Remove component definition",
    commands: [{ kind: "removeComponentDefinition", componentId }],
  };
}

/**
 * Insert a DETACHED clone of a component definition into a container. The
 * instance gets fresh server-allocated ids and never syncs with its definition.
 */
export function instantiateComponentBatch(
  componentId: string,
  parent: StructuredPrototypeContainerNode,
  index: number,
  targetPosition?: StructuredPrototypeFreeformPosition | null,
): StructuredPrototypeCommandBatch {
  if (parent.type === "Freeform" && (targetPosition === undefined || targetPosition === null)) {
    throw new Error("a position is required to insert a component into a Freeform container");
  }
  return {
    commandContractVersion: 1,
    summary: "Instantiate component",
    commands: [
      {
        kind: "instantiateComponent",
        componentId,
        parent: { kind: "existing", nodeId: parent.id },
        index,
        ...(targetPosition === undefined ? {} : { targetPosition }),
      },
    ],
  };
}
