import {
  applyRuntimeEventBatch,
  createInitialRuntimeState,
  deriveRuntimeViewModel,
} from "../src/features/prototype/runtime/runtimeCore";
import type {
  PrototypeRuntimeState,
  RuntimeEntity,
  RuntimeEvent,
  RuntimeValue,
  RuntimeViewModel,
} from "../src/features/prototype/runtime/types";
import {
  deriveFormInputBindings,
  type FormInputBinding,
} from "../src/features/prototype/structured/prototypeRendererCore";
import { parseRendererDocument } from "../src/features/prototype/structured/rendererDocumentCodec";
import {
  runtimeNodeActivationEvents,
  runtimeNodeTriggerEvents,
} from "../src/features/prototype/structured/structuredPrototypeDerived";
import { isStructuredPrototypeContainerNode } from "../src/features/prototype/structured/structuredPrototypeNodes";
import type {
  StructuredPrototypeDocument,
  StructuredPrototypeTableNode,
} from "../src/features/prototype/structured/types";

interface PublicRuntime {
  document: StructuredPrototypeDocument;
  state: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
  manualPageId: string | null;
  inputBindings: Map<string, FormInputBinding>;
  eventNo: number;
}

function requiredElement<ElementType extends Element>(
  root: ParentNode,
  selector: string,
  constructor: { new (): ElementType },
): ElementType {
  const element = root.querySelector(selector);
  if (!(element instanceof constructor))
    throw new Error(`Published prototype is missing ${selector}`);
  return element;
}

function runtimeValueText(value: RuntimeValue): string {
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

function nodeElement(nodeId: string): HTMLElement | null {
  const element = document.querySelector(`[data-prototype-node-id="${nodeId}"]`);
  return element instanceof HTMLElement ? element : null;
}

function findTableNode(
  documentValue: StructuredPrototypeDocument,
  nodeId: string,
): StructuredPrototypeTableNode | null {
  const visit = (
    node: StructuredPrototypeDocument["pages"][number]["root"],
  ): StructuredPrototypeTableNode | null => {
    if (node.id === nodeId) return node.type === "Table" ? node : null;
    if (isStructuredPrototypeContainerNode(node)) {
      for (const child of node.children) {
        const found = visit(child);
        if (found !== null) return found;
      }
    }
    return null;
  };
  for (const page of documentValue.pages) {
    const found = visit(page.root);
    if (found !== null) return found;
  }
  return null;
}

function renderTable(runtime: PublicRuntime, nodeId: string, rows: RuntimeEntity[]): void {
  const node = findTableNode(runtime.document, nodeId);
  if (node === null) throw new Error(`Runtime table ${nodeId} does not exist`);
  const root = nodeElement(nodeId);
  const body = root?.querySelector("tbody");
  if (!(body instanceof HTMLTableSectionElement)) {
    throw new Error(`Runtime table ${nodeId} has no table body`);
  }
  const binding = runtime.document.runtime.viewBindings.find(
    (candidate) => candidate.nodeId === nodeId && candidate.target === "tableRows",
  );
  if (binding === undefined || binding.target !== "tableRows") {
    throw new Error(`Runtime table ${nodeId} has no rows binding`);
  }
  const renderedRows: HTMLTableRowElement[] = [];
  for (const entity of rows) {
    const row = document.createElement("tr");
    row.dataset["entityId"] = entity.id;
    row.dataset["schemaId"] = entity.schemaId;
    for (const column of node.columns) {
      if (column.fieldId === null) {
        throw new Error(`Runtime table ${nodeId} column ${column.key} has no schema field binding`);
      }
      const field = entity.fields.find((candidate) => candidate.fieldId === column.fieldId);
      if (field === undefined) {
        throw new Error(
          `Runtime entity ${entity.id} has no value for table field ${column.fieldId}`,
        );
      }
      const cell = document.createElement("td");
      cell.textContent = runtimeValueText(field.value);
      row.append(cell);
    }
    renderedRows.push(row);
  }
  body.replaceChildren(...renderedRows);
}

function renderRuntime(runtime: PublicRuntime): void {
  const activePageId = runtime.manualPageId ?? runtime.state.currentPageId;
  document.querySelectorAll<HTMLElement>("[data-prototype-page-id]").forEach((page) => {
    page.dataset["active"] = String(page.dataset["prototypePageId"] === activePageId);
  });
  document.querySelectorAll<HTMLButtonElement>("[data-navigation-target]").forEach((item) => {
    item.setAttribute(
      "aria-current",
      item.dataset["navigationTarget"] === activePageId ? "page" : "false",
    );
  });
  const page = runtime.document.pages.find((candidate) => candidate.id === activePageId);
  const title = requiredElement(document, "[data-current-page-title]", HTMLElement);
  title.textContent = page?.title ?? runtime.document.title;
  const role = runtime.document.runtime.roles.find(
    (candidate) => candidate.id === runtime.state.actorRoleId,
  );
  const roleSelect = requiredElement(document, "[data-role-select]", HTMLSelectElement);
  roleSelect.value = runtime.state.actorRoleId;
  roleSelect.disabled = !runtime.state.allowSimulatedRoleSwitch;
  requiredElement(document, "[data-current-role-label]", HTMLElement).textContent =
    role?.label ?? runtime.state.actorRoleId;
  const notification = runtime.state.notifications.at(-1);
  const notificationElement = requiredElement(document, "[data-runtime-notification]", HTMLElement);
  notificationElement.dataset["visible"] = String(notification !== undefined);
  notificationElement.dataset["level"] = notification?.level ?? "info";
  notificationElement.textContent = notification?.message ?? "";
  for (const node of runtime.viewModel.nodes) {
    const element = nodeElement(node.nodeId);
    if (element === null) continue;
    for (const property of node.properties) {
      switch (property.target) {
        case "textContent":
          element.textContent = runtimeValueText(property.value);
          break;
        case "visibility":
          element.hidden = !property.value.value;
          break;
        case "tableRows":
          renderTable(runtime, node.nodeId, property.rows);
          break;
      }
    }
  }
  for (const form of runtime.state.formStates) {
    for (const binding of runtime.inputBindings.values()) {
      if (binding.formId !== form.formId) continue;
      const input = document.querySelector<HTMLInputElement>(
        `[data-runtime-form-id="${binding.formId}"][data-runtime-field-id="${binding.fieldId}"]`,
      );
      if (input === null) continue;
      const invalid = form.errors.some((error) => error.fieldId === binding.fieldId);
      input.setAttribute("aria-invalid", String(invalid));
    }
  }
}

function showError(error: unknown): void {
  const element = requiredElement(document, "[data-runtime-error]", HTMLElement);
  element.hidden = false;
  element.textContent = error instanceof Error ? error.message : String(error);
}

async function applyEvents(runtime: PublicRuntime, events: RuntimeEvent[]): Promise<void> {
  runtime.eventNo += 1;
  const transition = await applyRuntimeEventBatch(runtime.document.runtime, runtime.state, {
    clientEventId: `${runtime.state.sessionId}:${runtime.eventNo}`,
    expectedSequenceNo: runtime.state.sequenceNo,
    events,
  });
  runtime.state = transition.state;
  runtime.viewModel = transition.viewModel;
  runtime.manualPageId = null;
  renderRuntime(runtime);
}

function formValueEvent(binding: FormInputBinding, input: HTMLInputElement): RuntimeEvent {
  if (binding.valueType === "integer") {
    const value = Number(input.value);
    if (!Number.isSafeInteger(value)) throw new Error(`${input.value} is not a valid integer`);
    return {
      kind: "fieldValueCommitted",
      nodeId: binding.nodeId,
      formId: binding.formId,
      fieldId: binding.fieldId,
      value: { type: "integer", value },
    };
  }
  return {
    kind: "fieldValueCommitted",
    nodeId: binding.nodeId,
    formId: binding.formId,
    fieldId: binding.fieldId,
    value: { type: "string", value: input.value },
  };
}

function bindInteractions(runtime: PublicRuntime): void {
  let pending = Promise.resolve();
  const queue = (action: () => Promise<void>) => {
    pending = pending.then(action).catch((error: unknown) => showError(error));
  };
  document.querySelectorAll<HTMLButtonElement>("[data-navigation-target]").forEach((button) => {
    button.addEventListener("click", () => {
      runtime.manualPageId = button.dataset["navigationTarget"] ?? null;
      renderRuntime(runtime);
    });
  });
  if (runtime.state.allowSimulatedRoleSwitch) {
    requiredElement(document, "[data-role-select]", HTMLSelectElement).addEventListener(
      "change",
      (event) => {
        if (!(event.currentTarget instanceof HTMLSelectElement)) return;
        const roleId = event.currentTarget.value;
        queue(() => applyEvents(runtime, [{ kind: "switchSimulatedRole", roleId }]));
      },
    );
  }
  document.querySelectorAll<HTMLButtonElement>("[data-runtime-node-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const nodeId = button.dataset["runtimeNodeId"];
      if (nodeId === undefined) return;
      queue(async () => {
        const activationEvents = runtimeNodeActivationEvents(runtime.document, nodeId);
        if (activationEvents.length === 0) return;
        const events: RuntimeEvent[] = [];
        if (activationEvents.some((event) => event.event === "submit")) {
          const form = button.closest<HTMLFormElement>("[data-prototype-form-id]");
          if (form === null) throw new Error(`Submit button ${nodeId} is outside a form`);
          form.querySelectorAll<HTMLInputElement>("[data-runtime-field-id]").forEach((input) => {
            const binding = runtime.inputBindings.get(
              input.closest<HTMLElement>("[data-prototype-node-id]")?.dataset["prototypeNodeId"] ??
                "",
            );
            if (binding !== undefined) events.push(formValueEvent(binding, input));
          });
        }
        events.push(...activationEvents);
        await applyEvents(runtime, events);
      });
    });
  });
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const row = target.closest<HTMLTableRowElement>("tr[data-entity-id][data-schema-id]");
    const table = row?.closest<HTMLElement>("[data-prototype-node-id]");
    const entityId = row?.dataset["entityId"];
    const schemaId = row?.dataset["schemaId"];
    const nodeId = table?.dataset["prototypeNodeId"];
    if (entityId === undefined || schemaId === undefined || nodeId === undefined) return;
    queue(async () => {
      if (!runtimeNodeTriggerEvents(runtime.document, nodeId).includes("rowActivated")) return;
      await applyEvents(runtime, [
        {
          kind: "tableRowActivated",
          nodeId,
          entityRef: { type: "entityRef", schemaId, entityId },
        },
      ]);
    });
  });
}

async function main(): Promise<void> {
  const response = await fetch("./document.json", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok)
    throw new Error(`Published prototype document failed to load (${response.status})`);
  const documentValue = parseRendererDocument(await response.json());
  const scenario = documentValue.runtime.scenarios[0];
  if (scenario === undefined) throw new Error("Published prototype has no runtime scenario");
  const sessionId = `${documentValue.id}:${scenario.id}:published`;
  const state = createInitialRuntimeState(documentValue.runtime, scenario.id, sessionId);
  const runtime: PublicRuntime = {
    document: documentValue,
    state,
    viewModel: deriveRuntimeViewModel(documentValue.runtime, state),
    manualPageId: null,
    inputBindings: new Map(
      deriveFormInputBindings(documentValue).map((binding) => [binding.nodeId, binding]),
    ),
    eventNo: 0,
  };
  renderRuntime(runtime);
  bindInteractions(runtime);
}

void main().catch((error: unknown) => showError(error));
