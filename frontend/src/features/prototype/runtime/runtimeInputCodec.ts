import { parseEntitySet, parseRuntimeValue, parseVariableValue } from "./runtimeStateCodec";
import type {
  EntityFieldValueExpression,
  EntityRefRuntimeValue,
  EventEntityRefExpression,
  IntegerRuntimeValue,
  RuntimeBehaviorRule,
  RuntimeDefinition,
  RuntimeEffect,
  RuntimeEntityFieldDefinition,
  RuntimeEntityRefExpression,
  RuntimeEntitySchema,
  RuntimeEvent,
  RuntimeEventBatch,
  RuntimeFormDefinition,
  RuntimeFormFieldDefinition,
  RuntimePredicate,
  RuntimeRoleDefinition,
  RuntimeScenario,
  RuntimeValueExpression,
  RuntimeVariableDefinition,
  RuntimeViewBinding,
  StringRuntimeValue,
  VariableValueExpression,
} from "./types";

const MAX_EXPRESSION_DEPTH = 32;

interface RuntimeFieldAssignment {
  fieldId: string;
  value: RuntimeValueExpression;
}

export class RuntimeInputCodecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RuntimeInputCodecError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new RuntimeInputCodecError(`${path} must be an object`);
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
      throw new RuntimeInputCodecError(`${path} contains unknown field ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(record, key)) {
      throw new RuntimeInputCodecError(`${path} is missing field ${key}`);
    }
  }
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new RuntimeInputCodecError(`${path} must be a string`);
  }
  return value;
}

function requireNonEmptyString(value: unknown, path: string): string {
  const parsed = requireString(value, path);
  if (parsed.length === 0) {
    throw new RuntimeInputCodecError(`${path} must not be empty`);
  }
  return parsed;
}

function requireBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new RuntimeInputCodecError(`${path} must be a boolean`);
  }
  return value;
}

function requireSafeInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || Object.is(value, -0)) {
    throw new RuntimeInputCodecError(`${path} must be a safe integer`);
  }
  return value;
}

function requireArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new RuntimeInputCodecError(`${path} must be an array`);
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
  throw new RuntimeInputCodecError(`${path} has an unsupported value`);
}

function requireNullableSafeInteger(value: unknown, path: string): number | null {
  return value === null ? null : requireSafeInteger(value, path);
}

function requireDepth(depth: number, path: string): void {
  if (depth > MAX_EXPRESSION_DEPTH) {
    throw new RuntimeInputCodecError(`${path} exceeds the maximum expression depth`);
  }
}

function parseRole(value: unknown, path: string): RuntimeRoleDefinition {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "key", "label"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    label: requireString(record["label"], `${path}.label`),
  };
}

function parseVariable(value: unknown, path: string): RuntimeVariableDefinition {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "key", "valueType", "nullable", "defaultValue"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType: requireLiteral(
      record["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"] as const,
      `${path}.valueType`,
    ),
    nullable: requireBoolean(record["nullable"], `${path}.nullable`),
    defaultValue: parseRuntimeValue(record["defaultValue"], `${path}.defaultValue`),
  };
}

function parseEntityField(value: unknown, path: string): RuntimeEntityFieldDefinition {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "key", "valueType", "nullable"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType: requireLiteral(
      record["valueType"],
      ["null", "boolean", "integer", "string", "enum", "entityRef"] as const,
      `${path}.valueType`,
    ),
    nullable: requireBoolean(record["nullable"], `${path}.nullable`),
  };
}

function parseEntitySchema(value: unknown, path: string): RuntimeEntitySchema {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    fields: requireArray(record["fields"], `${path}.fields`).map((field, index) =>
      parseEntityField(field, `${path}.fields[${index}]`),
    ),
  };
}

function parseFormField(value: unknown, path: string): RuntimeFormFieldDefinition {
  const record = requireRecord(value, path);
  requireExactKeys(
    record,
    ["id", "key", "valueType", "initialValue", "required", "minInteger"],
    path,
  );
  const valueType = requireLiteral(
    record["valueType"],
    ["string", "integer"] as const,
    `${path}.valueType`,
  );
  const initialValue = parseRuntimeValue(record["initialValue"], `${path}.initialValue`);
  let typedInitialValue: StringRuntimeValue | IntegerRuntimeValue;
  if (valueType === "string") {
    if (initialValue.type !== "string") {
      throw new RuntimeInputCodecError(`${path}.initialValue must be a string runtime value`);
    }
    typedInitialValue = initialValue;
  } else {
    if (initialValue.type !== "integer") {
      throw new RuntimeInputCodecError(`${path}.initialValue must be an integer runtime value`);
    }
    typedInitialValue = initialValue;
  }
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    valueType,
    initialValue: typedInitialValue,
    required: requireBoolean(record["required"], `${path}.required`),
    minInteger: requireNullableSafeInteger(record["minInteger"], `${path}.minInteger`),
  };
}

function parseForm(value: unknown, path: string): RuntimeFormDefinition {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["id", "key", "fields"], path);
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    fields: requireArray(record["fields"], `${path}.fields`).map((field, index) =>
      parseFormField(field, `${path}.fields[${index}]`),
    ),
  };
}

function parseEntityRefExpression(value: unknown, path: string): RuntimeEntityRefExpression {
  const record = requireRecord(value, path);
  const kind = requireLiteral(
    record["kind"],
    ["variable", "eventEntityRef"] as const,
    `${path}.kind`,
  );
  if (kind === "variable") {
    requireExactKeys(record, ["kind", "variableId"], path);
    const expression: VariableValueExpression = {
      kind,
      variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`),
    };
    return expression;
  }
  requireExactKeys(record, ["kind"], path);
  const expression: EventEntityRefExpression = { kind };
  return expression;
}

function parseValueExpression(value: unknown, path: string, depth = 0): RuntimeValueExpression {
  requireDepth(depth, path);
  const record = requireRecord(value, path);
  const kind = requireLiteral(
    record["kind"],
    ["literal", "variable", "formField", "eventEntityRef", "entityField"] as const,
    `${path}.kind`,
  );
  switch (kind) {
    case "literal":
      requireExactKeys(record, ["kind", "value"], path);
      return { kind, value: parseRuntimeValue(record["value"], `${path}.value`) };
    case "variable":
      requireExactKeys(record, ["kind", "variableId"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`),
      };
    case "formField":
      requireExactKeys(record, ["kind", "formId", "fieldId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
      };
    case "eventEntityRef":
      requireExactKeys(record, ["kind"], path);
      return { kind };
    case "entityField": {
      requireExactKeys(record, ["kind", "entityRef", "fieldId", "fallback"], path);
      const expression: EntityFieldValueExpression = {
        kind,
        entityRef: parseEntityRefExpression(record["entityRef"], `${path}.entityRef`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
        fallback: parseRuntimeValue(record["fallback"], `${path}.fallback`),
      };
      return expression;
    }
  }
}

function parsePredicate(value: unknown, path: string, depth = 0): RuntimePredicate {
  requireDepth(depth, path);
  const record = requireRecord(value, path);
  const kind = requireLiteral(
    record["kind"],
    ["all", "roleIs", "formValid", "compare"] as const,
    `${path}.kind`,
  );
  switch (kind) {
    case "all":
      requireExactKeys(record, ["kind", "items"], path);
      return {
        kind,
        items: requireArray(record["items"], `${path}.items`).map((item, index) =>
          parsePredicate(item, `${path}.items[${index}]`, depth + 1),
        ),
      };
    case "roleIs":
      requireExactKeys(record, ["kind", "roleId"], path);
      return {
        kind,
        roleId: requireNonEmptyString(record["roleId"], `${path}.roleId`),
      };
    case "formValid":
      requireExactKeys(record, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
      };
    case "compare":
      requireExactKeys(record, ["kind", "operator", "left", "right"], path);
      return {
        kind,
        operator: requireLiteral(record["operator"], ["eq", "ne"] as const, `${path}.operator`),
        left: parseValueExpression(record["left"], `${path}.left`, depth + 1),
        right: parseValueExpression(record["right"], `${path}.right`, depth + 1),
      };
  }
}

function parseFieldAssignment(value: unknown, path: string): RuntimeFieldAssignment {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["fieldId", "value"], path);
  return {
    fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
    value: parseValueExpression(record["value"], `${path}.value`),
  };
}

function parseEffect(value: unknown, path: string): RuntimeEffect {
  const record = requireRecord(value, path);
  const kind = requireLiteral(
    record["kind"],
    ["setVariable", "validateForm", "createEntity", "updateEntity", "navigate", "notify"] as const,
    `${path}.kind`,
  );
  switch (kind) {
    case "setVariable":
      requireExactKeys(record, ["kind", "variableId", "value"], path);
      return {
        kind,
        variableId: requireNonEmptyString(record["variableId"], `${path}.variableId`),
        value: parseValueExpression(record["value"], `${path}.value`),
      };
    case "validateForm":
      requireExactKeys(record, ["kind", "formId"], path);
      return {
        kind,
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
      };
    case "createEntity":
      requireExactKeys(record, ["kind", "schemaId", "resultVariableId", "values"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
        resultVariableId: requireNonEmptyString(
          record["resultVariableId"],
          `${path}.resultVariableId`,
        ),
        values: requireArray(record["values"], `${path}.values`).map((entry, index) =>
          parseFieldAssignment(entry, `${path}.values[${index}]`),
        ),
      };
    case "updateEntity":
      requireExactKeys(record, ["kind", "schemaId", "entityRef", "updates"], path);
      return {
        kind,
        schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
        entityRef: parseEntityRefExpression(record["entityRef"], `${path}.entityRef`),
        updates: requireArray(record["updates"], `${path}.updates`).map((entry, index) =>
          parseFieldAssignment(entry, `${path}.updates[${index}]`),
        ),
      };
    case "navigate":
      requireExactKeys(record, ["kind", "targetPageId"], path);
      return {
        kind,
        targetPageId: requireNonEmptyString(record["targetPageId"], `${path}.targetPageId`),
      };
    case "notify":
      requireExactKeys(record, ["kind", "level", "message"], path);
      return {
        kind,
        level: requireLiteral(
          record["level"],
          ["info", "success", "warning", "error"] as const,
          `${path}.level`,
        ),
        message: requireString(record["message"], `${path}.message`),
      };
  }
}

function parseRule(value: unknown, path: string): RuntimeBehaviorRule {
  const record = requireRecord(value, path);
  requireExactKeys(
    record,
    ["id", "key", "enabled", "trigger", "guard", "effects", "guardFalseEffects"],
    path,
  );
  const trigger = requireRecord(record["trigger"], `${path}.trigger`);
  requireExactKeys(trigger, ["kind", "nodeId", "event"], `${path}.trigger`);
  if (trigger["kind"] !== "nodeEvent") {
    throw new RuntimeInputCodecError(`${path}.trigger.kind must equal nodeEvent`);
  }
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    enabled: requireBoolean(record["enabled"], `${path}.enabled`),
    trigger: {
      kind: "nodeEvent",
      nodeId: requireNonEmptyString(trigger["nodeId"], `${path}.trigger.nodeId`),
      event: requireLiteral(
        trigger["event"],
        ["click", "submit", "rowActivated"] as const,
        `${path}.trigger.event`,
      ),
    },
    guard: record["guard"] === null ? null : parsePredicate(record["guard"], `${path}.guard`),
    effects: requireArray(record["effects"], `${path}.effects`).map((effect, index) =>
      parseEffect(effect, `${path}.effects[${index}]`),
    ),
    guardFalseEffects: requireArray(record["guardFalseEffects"], `${path}.guardFalseEffects`).map(
      (effect, index) => parseEffect(effect, `${path}.guardFalseEffects[${index}]`),
    ),
  };
}

function parseViewBinding(value: unknown, path: string): RuntimeViewBinding {
  const record = requireRecord(value, path);
  const target = requireLiteral(
    record["target"],
    ["textContent", "visibility", "tableRows"] as const,
    `${path}.target`,
  );
  if (target === "textContent") {
    requireExactKeys(record, ["id", "nodeId", "target", "value"], path);
    return {
      id: requireNonEmptyString(record["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
      target,
      value: parseValueExpression(record["value"], `${path}.value`),
    };
  }
  if (target === "visibility") {
    requireExactKeys(record, ["id", "nodeId", "target", "predicate"], path);
    return {
      id: requireNonEmptyString(record["id"], `${path}.id`),
      nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
      target,
      predicate: parsePredicate(record["predicate"], `${path}.predicate`),
    };
  }
  requireExactKeys(
    record,
    ["id", "nodeId", "target", "schemaId", "sortFieldId", "sortDirection"],
    path,
  );
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
    target,
    schemaId: requireNonEmptyString(record["schemaId"], `${path}.schemaId`),
    sortFieldId:
      record["sortFieldId"] === null
        ? null
        : requireNonEmptyString(record["sortFieldId"], `${path}.sortFieldId`),
    sortDirection: requireLiteral(
      record["sortDirection"],
      ["asc", "desc"] as const,
      `${path}.sortDirection`,
    ),
  };
}

function parseScenario(value: unknown, path: string): RuntimeScenario {
  const record = requireRecord(value, path);
  requireExactKeys(
    record,
    [
      "id",
      "key",
      "actorRoleId",
      "startPageId",
      "initialVariables",
      "entityFixtures",
      "allowSimulatedRoleSwitch",
    ],
    path,
  );
  return {
    id: requireNonEmptyString(record["id"], `${path}.id`),
    key: requireNonEmptyString(record["key"], `${path}.key`),
    actorRoleId: requireNonEmptyString(record["actorRoleId"], `${path}.actorRoleId`),
    startPageId: requireNonEmptyString(record["startPageId"], `${path}.startPageId`),
    initialVariables: requireArray(record["initialVariables"], `${path}.initialVariables`).map(
      (entry, index) => parseVariableValue(entry, `${path}.initialVariables[${index}]`),
    ),
    entityFixtures: requireArray(record["entityFixtures"], `${path}.entityFixtures`).map(
      (entry, index) => parseEntitySet(entry, `${path}.entityFixtures[${index}]`),
    ),
    allowSimulatedRoleSwitch: requireBoolean(
      record["allowSimulatedRoleSwitch"],
      `${path}.allowSimulatedRoleSwitch`,
    ),
  };
}

export function parseRuntimeDefinition(value: unknown): RuntimeDefinition {
  const record = requireRecord(value, "runtimeDefinition");
  requireExactKeys(
    record,
    [
      "runtimeSchemaVersion",
      "pageIds",
      "roles",
      "variables",
      "entitySchemas",
      "forms",
      "viewBindings",
      "rules",
      "scenarios",
    ],
    "runtimeDefinition",
  );
  if (record["runtimeSchemaVersion"] !== 1) {
    throw new RuntimeInputCodecError("runtimeDefinition.runtimeSchemaVersion must equal 1");
  }
  return {
    runtimeSchemaVersion: 1,
    pageIds: requireArray(record["pageIds"], "runtimeDefinition.pageIds").map((pageId, index) =>
      requireNonEmptyString(pageId, `runtimeDefinition.pageIds[${index}]`),
    ),
    roles: requireArray(record["roles"], "runtimeDefinition.roles").map((role, index) =>
      parseRole(role, `runtimeDefinition.roles[${index}]`),
    ),
    variables: requireArray(record["variables"], "runtimeDefinition.variables").map(
      (variable, index) => parseVariable(variable, `runtimeDefinition.variables[${index}]`),
    ),
    entitySchemas: requireArray(record["entitySchemas"], "runtimeDefinition.entitySchemas").map(
      (schema, index) => parseEntitySchema(schema, `runtimeDefinition.entitySchemas[${index}]`),
    ),
    forms: requireArray(record["forms"], "runtimeDefinition.forms").map((form, index) =>
      parseForm(form, `runtimeDefinition.forms[${index}]`),
    ),
    viewBindings: requireArray(record["viewBindings"], "runtimeDefinition.viewBindings").map(
      (binding, index) => parseViewBinding(binding, `runtimeDefinition.viewBindings[${index}]`),
    ),
    rules: requireArray(record["rules"], "runtimeDefinition.rules").map((rule, index) =>
      parseRule(rule, `runtimeDefinition.rules[${index}]`),
    ),
    scenarios: requireArray(record["scenarios"], "runtimeDefinition.scenarios").map(
      (scenario, index) => parseScenario(scenario, `runtimeDefinition.scenarios[${index}]`),
    ),
  };
}

function parseEntityRef(value: unknown, path: string): EntityRefRuntimeValue {
  const parsed = parseRuntimeValue(value, path);
  if (parsed.type !== "entityRef") {
    throw new RuntimeInputCodecError(`${path} must be an entityRef runtime value`);
  }
  return parsed;
}

function parseRuntimeEvent(value: unknown, path: string): RuntimeEvent {
  const record = requireRecord(value, path);
  const kind = requireLiteral(
    record["kind"],
    ["fieldValueCommitted", "nodeActivated", "tableRowActivated", "switchSimulatedRole"] as const,
    `${path}.kind`,
  );
  switch (kind) {
    case "fieldValueCommitted":
      requireExactKeys(record, ["kind", "nodeId", "formId", "fieldId", "value"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        formId: requireNonEmptyString(record["formId"], `${path}.formId`),
        fieldId: requireNonEmptyString(record["fieldId"], `${path}.fieldId`),
        value: parseRuntimeValue(record["value"], `${path}.value`),
      };
    case "nodeActivated":
      requireExactKeys(record, ["kind", "nodeId", "event"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        event: requireLiteral(record["event"], ["click", "submit"] as const, `${path}.event`),
      };
    case "tableRowActivated":
      requireExactKeys(record, ["kind", "nodeId", "entityRef"], path);
      return {
        kind,
        nodeId: requireNonEmptyString(record["nodeId"], `${path}.nodeId`),
        entityRef: parseEntityRef(record["entityRef"], `${path}.entityRef`),
      };
    case "switchSimulatedRole":
      requireExactKeys(record, ["kind", "roleId"], path);
      return {
        kind,
        roleId: requireNonEmptyString(record["roleId"], `${path}.roleId`),
      };
  }
}

export function parseRuntimeEventBatch(
  value: unknown,
  path = "runtimeEventBatch",
): RuntimeEventBatch {
  const record = requireRecord(value, path);
  requireExactKeys(record, ["clientEventId", "expectedSequenceNo", "events"], path);
  return {
    clientEventId: requireNonEmptyString(record["clientEventId"], `${path}.clientEventId`),
    expectedSequenceNo: requireSafeInteger(
      record["expectedSequenceNo"],
      `${path}.expectedSequenceNo`,
    ),
    events: requireArray(record["events"], `${path}.events`).map((event, index) =>
      parseRuntimeEvent(event, `${path}.events[${index}]`),
    ),
  };
}
