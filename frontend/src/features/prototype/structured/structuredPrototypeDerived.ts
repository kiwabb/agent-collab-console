import type {
  RuntimeEntity,
  RuntimeEvent,
  RuntimeNodeTrigger,
  TableRowsViewBinding,
  RuntimeValue,
  RuntimeViewModel,
  RuntimeViewProperty,
} from "../runtime/types";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeFormNode,
  StructuredPrototypeInputNode,
  StructuredPrototypeNode,
} from "./types";
import { isStructuredPrototypeContainerNode } from "./structuredPrototypeNodes";

const RUNTIME_NODE_TRIGGER_EVENT_ORDER = [
  "click",
  "submit",
  "rowActivated",
] as const satisfies readonly RuntimeNodeTrigger["event"][];

export function defaultRuntimeScenarioId(document: StructuredPrototypeDocument): string {
  const scenario = document.runtime.scenarios[0];
  if (scenario === undefined) throw new Error("structured prototype has no runtime scenario");
  return scenario.id;
}

export function runtimeNodeTriggerEvents(
  document: StructuredPrototypeDocument,
  nodeId: string,
): RuntimeNodeTrigger["event"][] {
  const events = new Set(
    document.runtime.rules
      .filter((rule) => rule.enabled && rule.trigger.nodeId === nodeId)
      .map((rule) => rule.trigger.event),
  );
  return RUNTIME_NODE_TRIGGER_EVENT_ORDER.filter((event) => events.has(event));
}

export function runtimeNodeActivationEvents(
  document: StructuredPrototypeDocument,
  nodeId: string,
): Extract<RuntimeEvent, { kind: "nodeActivated" }>[] {
  return runtimeNodeTriggerEvents(document, nodeId).flatMap((event) =>
    event === "rowActivated" ? [] : [{ kind: "nodeActivated", nodeId, event }],
  );
}

export function runtimeTableRowsBinding(
  document: StructuredPrototypeDocument,
  nodeId: string,
): TableRowsViewBinding | null {
  const binding = document.runtime.viewBindings.find(
    (candidate) => candidate.nodeId === nodeId && candidate.target === "tableRows",
  );
  return binding?.target === "tableRows" ? binding : null;
}

export function findStructuredPrototypeFormForNode(
  document: StructuredPrototypeDocument,
  nodeId: string,
): StructuredPrototypeFormNode | null {
  const visit = (
    node: StructuredPrototypeNode,
    containingForm: StructuredPrototypeFormNode | null,
  ): StructuredPrototypeFormNode | null | undefined => {
    const nextForm = node.type === "Form" ? node : containingForm;
    if (node.id === nodeId) return nextForm;
    if (!isStructuredPrototypeContainerNode(node)) return undefined;
    for (const child of node.children) {
      const found = visit(child, nextForm);
      if (found !== undefined) return found;
    }
    return undefined;
  };
  for (const page of document.pages) {
    const found = visit(page.root, null);
    if (found !== undefined) return found;
  }
  return null;
}

export function structuredPrototypeInputNodes(
  node: StructuredPrototypeNode,
): StructuredPrototypeInputNode[] {
  const result: StructuredPrototypeInputNode[] = [];
  const visit = (candidate: StructuredPrototypeNode) => {
    if (candidate.type === "Input") result.push(candidate);
    if (isStructuredPrototypeContainerNode(candidate)) {
      for (const child of candidate.children) visit(child);
    }
  };
  visit(node);
  return result;
}

export function findStructuredPrototypeNode(
  node: StructuredPrototypeNode,
  nodeId: string,
): StructuredPrototypeNode | null {
  if (node.id === nodeId) return node;
  if (!isStructuredPrototypeContainerNode(node)) return null;
  for (const child of node.children) {
    const found = findStructuredPrototypeNode(child, nodeId);
    if (found) return found;
  }
  return null;
}

export function structuredPrototypeSubtreeHasRuntimeReferences(
  document: StructuredPrototypeDocument,
  node: StructuredPrototypeNode,
): boolean {
  const nodeIds = new Set<string>();
  const visit = (candidate: StructuredPrototypeNode): void => {
    nodeIds.add(candidate.id);
    if (isStructuredPrototypeContainerNode(candidate)) {
      for (const child of candidate.children) visit(child);
    }
  };
  visit(node);
  return (
    document.runtime.viewBindings.some((binding) => nodeIds.has(binding.nodeId)) ||
    document.runtime.rules.some((rule) => nodeIds.has(rule.trigger.nodeId)) ||
    document.flows.some((flow) => nodeIds.has(flow.fromNodeId))
  );
}

export function runtimeViewProperties(
  viewModel: RuntimeViewModel | null,
  nodeId: string,
): RuntimeViewProperty[] {
  return viewModel?.nodes.find((node) => node.nodeId === nodeId)?.properties ?? [];
}

export function runtimeNodeVisible(viewModel: RuntimeViewModel | null, nodeId: string): boolean {
  const property = runtimeViewProperties(viewModel, nodeId).find(
    (candidate) => candidate.target === "visibility",
  );
  return property?.target === "visibility" ? property.value.value : true;
}

export function runtimeNodeText(
  viewModel: RuntimeViewModel | null,
  nodeId: string,
  fallback: string,
): string {
  const property = runtimeViewProperties(viewModel, nodeId).find(
    (candidate) => candidate.target === "textContent",
  );
  return property?.target === "textContent" ? runtimeValueText(property.value) : fallback;
}

export function runtimeNodeRows(
  viewModel: RuntimeViewModel | null,
  nodeId: string,
): RuntimeEntity[] | null {
  const property = runtimeViewProperties(viewModel, nodeId).find(
    (candidate) => candidate.target === "tableRows",
  );
  return property?.target === "tableRows" ? property.rows : null;
}

export function runtimeValueText(value: RuntimeValue): string {
  switch (value.type) {
    case "null":
      return "";
    case "boolean":
      return value.value ? "true" : "false";
    case "integer":
      return String(value.value);
    case "string":
    case "enum":
      return value.value;
    case "entityRef":
      return value.entityId;
  }
}

export function runtimeEntityFieldText(entity: RuntimeEntity, fieldId: string | null): string {
  if (fieldId === null) throw new Error("runtime table column has no schema field binding");
  const field = entity.fields.find((candidate) => candidate.fieldId === fieldId);
  if (field === undefined) {
    throw new Error(`runtime entity ${entity.id} has no value for table field ${fieldId}`);
  }
  return runtimeValueText(field.value);
}
