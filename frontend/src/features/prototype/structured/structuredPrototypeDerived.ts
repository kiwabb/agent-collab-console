import type {
  RuntimeEntity,
  RuntimeValue,
  RuntimeViewModel,
  RuntimeViewProperty,
} from "../runtime/types";
import type { StructuredPrototypeDocument, StructuredPrototypeNode } from "./types";

export interface ProcurementRuntimeBindings {
  scenarioId: string;
  formId: string;
  titleFormFieldId: string;
  amountFormFieldId: string;
  titleInputNodeId: string;
  amountInputNodeId: string;
  submitNodeId: string;
  requestTableNodeId: string;
  approveNodeId: string;
  requestSchemaId: string;
  titleEntityFieldId: string;
  amountEntityFieldId: string;
  statusEntityFieldId: string;
}

function collectStructuredPrototypeNodes(
  node: StructuredPrototypeNode,
  target: StructuredPrototypeNode[],
): void {
  target.push(node);
  if (node.type !== "Stack" && node.type !== "Form") return;
  for (const child of node.children) collectStructuredPrototypeNodes(child, target);
}

export function deriveProcurementRuntimeBindings(
  document: StructuredPrototypeDocument,
): ProcurementRuntimeBindings | null {
  const runtime = document.runtime;
  const scenario = runtime.scenarios.find(
    (candidate) => candidate.key === "purchase-approval-happy-path",
  );
  const form = runtime.forms.find((candidate) => candidate.key === "create-purchase-request");
  const schema = runtime.entitySchemas.find((candidate) => candidate.key === "purchase-request");
  const submitRule = runtime.rules.find((candidate) => candidate.key === "submit-request");
  const selectRule = runtime.rules.find((candidate) => candidate.key === "select-request");
  const approveRule = runtime.rules.find((candidate) => candidate.key === "approve-request");
  const titleFormField = form?.fields.find((candidate) => candidate.key === "title");
  const amountFormField = form?.fields.find((candidate) => candidate.key === "amount");
  const titleEntityField = schema?.fields.find((candidate) => candidate.key === "title");
  const amountEntityField = schema?.fields.find((candidate) => candidate.key === "amount");
  const statusEntityField = schema?.fields.find((candidate) => candidate.key === "status");
  if (
    !scenario ||
    !form ||
    !schema ||
    !submitRule ||
    submitRule.trigger.event !== "submit" ||
    !selectRule ||
    selectRule.trigger.event !== "rowActivated" ||
    !approveRule ||
    approveRule.trigger.event !== "click" ||
    !titleFormField ||
    titleFormField.valueType !== "string" ||
    !amountFormField ||
    amountFormField.valueType !== "integer" ||
    !titleEntityField ||
    !amountEntityField ||
    !statusEntityField
  ) {
    return null;
  }

  const nodes: StructuredPrototypeNode[] = [];
  for (const page of document.pages) collectStructuredPrototypeNodes(page.root, nodes);
  const formNode = nodes.find((node) => node.type === "Form" && node.formDefinitionId === form.id);
  if (!formNode || formNode.type !== "Form") return null;
  const formNodes: StructuredPrototypeNode[] = [];
  collectStructuredPrototypeNodes(formNode, formNodes);
  const inputs = formNodes.filter((node) => node.type === "Input");
  const titleInputs = inputs.filter((node) => node.type === "Input" && node.inputType === "text");
  const amountInputs = inputs.filter(
    (node) => node.type === "Input" && node.inputType === "number",
  );
  const titleInput = titleInputs.length === 1 ? titleInputs[0] : null;
  const amountInput = amountInputs.length === 1 ? amountInputs[0] : null;
  if (!titleInput || !amountInput) return null;

  return {
    scenarioId: scenario.id,
    formId: form.id,
    titleFormFieldId: titleFormField.id,
    amountFormFieldId: amountFormField.id,
    titleInputNodeId: titleInput.id,
    amountInputNodeId: amountInput.id,
    submitNodeId: submitRule.trigger.nodeId,
    requestTableNodeId: selectRule.trigger.nodeId,
    approveNodeId: approveRule.trigger.nodeId,
    requestSchemaId: schema.id,
    titleEntityFieldId: titleEntityField.id,
    amountEntityFieldId: amountEntityField.id,
    statusEntityFieldId: statusEntityField.id,
  };
}

export function findStructuredPrototypeNode(
  node: StructuredPrototypeNode,
  nodeId: string,
): StructuredPrototypeNode | null {
  if (node.id === nodeId) return node;
  if (node.type !== "Stack" && node.type !== "Form") return null;
  for (const child of node.children) {
    const found = findStructuredPrototypeNode(child, nodeId);
    if (found) return found;
  }
  return null;
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

export function runtimeEntityFieldText(entity: RuntimeEntity, fieldId: string): string {
  const field = entity.fields.find((candidate) => candidate.fieldId === fieldId);
  return field ? runtimeValueText(field.value) : "";
}
