import type {
  RuntimeBehaviorRule,
  RuntimeEffect,
  RuntimeEntityRefExpression,
  RuntimeEntitySchema,
  RuntimePredicate,
  RuntimeValue,
  RuntimeValueExpression,
  RuntimeValueType,
} from "../runtime/types";
import type {
  StructuredPrototypeBehaviorRuleDefinition,
  StructuredPrototypeDocument,
  StructuredPrototypeNode,
  StructuredPrototypePage,
} from "./types";

export const STRUCTURED_PROTOTYPE_RULE_KEY_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;
export const STRUCTURED_PROTOTYPE_ENTITY_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const STRUCTURED_PROTOTYPE_PRIMARY_EFFECT_LIMIT = 100;
export const STRUCTURED_PROTOTYPE_GUARD_FALSE_EFFECT_LIMIT = 100;

export interface StructuredPrototypePendingRuleConnection {
  kind: "pendingConnection";
  sourcePageId: string;
  targetPageId: string;
}

export type StructuredPrototypeRuleInspectorSelection =
  { kind: "existingRule"; rule: RuntimeBehaviorRule } | StructuredPrototypePendingRuleConnection;

export interface StructuredPrototypeRuleTriggerCandidate {
  pageId: string;
  nodeId: string;
  nodeName: string;
  event: RuntimeBehaviorRule["trigger"]["event"];
}

export interface StructuredPrototypeRuleDraft {
  key: string;
  enabled: boolean;
  trigger: RuntimeBehaviorRule["trigger"] | null;
  guard: RuntimePredicate | null;
  effects: RuntimeEffect[];
  guardFalseEffects: RuntimeEffect[];
}

export type StructuredPrototypeRuleValidationCode =
  | "invalid_key"
  | "duplicate_key"
  | "trigger_required"
  | "unknown_trigger_node"
  | "ineligible_trigger_event"
  | "duplicate_trigger"
  | "primary_effect_required"
  | "effect_limit_exceeded"
  | "guard_item_required"
  | "guard_item_limit_exceeded"
  | "unknown_role"
  | "unknown_form"
  | "unknown_form_field"
  | "unknown_variable"
  | "unknown_schema"
  | "unknown_schema_field"
  | "unknown_page"
  | "event_context_unavailable"
  | "entity_schema_mismatch"
  | "expression_type_mismatch"
  | "invalid_enum_value"
  | "runtime_string_too_long"
  | "invalid_entity_id"
  | "entity_fixture_missing"
  | "duplicate_field_assignment"
  | "update_assignment_required"
  | "invalid_notification";

export interface StructuredPrototypeRuleValidationIssue {
  code: StructuredPrototypeRuleValidationCode;
  path: string;
}

export type StructuredPrototypeRuleExpressionKind = RuntimeValueExpression["kind"];
export type StructuredPrototypeRulePredicateKind = RuntimePredicate["kind"];
export type StructuredPrototypeRuleEffectKind = RuntimeEffect["kind"];

type NodeVisit = {
  pageId: string;
  node: StructuredPrototypeNode;
  insideForm: boolean;
};

type ValidationContext = {
  document: StructuredPrototypeDocument;
  trigger: RuntimeBehaviorRule["trigger"];
  issues: StructuredPrototypeRuleValidationIssue[];
};

type RuntimeExpressionIdentity = {
  valueType: RuntimeValueType;
  entitySchemaId: string | null;
};

export function isStructuredPrototypeTechnicalKey(value: string): boolean {
  return (
    STRUCTURED_PROTOTYPE_RULE_KEY_PATTERN.test(value) &&
    !value.includes("\n") &&
    !value.includes("\r")
  );
}

export function structuredPrototypeRuleInspectorStateKey(
  selection: StructuredPrototypeRuleInspectorSelection,
): string {
  if (selection.kind === "existingRule") {
    return `${selection.rule.id}:${JSON.stringify(selection.rule)}`;
  }
  return `${selection.sourcePageId}:${selection.targetPageId}`;
}

function visitPageNodes(page: StructuredPrototypePage): NodeVisit[] {
  const visits: NodeVisit[] = [];
  const visit = (node: StructuredPrototypeNode, insideForm: boolean): void => {
    visits.push({ pageId: page.id, node, insideForm });
    if (!("children" in node)) return;
    const childInsideForm = insideForm || node.type === "Form";
    node.children.forEach((child) => visit(child, childInsideForm));
  };
  visit(page.root, false);
  return visits;
}

function allNodeVisits(document: StructuredPrototypeDocument): NodeVisit[] {
  return document.pages.flatMap(visitPageNodes);
}

function triggerEventsForVisit(
  document: StructuredPrototypeDocument,
  visit: NodeVisit,
): RuntimeBehaviorRule["trigger"]["event"][] {
  if (visit.node.type === "Table") {
    return document.runtime.viewBindings.some(
      (binding) => binding.target === "tableRows" && binding.nodeId === visit.node.id,
    )
      ? ["rowActivated"]
      : [];
  }
  if (visit.node.type !== "Button") return [];
  return visit.insideForm ? ["submit", "click"] : ["click"];
}

export function structuredPrototypeRuleTriggerCandidates(
  document: StructuredPrototypeDocument,
  pageId: string | null = null,
): StructuredPrototypeRuleTriggerCandidate[] {
  return allNodeVisits(document).flatMap((visit) => {
    if (pageId !== null && visit.pageId !== pageId) return [];
    return triggerEventsForVisit(document, visit).map((event) => ({
      pageId: visit.pageId,
      nodeId: visit.node.id,
      nodeName: visit.node.name,
      event,
    }));
  });
}

export function isStructuredPrototypeRuleTriggerEligible(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
): boolean {
  return structuredPrototypeRuleTriggerCandidates(document).some(
    (candidate) => candidate.nodeId === trigger.nodeId && candidate.event === trigger.event,
  );
}

function uniqueRuleKey(document: StructuredPrototypeDocument, requested: string): string {
  const existing = new Set(document.runtime.rules.map((rule) => rule.key));
  if (!existing.has(requested)) return requested;
  for (let suffix = 2; suffix <= document.runtime.rules.length + 2; suffix += 1) {
    const suffixText = `-${suffix}`;
    const candidate = `${requested.slice(0, 64 - suffixText.length).replace(/-+$/, "")}${suffixText}`;
    if (!existing.has(candidate)) return candidate;
  }
  throw new Error("unable to allocate a unique behavior rule key");
}

function pendingRuleKey(
  document: StructuredPrototypeDocument,
  source: StructuredPrototypePage,
  target: StructuredPrototypePage,
): string {
  const requested = `flow-${source.key}-to-${target.key}`
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/, "");
  const normalized = /^[a-z]/.test(requested) ? requested : `flow-${requested}`.slice(0, 64);
  return uniqueRuleKey(document, normalized);
}

export function structuredPrototypeBehaviorRuleDefinition(
  rule: RuntimeBehaviorRule,
): StructuredPrototypeBehaviorRuleDefinition {
  const { id: _id, ...definition } = structuredClone(rule);
  return definition;
}

export function createStructuredPrototypeRuleDraft(
  document: StructuredPrototypeDocument,
  selection: StructuredPrototypeRuleInspectorSelection,
): StructuredPrototypeRuleDraft | null {
  if (selection.kind === "existingRule") {
    return structuredPrototypeBehaviorRuleDefinition(selection.rule);
  }
  const source = document.pages.find((page) => page.id === selection.sourcePageId);
  const target = document.pages.find((page) => page.id === selection.targetPageId);
  if (source === undefined || target === undefined) return null;
  return {
    key: pendingRuleKey(document, source, target),
    enabled: true,
    trigger: null,
    guard: null,
    effects: [{ kind: "navigate", targetPageId: target.id }],
    guardFalseEffects: [],
  };
}

export function buildStructuredPrototypeRuleDefinition(
  draft: StructuredPrototypeRuleDraft,
): StructuredPrototypeBehaviorRuleDefinition | null {
  if (draft.trigger === null) return null;
  return structuredClone({
    key: draft.key,
    enabled: draft.enabled,
    trigger: draft.trigger,
    guard: draft.guard,
    effects: draft.effects,
    guardFalseEffects: draft.guardFalseEffects,
  });
}

export function insertStructuredPrototypeRuleEffect(
  effects: readonly RuntimeEffect[],
  index: number,
  effect: RuntimeEffect,
): RuntimeEffect[] {
  const boundedIndex = Math.max(0, Math.min(index, effects.length));
  const next = effects.slice();
  next.splice(boundedIndex, 0, effect);
  return next;
}

export function removeStructuredPrototypeRuleEffect(
  effects: readonly RuntimeEffect[],
  index: number,
): RuntimeEffect[] {
  if (index < 0 || index >= effects.length) return effects.slice();
  return effects.filter((_effect, effectIndex) => effectIndex !== index);
}

export function moveStructuredPrototypeRuleEffect(
  effects: readonly RuntimeEffect[],
  sourceIndex: number,
  targetIndex: number,
): RuntimeEffect[] {
  if (
    sourceIndex < 0 ||
    sourceIndex >= effects.length ||
    targetIndex < 0 ||
    targetIndex >= effects.length ||
    sourceIndex === targetIndex
  ) {
    return effects.slice();
  }
  const next = effects.slice();
  const [effect] = next.splice(sourceIndex, 1);
  if (effect === undefined) return effects.slice();
  next.splice(targetIndex, 0, effect);
  return next;
}

function addIssue(
  context: ValidationContext,
  code: StructuredPrototypeRuleValidationCode,
  path: string,
): void {
  context.issues.push({ code, path });
}

function eventEntitySchemaId(context: ValidationContext): string | null {
  if (context.trigger.event !== "rowActivated") return null;
  const binding = context.document.runtime.viewBindings.find(
    (candidate) => candidate.target === "tableRows" && candidate.nodeId === context.trigger.nodeId,
  );
  return binding?.target === "tableRows" ? binding.schemaId : null;
}

export function structuredPrototypeRuleEventSchemaId(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
): string | null {
  if (trigger.event !== "rowActivated") return null;
  const binding = document.runtime.viewBindings.find(
    (candidate) => candidate.target === "tableRows" && candidate.nodeId === trigger.nodeId,
  );
  return binding?.target === "tableRows" ? binding.schemaId : null;
}

export function createStructuredPrototypeRuleRuntimeValue(
  document: StructuredPrototypeDocument,
  type: RuntimeValueType,
  preferredEntitySchemaId: string | null = null,
): RuntimeValue | null {
  if (type === "null") return { type };
  if (type === "boolean") return { type, value: false };
  if (type === "integer") return { type, value: 0 };
  if (type === "string") return { type, value: "" };
  if (type === "enum") return { type, value: "value" };
  const schemas =
    preferredEntitySchemaId === null
      ? document.runtime.entitySchemas
      : document.runtime.entitySchemas.filter((schema) => schema.id === preferredEntitySchemaId);
  for (const schema of schemas) {
    const entityId = structuredPrototypeRuleFixtureEntityIds(document, schema.id)[0];
    if (entityId !== undefined) return { type, schemaId: schema.id, entityId };
  }
  return null;
}

export function structuredPrototypeRuleFixtureEntityIds(
  document: StructuredPrototypeDocument,
  schemaId: string,
): string[] {
  if (!STRUCTURED_PROTOTYPE_ENTITY_ID_PATTERN.test(schemaId)) return [];
  return Array.from(
    new Set(
      document.runtime.scenarios
        .flatMap((scenario) => scenario.entityFixtures)
        .filter((fixture) => fixture.schemaId === schemaId)
        .flatMap((fixture) =>
          fixture.entities
            .filter(
              (entity) =>
                entity.schemaId === schemaId &&
                STRUCTURED_PROTOTYPE_ENTITY_ID_PATTERN.test(entity.id),
            )
            .map((entity) => entity.id),
        ),
    ),
  );
}

export function structuredPrototypeCreateEntitySchemaOptions(
  document: StructuredPrototypeDocument,
): RuntimeEntitySchema[] {
  return document.runtime.entitySchemas.filter((schema) =>
    document.runtime.variables.some(
      (variable) => variable.valueType === "entityRef" && variable.entitySchemaId === schema.id,
    ),
  );
}

function expressionReferenceSchemas(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
): Array<{ ref: RuntimeEntityRefExpression; schemaId: string }> {
  const references: Array<{ ref: RuntimeEntityRefExpression; schemaId: string }> =
    document.runtime.variables.flatMap((variable) =>
      variable.valueType === "entityRef" && variable.entitySchemaId !== null
        ? [
            {
              ref: { kind: "variable", variableId: variable.id } as const,
              schemaId: variable.entitySchemaId,
            },
          ]
        : [],
    );
  const eventSchemaId = structuredPrototypeRuleEventSchemaId(document, trigger);
  if (eventSchemaId !== null) {
    references.unshift({ ref: { kind: "eventEntityRef" }, schemaId: eventSchemaId });
  }
  return references;
}

export function structuredPrototypeRuleExpressionKinds(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  expectedType: RuntimeValueType | null,
  expectedEntitySchemaId: string | null = null,
): StructuredPrototypeRuleExpressionKind[] {
  const literalType = expectedType ?? "string";
  const kinds: StructuredPrototypeRuleExpressionKind[] =
    createStructuredPrototypeRuleRuntimeValue(document, literalType, expectedEntitySchemaId) ===
    null
      ? []
      : ["literal"];
  if (
    document.runtime.variables.some(
      (variable) =>
        (expectedType === null || variable.valueType === expectedType) &&
        (expectedType !== "entityRef" ||
          expectedEntitySchemaId === null ||
          variable.entitySchemaId === expectedEntitySchemaId),
    )
  ) {
    kinds.push("variable");
  }
  if (
    document.runtime.forms.some((form) =>
      form.fields.some((field) => expectedType === null || field.valueType === expectedType),
    )
  ) {
    kinds.push("formField");
  }
  if (
    (expectedType === null || expectedType === "entityRef") &&
    structuredPrototypeRuleEventSchemaId(document, trigger) !== null &&
    (expectedEntitySchemaId === null ||
      structuredPrototypeRuleEventSchemaId(document, trigger) === expectedEntitySchemaId)
  ) {
    kinds.push("eventEntityRef");
  }
  if (
    expressionReferenceSchemas(document, trigger).some(({ schemaId }) =>
      document.runtime.entitySchemas
        .find((schema) => schema.id === schemaId)
        ?.fields.some(
          (field) =>
            (expectedType === null || field.valueType === expectedType) &&
            createStructuredPrototypeRuleRuntimeValue(document, field.valueType) !== null,
        ),
    )
  ) {
    kinds.push("entityField");
  }
  return kinds;
}

export function createStructuredPrototypeRuleExpression(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  kind: StructuredPrototypeRuleExpressionKind,
  expectedType: RuntimeValueType | null,
  expectedEntitySchemaId: string | null = null,
): RuntimeValueExpression | null {
  if (kind === "literal") {
    const value = createStructuredPrototypeRuleRuntimeValue(
      document,
      expectedType ?? "string",
      expectedEntitySchemaId,
    );
    if (value === null) return null;
    return {
      kind,
      value,
    };
  }
  if (kind === "variable") {
    const variable = document.runtime.variables.find(
      (candidate) =>
        (expectedType === null || candidate.valueType === expectedType) &&
        (expectedType !== "entityRef" ||
          expectedEntitySchemaId === null ||
          candidate.entitySchemaId === expectedEntitySchemaId),
    );
    return variable === undefined ? null : { kind, variableId: variable.id };
  }
  if (kind === "formField") {
    for (const form of document.runtime.forms) {
      const field = form.fields.find(
        (candidate) => expectedType === null || candidate.valueType === expectedType,
      );
      if (field !== undefined) return { kind, formId: form.id, fieldId: field.id };
    }
    return null;
  }
  if (kind === "eventEntityRef") {
    const eventSchemaId = structuredPrototypeRuleEventSchemaId(document, trigger);
    return eventSchemaId === null ||
      (expectedEntitySchemaId !== null && eventSchemaId !== expectedEntitySchemaId)
      ? null
      : { kind };
  }
  for (const reference of expressionReferenceSchemas(document, trigger)) {
    const field = document.runtime.entitySchemas
      .find((schema) => schema.id === reference.schemaId)
      ?.fields.find(
        (candidate) =>
          (expectedType === null || candidate.valueType === expectedType) &&
          createStructuredPrototypeRuleRuntimeValue(document, candidate.valueType) !== null,
      );
    if (field !== undefined) {
      const fallback = createStructuredPrototypeRuleRuntimeValue(document, field.valueType);
      if (fallback === null) continue;
      return {
        kind,
        entityRef: reference.ref,
        fieldId: field.id,
        fallback,
      };
    }
  }
  return null;
}

export function createStructuredPrototypeRulePredicate(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  kind: StructuredPrototypeRulePredicateKind,
): RuntimePredicate | null {
  if (kind === "roleIs") {
    const role = document.runtime.roles[0];
    return role === undefined ? null : { kind, roleId: role.id };
  }
  if (kind === "formValid") {
    const form = document.runtime.forms[0];
    return form === undefined ? null : { kind, formId: form.id };
  }
  if (kind === "compare") {
    const left = createStructuredPrototypeRuleExpression(document, trigger, "literal", "string");
    const right = createStructuredPrototypeRuleExpression(document, trigger, "literal", "string");
    return left === null || right === null ? null : { kind, operator: "eq", left, right };
  }
  const item =
    createStructuredPrototypeRulePredicate(document, trigger, "roleIs") ??
    createStructuredPrototypeRulePredicate(document, trigger, "formValid") ??
    createStructuredPrototypeRulePredicate(document, trigger, "compare");
  return item === null ? null : { kind, items: [item] };
}

export function createStructuredPrototypeRuleEffect(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  kind: StructuredPrototypeRuleEffectKind,
): RuntimeEffect | null {
  if (kind === "navigate") {
    const page = document.pages[0];
    return page === undefined ? null : { kind, targetPageId: page.id };
  }
  if (kind === "notify") return { kind, level: "info", message: "" };
  if (kind === "validateForm") {
    const form = document.runtime.forms[0];
    return form === undefined ? null : { kind, formId: form.id };
  }
  if (kind === "setVariable") {
    for (const variable of document.runtime.variables) {
      const value = createStructuredPrototypeRuleExpression(
        document,
        trigger,
        "literal",
        variable.valueType,
        variable.entitySchemaId,
      );
      if (value !== null) return { kind, variableId: variable.id, value };
    }
    return null;
  }
  const eventSchemaId = structuredPrototypeRuleEventSchemaId(document, trigger);
  const schema =
    kind === "updateEntity" && eventSchemaId !== null
      ? document.runtime.entitySchemas.find((candidate) => candidate.id === eventSchemaId)
      : structuredPrototypeCreateEntitySchemaOptions(document)[0];
  if (schema === undefined) return null;
  const refVariable = document.runtime.variables.find(
    (variable) => variable.valueType === "entityRef" && variable.entitySchemaId === schema.id,
  );
  if (kind === "createEntity") {
    if (refVariable === undefined) return null;
    return { kind, schemaId: schema.id, resultVariableId: refVariable.id, values: [] };
  }
  const field = schema.fields.find(
    (candidate) =>
      createStructuredPrototypeRuleRuntimeValue(document, candidate.valueType) !== null,
  );
  if (field === undefined) return null;
  const entityRef: RuntimeEntityRefExpression =
    eventSchemaId === schema.id
      ? { kind: "eventEntityRef" }
      : refVariable === undefined
        ? { kind: "eventEntityRef" }
        : { kind: "variable", variableId: refVariable.id };
  const value = createStructuredPrototypeRuleExpression(
    document,
    trigger,
    "literal",
    field.valueType,
  );
  return value === null
    ? null
    : {
        kind,
        schemaId: schema.id,
        entityRef,
        updates: [{ fieldId: field.id, value }],
      };
}

function validateRuntimeValue(
  context: ValidationContext,
  value: RuntimeValue,
  path: string,
): RuntimeExpressionIdentity {
  if (value.type === "string" && Array.from(value.value).length > 8_000) {
    addIssue(context, "runtime_string_too_long", path);
  }
  if (value.type === "enum" && !isStructuredPrototypeTechnicalKey(value.value)) {
    addIssue(context, "invalid_enum_value", path);
  }
  if (value.type !== "entityRef") {
    return { valueType: value.type, entitySchemaId: null };
  }
  if (!STRUCTURED_PROTOTYPE_ENTITY_ID_PATTERN.test(value.schemaId)) {
    addIssue(context, "invalid_entity_id", `${path}.schemaId`);
  }
  if (!STRUCTURED_PROTOTYPE_ENTITY_ID_PATTERN.test(value.entityId)) {
    addIssue(context, "invalid_entity_id", `${path}.entityId`);
  }
  if (!context.document.runtime.entitySchemas.some((schema) => schema.id === value.schemaId)) {
    addIssue(context, "unknown_schema", `${path}.schemaId`);
  }
  const fixtureSchemaIds = new Set(
    context.document.runtime.scenarios.flatMap((scenario) =>
      scenario.entityFixtures.flatMap((fixture) =>
        fixture.entities.some(
          (entity) => entity.id === value.entityId && entity.schemaId === fixture.schemaId,
        )
          ? [fixture.schemaId]
          : [],
      ),
    ),
  );
  if (!fixtureSchemaIds.has(value.schemaId)) {
    addIssue(
      context,
      fixtureSchemaIds.size === 0 ? "entity_fixture_missing" : "entity_schema_mismatch",
      fixtureSchemaIds.size === 0 ? `${path}.entityId` : `${path}.schemaId`,
    );
  }
  return { valueType: value.type, entitySchemaId: value.schemaId };
}

function validateExpectedExpressionIdentity(
  context: ValidationContext,
  identity: RuntimeExpressionIdentity,
  expectedType: RuntimeValueType | null,
  expectedEntitySchemaId: string | null,
  allowNull: boolean,
  path: string,
): void {
  if (identity.valueType === "null") {
    if (expectedType !== null && expectedType !== "null" && !allowNull) {
      addIssue(context, "expression_type_mismatch", path);
    }
    return;
  }
  if (expectedType !== null && identity.valueType !== expectedType) {
    addIssue(context, "expression_type_mismatch", path);
    return;
  }
  if (
    expectedType === "entityRef" &&
    expectedEntitySchemaId !== null &&
    identity.entitySchemaId !== expectedEntitySchemaId
  ) {
    addIssue(context, "entity_schema_mismatch", path);
  }
}

function validateEntityRefExpression(
  context: ValidationContext,
  expression: RuntimeEntityRefExpression,
  expectedSchemaId: string | null,
  path: string,
): string | null {
  if (expression.kind === "eventEntityRef") {
    const schemaId = eventEntitySchemaId(context);
    if (schemaId === null) addIssue(context, "event_context_unavailable", path);
    else if (expectedSchemaId !== null && schemaId !== expectedSchemaId) {
      addIssue(context, "entity_schema_mismatch", path);
    }
    return schemaId;
  }
  const variable = context.document.runtime.variables.find(
    (candidate) => candidate.id === expression.variableId,
  );
  if (variable === undefined) {
    addIssue(context, "unknown_variable", `${path}.variableId`);
    return null;
  }
  if (variable.valueType !== "entityRef" || variable.entitySchemaId === null) {
    addIssue(context, "expression_type_mismatch", path);
    return null;
  }
  if (expectedSchemaId !== null && variable.entitySchemaId !== expectedSchemaId) {
    addIssue(context, "entity_schema_mismatch", path);
  }
  return variable.entitySchemaId;
}

export function structuredPrototypeRuleExpressionType(
  document: StructuredPrototypeDocument,
  trigger: RuntimeBehaviorRule["trigger"],
  expression: RuntimeValueExpression,
): RuntimeValueType | null {
  if (expression.kind === "literal") return expression.value.type;
  if (expression.kind === "variable") {
    return (
      document.runtime.variables.find((variable) => variable.id === expression.variableId)
        ?.valueType ?? null
    );
  }
  if (expression.kind === "formField") {
    return (
      document.runtime.forms
        .find((form) => form.id === expression.formId)
        ?.fields.find((field) => field.id === expression.fieldId)?.valueType ?? null
    );
  }
  if (expression.kind === "eventEntityRef") {
    return trigger.event === "rowActivated" ? "entityRef" : null;
  }
  const entityRef = expression.entityRef;
  const refSchemaId =
    entityRef.kind === "eventEntityRef"
      ? structuredPrototypeRuleEventSchemaId(document, trigger)
      : document.runtime.variables.find((variable) => variable.id === entityRef.variableId)
          ?.entitySchemaId;
  if (refSchemaId === null || refSchemaId === undefined) return null;
  return (
    document.runtime.entitySchemas
      .find((schema) => schema.id === refSchemaId)
      ?.fields.find((field) => field.id === expression.fieldId)?.valueType ?? null
  );
}

function entityFieldValueSchemaId(
  context: ValidationContext,
  sourceSchemaId: string,
  fieldId: string,
  fallback: RuntimeExpressionIdentity,
): string | null {
  const schemaIds = new Set<string>();
  if (fallback.valueType === "entityRef" && fallback.entitySchemaId !== null) {
    schemaIds.add(fallback.entitySchemaId);
  }
  for (const fixture of context.document.runtime.scenarios.flatMap(
    (scenario) => scenario.entityFixtures,
  )) {
    if (fixture.schemaId !== sourceSchemaId) continue;
    for (const entity of fixture.entities) {
      const value = entity.fields.find((field) => field.fieldId === fieldId)?.value;
      if (value?.type === "entityRef") schemaIds.add(value.schemaId);
    }
  }
  return schemaIds.size === 1 ? (schemaIds.values().next().value ?? null) : null;
}

function validateExpression(
  context: ValidationContext,
  expression: RuntimeValueExpression,
  expectedType: RuntimeValueType | null,
  allowNull: boolean,
  path: string,
  expectedEntitySchemaId: string | null = null,
): RuntimeExpressionIdentity | null {
  let identity: RuntimeExpressionIdentity | null;
  if (expression.kind === "literal") {
    identity = validateRuntimeValue(context, expression.value, `${path}.value`);
  } else if (expression.kind === "variable") {
    const variable = context.document.runtime.variables.find(
      (candidate) => candidate.id === expression.variableId,
    );
    if (variable === undefined) {
      addIssue(context, "unknown_variable", `${path}.variableId`);
      return null;
    }
    identity = {
      valueType: variable.valueType,
      entitySchemaId: variable.valueType === "entityRef" ? variable.entitySchemaId : null,
    };
  } else if (expression.kind === "formField") {
    const form = context.document.runtime.forms.find(
      (candidate) => candidate.id === expression.formId,
    );
    if (form === undefined) {
      addIssue(context, "unknown_form", `${path}.formId`);
      return null;
    }
    const field = form.fields.find((candidate) => candidate.id === expression.fieldId);
    if (field === undefined) {
      addIssue(context, "unknown_form_field", `${path}.fieldId`);
      return null;
    }
    identity = { valueType: field.valueType, entitySchemaId: null };
  } else if (expression.kind === "eventEntityRef") {
    const schemaId = eventEntitySchemaId(context);
    if (schemaId === null) {
      addIssue(context, "event_context_unavailable", path);
      return null;
    }
    identity = { valueType: "entityRef", entitySchemaId: schemaId };
  } else {
    const schemaId = validateEntityRefExpression(
      context,
      expression.entityRef,
      null,
      `${path}.entityRef`,
    );
    if (schemaId === null) return null;
    const schema = context.document.runtime.entitySchemas.find(
      (candidate) => candidate.id === schemaId,
    );
    if (schema === undefined) {
      addIssue(context, "unknown_schema", `${path}.entityRef`);
      return null;
    }
    const field = schema.fields.find((candidate) => candidate.id === expression.fieldId);
    if (field === undefined) {
      addIssue(context, "unknown_schema_field", `${path}.fieldId`);
      return null;
    }
    const fallbackIdentity = validateRuntimeValue(context, expression.fallback, `${path}.fallback`);
    validateExpectedExpressionIdentity(
      context,
      fallbackIdentity,
      field.valueType,
      null,
      true,
      `${path}.fallback`,
    );
    identity = {
      valueType: field.valueType,
      entitySchemaId:
        field.valueType === "entityRef"
          ? entityFieldValueSchemaId(context, schemaId, field.id, fallbackIdentity)
          : null,
    };
  }
  validateExpectedExpressionIdentity(
    context,
    identity,
    expectedType,
    expectedEntitySchemaId,
    allowNull,
    path,
  );
  return identity;
}

function validatePredicate(
  context: ValidationContext,
  predicate: RuntimePredicate,
  path: string,
): void {
  if (predicate.kind === "all") {
    if (predicate.items.length === 0) addIssue(context, "guard_item_required", `${path}.items`);
    if (predicate.items.length > 20) {
      addIssue(context, "guard_item_limit_exceeded", `${path}.items`);
    }
    predicate.items.forEach((item, index) =>
      validatePredicate(context, item, `${path}.items[${index}]`),
    );
    return;
  }
  if (predicate.kind === "roleIs") {
    if (!context.document.runtime.roles.some((role) => role.id === predicate.roleId)) {
      addIssue(context, "unknown_role", `${path}.roleId`);
    }
    return;
  }
  if (predicate.kind === "formValid") {
    if (!context.document.runtime.forms.some((form) => form.id === predicate.formId)) {
      addIssue(context, "unknown_form", `${path}.formId`);
    }
    return;
  }
  const left = validateExpression(context, predicate.left, null, true, `${path}.left`);
  const right = validateExpression(context, predicate.right, null, true, `${path}.right`);
  if (
    left !== null &&
    right !== null &&
    left.valueType !== "null" &&
    right.valueType !== "null" &&
    left.valueType !== right.valueType
  ) {
    addIssue(context, "expression_type_mismatch", path);
  } else if (
    left?.valueType === "entityRef" &&
    right?.valueType === "entityRef" &&
    left.entitySchemaId !== right.entitySchemaId
  ) {
    addIssue(context, "entity_schema_mismatch", path);
  }
}

function validateAssignments(
  context: ValidationContext,
  schemaId: string,
  assignments: Array<{ fieldId: string; value: RuntimeValueExpression }>,
  path: string,
): void {
  const schema = context.document.runtime.entitySchemas.find(
    (candidate) => candidate.id === schemaId,
  );
  if (schema === undefined) {
    addIssue(context, "unknown_schema", path.replace(/\.(values|updates)$/, ".schemaId"));
    return;
  }
  const seen = new Set<string>();
  assignments.forEach((assignment, index) => {
    const assignmentPath = `${path}[${index}]`;
    if (seen.has(assignment.fieldId)) {
      addIssue(context, "duplicate_field_assignment", `${assignmentPath}.fieldId`);
    }
    seen.add(assignment.fieldId);
    const field = schema.fields.find((candidate) => candidate.id === assignment.fieldId);
    if (field === undefined) {
      addIssue(context, "unknown_schema_field", `${assignmentPath}.fieldId`);
      return;
    }
    validateExpression(
      context,
      assignment.value,
      field.valueType,
      false,
      `${assignmentPath}.value`,
    );
  });
}

function validateEffect(context: ValidationContext, effect: RuntimeEffect, path: string): void {
  if (effect.kind === "navigate") {
    if (!context.document.pages.some((page) => page.id === effect.targetPageId)) {
      addIssue(context, "unknown_page", `${path}.targetPageId`);
    }
    return;
  }
  if (effect.kind === "notify") {
    if (effect.message.trim().length === 0 || effect.message.length > 240) {
      addIssue(context, "invalid_notification", `${path}.message`);
    }
    return;
  }
  if (effect.kind === "validateForm") {
    if (!context.document.runtime.forms.some((form) => form.id === effect.formId)) {
      addIssue(context, "unknown_form", `${path}.formId`);
    }
    return;
  }
  if (effect.kind === "setVariable") {
    const variable = context.document.runtime.variables.find(
      (candidate) => candidate.id === effect.variableId,
    );
    if (variable === undefined) {
      addIssue(context, "unknown_variable", `${path}.variableId`);
      return;
    }
    validateExpression(
      context,
      effect.value,
      variable.valueType,
      false,
      `${path}.value`,
      variable.entitySchemaId,
    );
    return;
  }
  const schema = context.document.runtime.entitySchemas.find(
    (candidate) => candidate.id === effect.schemaId,
  );
  if (schema === undefined) addIssue(context, "unknown_schema", `${path}.schemaId`);
  if (effect.kind === "createEntity") {
    const resultVariable = context.document.runtime.variables.find(
      (variable) => variable.id === effect.resultVariableId,
    );
    if (resultVariable === undefined) {
      addIssue(context, "unknown_variable", `${path}.resultVariableId`);
    } else if (
      resultVariable.valueType !== "entityRef" ||
      resultVariable.entitySchemaId !== effect.schemaId
    ) {
      addIssue(context, "entity_schema_mismatch", `${path}.resultVariableId`);
    }
    validateAssignments(context, effect.schemaId, effect.values, `${path}.values`);
    return;
  }
  validateEntityRefExpression(context, effect.entityRef, effect.schemaId, `${path}.entityRef`);
  if (effect.updates.length === 0) {
    addIssue(context, "update_assignment_required", `${path}.updates`);
  }
  validateAssignments(context, effect.schemaId, effect.updates, `${path}.updates`);
}

export function validateStructuredPrototypeRuleDraft(
  document: StructuredPrototypeDocument,
  draft: StructuredPrototypeRuleDraft,
  editingRuleId: string | null,
): StructuredPrototypeRuleValidationIssue[] {
  const issues: StructuredPrototypeRuleValidationIssue[] = [];
  if (draft.trigger === null) {
    issues.push({ code: "trigger_required", path: "trigger" });
    if (!isStructuredPrototypeTechnicalKey(draft.key)) {
      issues.push({ code: "invalid_key", path: "key" });
    }
    if (
      document.runtime.rules.some((rule) => rule.id !== editingRuleId && rule.key === draft.key)
    ) {
      issues.push({ code: "duplicate_key", path: "key" });
    }
    if (draft.effects.length === 0) {
      issues.push({ code: "primary_effect_required", path: "effects" });
    }
    return issues;
  }
  const trigger = draft.trigger;
  const context: ValidationContext = { document, trigger, issues };
  if (!isStructuredPrototypeTechnicalKey(draft.key)) {
    addIssue(context, "invalid_key", "key");
  }
  if (document.runtime.rules.some((rule) => rule.id !== editingRuleId && rule.key === draft.key)) {
    addIssue(context, "duplicate_key", "key");
  }
  const triggerNodeExists = allNodeVisits(document).some(
    (visit) => visit.node.id === trigger.nodeId,
  );
  if (!triggerNodeExists) addIssue(context, "unknown_trigger_node", "trigger.nodeId");
  else if (!isStructuredPrototypeRuleTriggerEligible(document, trigger)) {
    addIssue(context, "ineligible_trigger_event", "trigger.event");
  }
  if (
    draft.enabled &&
    document.runtime.rules.some(
      (rule) =>
        rule.id !== editingRuleId &&
        rule.enabled &&
        rule.trigger.nodeId === trigger.nodeId &&
        rule.trigger.event === trigger.event,
    )
  ) {
    addIssue(context, "duplicate_trigger", "trigger");
  }
  if (draft.guard !== null) validatePredicate(context, draft.guard, "guard");
  if (draft.effects.length === 0) addIssue(context, "primary_effect_required", "effects");
  if (draft.effects.length > STRUCTURED_PROTOTYPE_PRIMARY_EFFECT_LIMIT) {
    addIssue(context, "effect_limit_exceeded", "effects");
  }
  if (draft.guardFalseEffects.length > STRUCTURED_PROTOTYPE_GUARD_FALSE_EFFECT_LIMIT) {
    addIssue(context, "effect_limit_exceeded", "guardFalseEffects");
  }
  draft.effects.forEach((effect, index) => validateEffect(context, effect, `effects[${index}]`));
  draft.guardFalseEffects.forEach((effect, index) =>
    validateEffect(context, effect, `guardFalseEffects[${index}]`),
  );
  return issues;
}
