import { safeJsonParse } from "@/lib/utils";

import { canonicalRuntimeJson } from "./canonical";
import type {
  PrototypeRuntimeState,
  RuntimeEntity,
  RuntimeEntitySet,
  RuntimeFieldValue,
  RuntimeFormError,
  RuntimeFormState,
  RuntimeNodeViewModel,
  RuntimeNotification,
  RuntimeValue,
  RuntimeVariableValue,
  RuntimeViewModel,
  RuntimeViewProperty,
} from "./types";

export class RuntimeStateCodecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeStateCodecError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new RuntimeStateCodecError(`${path} must be an object`);
  }
  return value;
}

function requireExactKeys(
  record: Record<string, unknown>,
  expectedKeys: readonly string[],
  path: string,
): void {
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      throw new RuntimeStateCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new RuntimeStateCodecError(`${path} is missing field ${key}`);
    }
  }
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new RuntimeStateCodecError(`${path} must be a string`);
  }
  return value;
}

function requireBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new RuntimeStateCodecError(`${path} must be a boolean`);
  }
  return value;
}

function requireSafeInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RuntimeStateCodecError(`${path} must be a safe integer`);
  }
  return value;
}

function requireArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new RuntimeStateCodecError(`${path} must be an array`);
  }
  return value;
}

function requireLiteral<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value === "string") {
    for (const candidate of allowed) {
      if (candidate === value) {
        return candidate;
      }
    }
  }
  throw new RuntimeStateCodecError(`${path} has an unsupported value`);
}

export function parseRuntimeValue(value: unknown, path: string): RuntimeValue {
  const record = requireRecord(value, path);
  const type = requireLiteral(
    record["type"],
    ["null", "boolean", "integer", "string", "enum", "entityRef"] as const,
    `${path}.type`,
  );
  switch (type) {
    case "null":
      requireExactKeys(record, ["type"], path);
      return { type: "null" };
    case "boolean":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "boolean", value: requireBoolean(record["value"], `${path}.value`) };
    case "integer":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "integer", value: requireSafeInteger(record["value"], `${path}.value`) };
    case "string":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "string", value: requireString(record["value"], `${path}.value`) };
    case "enum":
      requireExactKeys(record, ["type", "value"], path);
      return { type: "enum", value: requireString(record["value"], `${path}.value`) };
    case "entityRef":
      requireExactKeys(record, ["type", "schemaId", "entityId"], path);
      return {
        type: "entityRef",
        schemaId: requireString(record["schemaId"], `${path}.schemaId`),
        entityId: requireString(record["entityId"], `${path}.entityId`),
      };
  }
}

function parseFieldValue(value: unknown, path: string): RuntimeFieldValue {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["fieldId", "value"], path);
  return {
    fieldId: requireString(record["fieldId"], `${path}.fieldId`),
    value: parseRuntimeValue(record["value"], `${path}.value`),
  };
}

export function parseVariableValue(value: unknown, path: string): RuntimeVariableValue {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["variableId", "value"], path);
  return {
    variableId: requireString(record["variableId"], `${path}.variableId`),
    value: parseRuntimeValue(record["value"], `${path}.value`),
  };
}

function parseEntity(value: unknown, path: string): RuntimeEntity {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "schemaId", "fields"], path);
  return {
    id: requireString(record["id"], `${path}.id`),
    schemaId: requireString(record["schemaId"], `${path}.schemaId`),
    fields: requireArray(record["fields"], `${path}.fields`).map((field, index) =>
      parseFieldValue(field, `${path}.fields[${index}]`),
    ),
  };
}

export function parseEntitySet(value: unknown, path: string): RuntimeEntitySet {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["schemaId", "entities"], path);
  return {
    schemaId: requireString(record["schemaId"], `${path}.schemaId`),
    entities: requireArray(record["entities"], `${path}.entities`).map((entity, index) =>
      parseEntity(entity, `${path}.entities[${index}]`),
    ),
  };
}

function parseFormError(value: unknown, path: string): RuntimeFormError {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["fieldId", "code"], path);
  return {
    fieldId: requireString(record["fieldId"], `${path}.fieldId`),
    code: requireLiteral(
      record["code"],
      ["required", "min_integer", "type_mismatch"] as const,
      `${path}.code`,
    ),
  };
}

function parseFormState(value: unknown, path: string): RuntimeFormState {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["formId", "values", "errors"], path);
  return {
    formId: requireString(record["formId"], `${path}.formId`),
    values: requireArray(record["values"], `${path}.values`).map((field, index) =>
      parseFieldValue(field, `${path}.values[${index}]`),
    ),
    errors: requireArray(record["errors"], `${path}.errors`).map((error, index) =>
      parseFormError(error, `${path}.errors[${index}]`),
    ),
  };
}

function parseNotification(value: unknown, path: string): RuntimeNotification {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "level", "message"], path);
  return {
    id: requireString(record["id"], `${path}.id`),
    level: requireLiteral(
      record["level"],
      ["info", "success", "warning", "error"] as const,
      `${path}.level`,
    ),
    message: requireString(record["message"], `${path}.message`),
  };
}

export function parsePrototypeRuntimeState(value: unknown): PrototypeRuntimeState {
  const record = requireRecord(value, "runtimeState");
  requireExactKeys(
    record,
    [
      "runtimeStateSchemaVersion",
      "sessionId",
      "scenarioId",
      "runtimeCoreVersion",
      "stateMachineKernelVersion",
      "sequenceNo",
      "actorRoleId",
      "currentPageId",
      "navigationStack",
      "variableValues",
      "entitySets",
      "formStates",
      "notifications",
      "allowSimulatedRoleSwitch",
    ],
    "runtimeState",
  );
  if (record["runtimeStateSchemaVersion"] !== 1) {
    throw new RuntimeStateCodecError("runtimeState.runtimeStateSchemaVersion must equal 1");
  }
  return {
    runtimeStateSchemaVersion: 1,
    sessionId: requireString(record["sessionId"], "runtimeState.sessionId"),
    scenarioId: requireString(record["scenarioId"], "runtimeState.scenarioId"),
    runtimeCoreVersion: requireString(
      record["runtimeCoreVersion"],
      "runtimeState.runtimeCoreVersion",
    ),
    stateMachineKernelVersion: requireString(
      record["stateMachineKernelVersion"],
      "runtimeState.stateMachineKernelVersion",
    ),
    sequenceNo: requireSafeInteger(record["sequenceNo"], "runtimeState.sequenceNo"),
    actorRoleId: requireString(record["actorRoleId"], "runtimeState.actorRoleId"),
    currentPageId: requireString(record["currentPageId"], "runtimeState.currentPageId"),
    navigationStack: requireArray(record["navigationStack"], "runtimeState.navigationStack").map(
      (pageId, index) => requireString(pageId, `runtimeState.navigationStack[${index}]`),
    ),
    variableValues: requireArray(record["variableValues"], "runtimeState.variableValues").map(
      (entry, index) => parseVariableValue(entry, `runtimeState.variableValues[${index}]`),
    ),
    entitySets: requireArray(record["entitySets"], "runtimeState.entitySets").map((set, index) =>
      parseEntitySet(set, `runtimeState.entitySets[${index}]`),
    ),
    formStates: requireArray(record["formStates"], "runtimeState.formStates").map((form, index) =>
      parseFormState(form, `runtimeState.formStates[${index}]`),
    ),
    notifications: requireArray(record["notifications"], "runtimeState.notifications").map(
      (notification, index) =>
        parseNotification(notification, `runtimeState.notifications[${index}]`),
    ),
    allowSimulatedRoleSwitch: requireBoolean(
      record["allowSimulatedRoleSwitch"],
      "runtimeState.allowSimulatedRoleSwitch",
    ),
  };
}

export function serializePrototypeRuntimeState(state: PrototypeRuntimeState): string {
  return canonicalRuntimeJson(state);
}

export function parsePrototypeRuntimeStateJson(input: string): PrototypeRuntimeState {
  const decoded = safeJsonParse(input);
  if (decoded === null) {
    throw new RuntimeStateCodecError("runtimeState JSON is invalid");
  }
  return parsePrototypeRuntimeState(decoded);
}

function parseRuntimeViewProperty(value: unknown, path: string): RuntimeViewProperty {
  const record = requireRecord(value, path);
  const target = requireLiteral(
    record["target"],
    ["textContent", "visibility", "tableRows"] as const,
    `${path}.target`,
  );
  if (target === "textContent") {
    requireExactKeys(record, ["target", "value"], path);
    return { target, value: parseRuntimeValue(record["value"], `${path}.value`) };
  }
  if (target === "visibility") {
    requireExactKeys(record, ["target", "value"], path);
    const parsed = parseRuntimeValue(record["value"], `${path}.value`);
    if (parsed.type !== "boolean") {
      throw new RuntimeStateCodecError(`${path}.value must be a boolean runtime value`);
    }
    return { target, value: parsed };
  }
  requireExactKeys(record, ["target", "rows"], path);
  return {
    target,
    rows: requireArray(record["rows"], `${path}.rows`).map((row, index) =>
      parseEntity(row, `${path}.rows[${index}]`),
    ),
  };
}

function parseRuntimeNodeViewModel(value: unknown, path: string): RuntimeNodeViewModel {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["nodeId", "properties"], path);
  return {
    nodeId: requireString(record["nodeId"], `${path}.nodeId`),
    properties: requireArray(record["properties"], `${path}.properties`).map((property, index) =>
      parseRuntimeViewProperty(property, `${path}.properties[${index}]`),
    ),
  };
}

export function parseRuntimeViewModel(value: unknown): RuntimeViewModel {
  const record = requireRecord(value, "runtimeViewModel");
  requireExactKeys(record, ["nodes"], "runtimeViewModel");
  return {
    nodes: requireArray(record["nodes"], "runtimeViewModel.nodes").map((node, index) =>
      parseRuntimeNodeViewModel(node, `runtimeViewModel.nodes[${index}]`),
    ),
  };
}

export function parseRuntimeViewModelJson(input: string): RuntimeViewModel {
  const decoded = safeJsonParse(input);
  if (decoded === null) {
    throw new RuntimeStateCodecError("runtimeViewModel JSON is invalid");
  }
  return parseRuntimeViewModel(decoded);
}
