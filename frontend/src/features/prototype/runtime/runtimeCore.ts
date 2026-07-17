import { assign, createActor, setup } from "xstate";

import { deterministicUuidV5, hashRuntimeValue } from "./canonical";
import type {
  EntityRefRuntimeValue,
  PrototypeRuntimeState,
  RuntimeBehaviorRule,
  RuntimeDefinition,
  RuntimeEffect,
  RuntimeEffectTrace,
  RuntimeEntity,
  RuntimeEntitySet,
  RuntimeEvent,
  RuntimeEventBatch,
  RuntimeFieldValue,
  RuntimeFormError,
  RuntimeFormState,
  RuntimeNodeViewModel,
  RuntimePredicate,
  RuntimeTransitionReduction,
  RuntimeTransitionResult,
  RuntimeValue,
  RuntimeValueExpression,
  RuntimeViewModel,
  RuntimeViewProperty,
} from "./types";

export const RUNTIME_CORE_VERSION = "0.2.0-spike";
export const XSTATE_KERNEL_VERSION = "5.32.4";

const RUNTIME_ENTITY_NAMESPACE = "1af0c23d-70d2-5fd5-aad8-3f1eafbb10a1";

export class RuntimeCoreError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RuntimeCoreError";
  }
}

interface RuntimeAllocation {
  key: string;
  entityId: string;
}

type RuntimeEffectBranch = "effects" | "guardFalseEffects";

interface RuntimeNodeEventIdentity {
  nodeId: string;
  event: RuntimeBehaviorRule["trigger"]["event"];
}

interface RuntimeMachineInput {
  definition: RuntimeDefinition;
  state: PrototypeRuntimeState;
}

interface RuntimeMachineContext extends RuntimeMachineInput {
  reduction: RuntimeTransitionReduction | null;
}

interface RuntimeMachineEvent {
  type: "runtime.eventBatch";
  batch: RuntimeEventBatch;
  allocations: RuntimeAllocation[];
}

interface EffectResult {
  state: PrototypeRuntimeState;
  stop: boolean;
  outcome: RuntimeTransitionReduction["outcome"];
}

function requireItem<T>(item: T | undefined, code: string, message: string): T {
  if (item === undefined) {
    throw new RuntimeCoreError(code, message);
  }
  return item;
}

function assertUniqueIds(items: ReadonlyArray<{ id: string }>, label: string): string[] {
  return assertUniqueValues(
    items.map((item) => item.id),
    label,
  );
}

function assertUniqueValues(values: readonly string[], label: string): string[] {
  const seen = new Set<string>();
  const errors: string[] = [];
  for (const value of values) {
    if (seen.has(value)) {
      errors.push(`${label} contains duplicate id ${value}`);
    }
    seen.add(value);
  }
  return errors;
}

function valueMatchesType(
  value: RuntimeValue,
  expected: RuntimeValue["type"],
  nullable: boolean,
): boolean {
  if (value.type === "null") {
    return nullable;
  }
  return value.type === expected;
}

function entityRefMatchesSchema(value: RuntimeValue, entitySchemaId: string | null): boolean {
  return value.type !== "entityRef" || value.schemaId === entitySchemaId;
}

function valueExpressionUsesEventEntityRef(expression: RuntimeValueExpression): boolean {
  switch (expression.kind) {
    case "eventEntityRef":
      return true;
    case "entityField":
      return valueExpressionUsesEventEntityRef(expression.entityRef);
    case "literal":
    case "variable":
    case "formField":
      return false;
  }
}

function predicateUsesEventEntityRef(predicate: RuntimePredicate): boolean {
  switch (predicate.kind) {
    case "all":
      return predicate.items.some(predicateUsesEventEntityRef);
    case "compare":
      return (
        valueExpressionUsesEventEntityRef(predicate.left) ||
        valueExpressionUsesEventEntityRef(predicate.right)
      );
    case "roleIs":
    case "formValid":
      return false;
  }
}

export function validateRuntimeDefinition(definition: RuntimeDefinition): string[] {
  const errors = [
    ...assertUniqueValues(definition.pageIds, "pages"),
    ...assertUniqueIds(definition.roles, "roles"),
    ...assertUniqueIds(definition.variables, "variables"),
    ...assertUniqueIds(definition.entitySchemas, "entitySchemas"),
    ...assertUniqueIds(definition.forms, "forms"),
    ...assertUniqueIds(definition.viewBindings, "viewBindings"),
    ...assertUniqueValues(
      definition.viewBindings.map((binding) => `${binding.nodeId}:${binding.target}`),
      "view binding node targets",
    ),
    ...assertUniqueIds(definition.rules, "rules"),
    ...assertUniqueIds(definition.scenarios, "scenarios"),
  ];
  const roleIds = new Set(definition.roles.map((role) => role.id));
  const pageIds = new Set(definition.pageIds);
  const schemaIds = new Set(definition.entitySchemas.map((schema) => schema.id));

  for (const variable of definition.variables) {
    if (variable.valueType === "entityRef") {
      if (variable.entitySchemaId === null) {
        errors.push(`variable ${variable.id} entityRef type requires an entity schema`);
      } else if (!schemaIds.has(variable.entitySchemaId)) {
        errors.push(
          `variable ${variable.id} references unknown entity schema ${variable.entitySchemaId}`,
        );
      }
    } else if (variable.entitySchemaId !== null) {
      errors.push(`variable ${variable.id} non-entityRef type cannot declare an entity schema`);
    }
    if (!valueMatchesType(variable.defaultValue, variable.valueType, variable.nullable)) {
      errors.push(`variable ${variable.id} default value does not match ${variable.valueType}`);
    } else if (!entityRefMatchesSchema(variable.defaultValue, variable.entitySchemaId)) {
      errors.push(`variable ${variable.id} default entity schema does not match its definition`);
    }
  }
  for (const scenario of definition.scenarios) {
    errors.push(
      ...assertUniqueValues(
        scenario.initialVariables.map((entry) => entry.variableId),
        `scenario ${scenario.id} variables`,
      ),
      ...assertUniqueValues(
        scenario.entityFixtures.map((fixture) => fixture.schemaId),
        `scenario ${scenario.id} entity fixtures`,
      ),
    );
    if (!roleIds.has(scenario.actorRoleId)) {
      errors.push(`scenario ${scenario.id} references unknown role ${scenario.actorRoleId}`);
    }
    if (!pageIds.has(scenario.startPageId)) {
      errors.push(`scenario ${scenario.id} references unknown page ${scenario.startPageId}`);
    }
    for (const value of scenario.initialVariables) {
      const variable = definition.variables.find((candidate) => candidate.id === value.variableId);
      if (variable === undefined) {
        errors.push(`scenario ${scenario.id} references unknown variable ${value.variableId}`);
      } else if (!valueMatchesType(value.value, variable.valueType, variable.nullable)) {
        errors.push(
          `scenario ${scenario.id} variable ${value.variableId} does not match ${variable.valueType}`,
        );
      } else if (!entityRefMatchesSchema(value.value, variable.entitySchemaId)) {
        errors.push(
          `scenario ${scenario.id} variable ${value.variableId} entity schema does not match its definition`,
        );
      }
    }
    for (const fixture of scenario.entityFixtures) {
      if (!schemaIds.has(fixture.schemaId)) {
        errors.push(`scenario ${scenario.id} references unknown schema ${fixture.schemaId}`);
      }
    }
  }
  for (const rule of definition.rules) {
    if (rule.effects.length === 0) {
      errors.push(`rule ${rule.id} has no effects`);
    }
    for (const effect of [...rule.effects, ...rule.guardFalseEffects]) {
      if (effect.kind !== "createEntity") {
        continue;
      }
      const resultVariable = definition.variables.find(
        (variable) => variable.id === effect.resultVariableId,
      );
      if (
        resultVariable === undefined ||
        resultVariable.valueType !== "entityRef" ||
        resultVariable.entitySchemaId !== effect.schemaId
      ) {
        errors.push(
          `rule ${rule.id} create-entity result variable does not match schema ${effect.schemaId}`,
        );
      }
    }
  }
  for (const binding of definition.viewBindings) {
    if (binding.target === "tableRows" && !schemaIds.has(binding.schemaId)) {
      errors.push(`view binding ${binding.id} references unknown schema ${binding.schemaId}`);
    }
    if (
      (binding.target === "textContent" && valueExpressionUsesEventEntityRef(binding.value)) ||
      (binding.target === "visibility" && predicateUsesEventEntityRef(binding.predicate))
    ) {
      errors.push(`view binding ${binding.id} cannot reference the current event entity`);
    }
  }
  for (const form of definition.forms) {
    errors.push(...assertUniqueIds(form.fields, `form ${form.id} fields`));
  }
  for (const schema of definition.entitySchemas) {
    errors.push(...assertUniqueIds(schema.fields, `schema ${schema.id} fields`));
  }
  if (definition.roles.length === 0) {
    errors.push("runtime definition requires at least one role");
  }
  if (definition.scenarios.length === 0) {
    errors.push("runtime definition requires at least one scenario");
  }
  return errors;
}

export function validateRuntimeState(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
): string[] {
  const errors: string[] = [];
  if (state.runtimeCoreVersion !== RUNTIME_CORE_VERSION) {
    errors.push(
      `runtime core version ${state.runtimeCoreVersion} does not match ${RUNTIME_CORE_VERSION}`,
    );
  }
  if (state.stateMachineKernelVersion !== XSTATE_KERNEL_VERSION) {
    errors.push(
      `state machine kernel version ${state.stateMachineKernelVersion} does not match ${XSTATE_KERNEL_VERSION}`,
    );
  }
  if (state.sessionId.length === 0) {
    errors.push("runtime session id must not be empty");
  }
  if (state.sequenceNo < 0) {
    errors.push("runtime sequence must not be negative");
  }
  if (!definition.roles.some((role) => role.id === state.actorRoleId)) {
    errors.push(`runtime state references unknown role ${state.actorRoleId}`);
  }
  if (!definition.pageIds.includes(state.currentPageId)) {
    errors.push(`runtime state references unknown current page ${state.currentPageId}`);
  }
  for (const pageId of state.navigationStack) {
    if (!definition.pageIds.includes(pageId)) {
      errors.push(`runtime navigation stack references unknown page ${pageId}`);
    }
  }

  const scenario = definition.scenarios.find((candidate) => candidate.id === state.scenarioId);
  if (scenario === undefined) {
    errors.push(`runtime state references unknown scenario ${state.scenarioId}`);
  } else if (state.allowSimulatedRoleSwitch !== scenario.allowSimulatedRoleSwitch) {
    errors.push(`runtime state role-switch policy does not match scenario ${state.scenarioId}`);
  }

  errors.push(
    ...assertUniqueValues(
      state.variableValues.map((entry) => entry.variableId),
      "runtime variable values",
    ),
  );
  for (const definitionVariable of definition.variables) {
    if (!state.variableValues.some((entry) => entry.variableId === definitionVariable.id)) {
      errors.push(`runtime state is missing variable ${definitionVariable.id}`);
    }
  }
  for (const entry of state.variableValues) {
    const variable = definition.variables.find((candidate) => candidate.id === entry.variableId);
    if (variable === undefined) {
      errors.push(`runtime state contains unknown variable ${entry.variableId}`);
    } else if (!valueMatchesType(entry.value, variable.valueType, variable.nullable)) {
      errors.push(`runtime variable ${entry.variableId} does not match ${variable.valueType}`);
    } else if (!entityRefMatchesSchema(entry.value, variable.entitySchemaId)) {
      errors.push(
        `runtime variable ${entry.variableId} entity schema does not match its definition`,
      );
    }
  }

  errors.push(
    ...assertUniqueValues(
      state.entitySets.map((set) => set.schemaId),
      "runtime entity sets",
    ),
  );
  for (const schema of definition.entitySchemas) {
    if (!state.entitySets.some((set) => set.schemaId === schema.id)) {
      errors.push(`runtime state is missing entity set ${schema.id}`);
    }
  }
  for (const set of state.entitySets) {
    const schema = definition.entitySchemas.find((candidate) => candidate.id === set.schemaId);
    if (schema === undefined) {
      errors.push(`runtime state contains unknown entity set ${set.schemaId}`);
      continue;
    }
    errors.push(
      ...assertUniqueValues(
        set.entities.map((entity) => entity.id),
        `runtime entity set ${set.schemaId}`,
      ),
    );
    for (const entity of set.entities) {
      if (entity.schemaId !== set.schemaId) {
        errors.push(`runtime entity ${entity.id} schema does not match set ${set.schemaId}`);
      }
      errors.push(
        ...assertUniqueValues(
          entity.fields.map((field) => field.fieldId),
          `runtime entity ${entity.id} fields`,
        ),
      );
      for (const fieldDefinition of schema.fields) {
        if (!entity.fields.some((field) => field.fieldId === fieldDefinition.id)) {
          errors.push(`runtime entity ${entity.id} is missing field ${fieldDefinition.id}`);
        }
      }
      for (const field of entity.fields) {
        const fieldDefinition = schema.fields.find((candidate) => candidate.id === field.fieldId);
        if (fieldDefinition === undefined) {
          errors.push(`runtime entity ${entity.id} contains unknown field ${field.fieldId}`);
        } else if (
          !valueMatchesType(field.value, fieldDefinition.valueType, fieldDefinition.nullable)
        ) {
          errors.push(
            `runtime entity ${entity.id} field ${field.fieldId} does not match ${fieldDefinition.valueType}`,
          );
        }
      }
    }
  }

  errors.push(
    ...assertUniqueValues(
      state.formStates.map((form) => form.formId),
      "runtime form states",
    ),
  );
  for (const formDefinition of definition.forms) {
    if (!state.formStates.some((form) => form.formId === formDefinition.id)) {
      errors.push(`runtime state is missing form ${formDefinition.id}`);
    }
  }
  for (const form of state.formStates) {
    const formDefinition = definition.forms.find((candidate) => candidate.id === form.formId);
    if (formDefinition === undefined) {
      errors.push(`runtime state contains unknown form ${form.formId}`);
      continue;
    }
    errors.push(
      ...assertUniqueValues(
        form.values.map((field) => field.fieldId),
        `runtime form ${form.formId} values`,
      ),
    );
    for (const fieldDefinition of formDefinition.fields) {
      if (!form.values.some((field) => field.fieldId === fieldDefinition.id)) {
        errors.push(`runtime form ${form.formId} is missing field ${fieldDefinition.id}`);
      }
    }
    for (const field of form.values) {
      const fieldDefinition = formDefinition.fields.find(
        (candidate) => candidate.id === field.fieldId,
      );
      if (fieldDefinition === undefined) {
        errors.push(`runtime form ${form.formId} contains unknown field ${field.fieldId}`);
      } else if (field.value.type !== fieldDefinition.valueType) {
        errors.push(
          `runtime form ${form.formId} field ${field.fieldId} does not match ${fieldDefinition.valueType}`,
        );
      }
    }
    for (const formError of form.errors) {
      if (!formDefinition.fields.some((field) => field.id === formError.fieldId)) {
        errors.push(
          `runtime form ${form.formId} error references unknown field ${formError.fieldId}`,
        );
      }
    }
  }

  errors.push(
    ...assertUniqueValues(
      state.notifications.map((notification) => notification.id),
      "runtime notifications",
    ),
  );
  return errors;
}

function cloneRuntimeValue(value: RuntimeValue): RuntimeValue {
  return { ...value };
}

function cloneFieldValues(values: RuntimeFieldValue[]): RuntimeFieldValue[] {
  return values.map((entry) => ({ fieldId: entry.fieldId, value: cloneRuntimeValue(entry.value) }));
}

function cloneEntity(entity: RuntimeEntity): RuntimeEntity {
  return { id: entity.id, schemaId: entity.schemaId, fields: cloneFieldValues(entity.fields) };
}

function cloneState(state: PrototypeRuntimeState): PrototypeRuntimeState {
  return {
    ...state,
    navigationStack: [...state.navigationStack],
    variableValues: state.variableValues.map((entry) => ({
      variableId: entry.variableId,
      value: cloneRuntimeValue(entry.value),
    })),
    entitySets: state.entitySets.map((set) => ({
      schemaId: set.schemaId,
      entities: set.entities.map(cloneEntity),
    })),
    formStates: state.formStates.map((form) => ({
      formId: form.formId,
      values: cloneFieldValues(form.values),
      errors: form.errors.map((error) => ({ ...error })),
    })),
    notifications: state.notifications.map((notification) => ({ ...notification })),
  };
}

export function createInitialRuntimeState(
  definition: RuntimeDefinition,
  scenarioId: string,
  sessionId: string,
): PrototypeRuntimeState {
  const validationErrors = validateRuntimeDefinition(definition);
  if (validationErrors.length > 0) {
    throw new RuntimeCoreError("runtime_definition_invalid", validationErrors.join("; "));
  }
  const scenario = requireItem(
    definition.scenarios.find((candidate) => candidate.id === scenarioId),
    "runtime_scenario_missing",
    `Unknown runtime scenario ${scenarioId}`,
  );
  const initialVariableById = new Map(
    scenario.initialVariables.map((entry) => [entry.variableId, entry.value] as const),
  );

  const state: PrototypeRuntimeState = {
    runtimeStateSchemaVersion: 1,
    sessionId,
    scenarioId,
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    sequenceNo: 0,
    actorRoleId: scenario.actorRoleId,
    currentPageId: scenario.startPageId,
    navigationStack: [],
    variableValues: definition.variables.map((variable) => ({
      variableId: variable.id,
      value: cloneRuntimeValue(initialVariableById.get(variable.id) ?? variable.defaultValue),
    })),
    entitySets: definition.entitySchemas.map((schema) => {
      const fixture = scenario.entityFixtures.find((candidate) => candidate.schemaId === schema.id);
      return {
        schemaId: schema.id,
        entities: fixture === undefined ? [] : fixture.entities.map(cloneEntity),
      };
    }),
    formStates: definition.forms.map((form) => ({
      formId: form.id,
      values: form.fields.map((field) => ({
        fieldId: field.id,
        value: cloneRuntimeValue(field.initialValue),
      })),
      errors: [],
    })),
    notifications: [],
    allowSimulatedRoleSwitch: scenario.allowSimulatedRoleSwitch,
  };
  const stateErrors = validateRuntimeState(definition, state);
  if (stateErrors.length > 0) {
    throw new RuntimeCoreError("runtime_state_invalid", stateErrors.join("; "));
  }
  return state;
}

function requireFormState(state: PrototypeRuntimeState, formId: string): RuntimeFormState {
  return requireItem(
    state.formStates.find((form) => form.formId === formId),
    "runtime_form_state_missing",
    `Runtime form state ${formId} does not exist`,
  );
}

function requireFieldValue(values: RuntimeFieldValue[], fieldId: string): RuntimeValue {
  return requireItem(
    values.find((entry) => entry.fieldId === fieldId),
    "runtime_field_value_missing",
    `Runtime field value ${fieldId} does not exist`,
  ).value;
}

function requireVariableValue(state: PrototypeRuntimeState, variableId: string): RuntimeValue {
  return requireItem(
    state.variableValues.find((entry) => entry.variableId === variableId),
    "runtime_variable_value_missing",
    `Runtime variable ${variableId} does not exist`,
  ).value;
}

function requireEntitySet(state: PrototypeRuntimeState, schemaId: string): RuntimeEntitySet {
  return requireItem(
    state.entitySets.find((set) => set.schemaId === schemaId),
    "runtime_entity_set_missing",
    `Runtime entity set ${schemaId} does not exist`,
  );
}

function resolveEntityRef(
  state: PrototypeRuntimeState,
  expression: RuntimeValueExpression,
  event: RuntimeEvent,
): EntityRefRuntimeValue {
  const value = evaluateValueExpression(state, expression, event);
  if (value.type !== "entityRef") {
    throw new RuntimeCoreError(
      "runtime_entity_ref_required",
      "Expression did not resolve to entityRef",
    );
  }
  return value;
}

function evaluateValueExpression(
  state: PrototypeRuntimeState,
  expression: RuntimeValueExpression,
  event: RuntimeEvent,
): RuntimeValue {
  switch (expression.kind) {
    case "literal":
      return cloneRuntimeValue(expression.value);
    case "variable":
      return cloneRuntimeValue(requireVariableValue(state, expression.variableId));
    case "formField":
      return cloneRuntimeValue(
        requireFieldValue(requireFormState(state, expression.formId).values, expression.fieldId),
      );
    case "eventEntityRef":
      if (event.kind !== "tableRowActivated") {
        throw new RuntimeCoreError(
          "runtime_event_entity_ref_missing",
          "Current runtime event has no entity reference",
        );
      }
      return cloneRuntimeValue(event.entityRef);
    case "entityField": {
      const referenceValue = evaluateValueExpression(state, expression.entityRef, event);
      if (referenceValue.type === "null") {
        return cloneRuntimeValue(expression.fallback);
      }
      if (referenceValue.type !== "entityRef") {
        throw new RuntimeCoreError(
          "runtime_entity_ref_required",
          "Entity field expression did not resolve to entityRef",
        );
      }
      const entityRef = referenceValue;
      const entity = requireItem(
        requireEntitySet(state, entityRef.schemaId).entities.find(
          (candidate) => candidate.id === entityRef.entityId,
        ),
        "runtime_entity_missing",
        `Runtime entity ${entityRef.entityId} does not exist`,
      );
      return cloneRuntimeValue(requireFieldValue(entity.fields, expression.fieldId));
    }
  }
}

function runtimeValuesEqual(left: RuntimeValue, right: RuntimeValue): boolean {
  if (left.type !== right.type) {
    return false;
  }
  switch (left.type) {
    case "null":
      return true;
    case "boolean":
      return right.type === "boolean" && left.value === right.value;
    case "integer":
      return right.type === "integer" && left.value === right.value;
    case "string":
      return right.type === "string" && left.value === right.value;
    case "enum":
      return right.type === "enum" && left.value === right.value;
    case "entityRef":
      return (
        right.type === "entityRef" &&
        left.schemaId === right.schemaId &&
        left.entityId === right.entityId
      );
  }
}

function validateForm(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  formId: string,
): RuntimeFormError[] {
  const formDefinition = requireItem(
    definition.forms.find((form) => form.id === formId),
    "runtime_form_definition_missing",
    `Runtime form definition ${formId} does not exist`,
  );
  const formState = requireFormState(state, formId);
  const errors: RuntimeFormError[] = [];
  for (const field of formDefinition.fields) {
    const value = requireFieldValue(formState.values, field.id);
    if (field.valueType !== value.type) {
      errors.push({ fieldId: field.id, code: "type_mismatch" });
      continue;
    }
    if (field.required && value.type === "string" && value.value.trim().length === 0) {
      errors.push({ fieldId: field.id, code: "required" });
    }
    if (
      field.required &&
      value.type === "integer" &&
      field.minInteger !== null &&
      value.value < field.minInteger
    ) {
      errors.push({ fieldId: field.id, code: "min_integer" });
    }
  }
  return errors;
}

function evaluatePredicate(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  predicate: RuntimePredicate,
  event: RuntimeEvent,
): boolean {
  switch (predicate.kind) {
    case "all":
      return predicate.items.every((item) => evaluatePredicate(definition, state, item, event));
    case "roleIs":
      return state.actorRoleId === predicate.roleId;
    case "formValid":
      return validateForm(definition, state, predicate.formId).length === 0;
    case "compare": {
      const equal = runtimeValuesEqual(
        evaluateValueExpression(state, predicate.left, event),
        evaluateValueExpression(state, predicate.right, event),
      );
      return predicate.operator === "eq" ? equal : !equal;
    }
  }
}

function replaceVariableValue(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  variableId: string,
  value: RuntimeValue,
): PrototypeRuntimeState {
  const variable = requireItem(
    definition.variables.find((candidate) => candidate.id === variableId),
    "runtime_variable_definition_missing",
    `Unknown variable definition ${variableId}`,
  );
  if (!valueMatchesType(value, variable.valueType, variable.nullable)) {
    throw new RuntimeCoreError(
      "runtime_variable_type_mismatch",
      `Variable ${variableId} requires ${variable.valueType}`,
    );
  }
  if (!entityRefMatchesSchema(value, variable.entitySchemaId)) {
    throw new RuntimeCoreError(
      "runtime_variable_entity_schema_mismatch",
      `Variable ${variableId} requires entity schema ${variable.entitySchemaId}`,
    );
  }
  let replaced = false;
  const variableValues = state.variableValues.map((entry) => {
    if (entry.variableId !== variableId) {
      return entry;
    }
    replaced = true;
    return { variableId, value: cloneRuntimeValue(value) };
  });
  if (!replaced) {
    throw new RuntimeCoreError("runtime_variable_value_missing", `Unknown variable ${variableId}`);
  }
  return { ...state, variableValues };
}

function replaceFormState(
  state: PrototypeRuntimeState,
  formId: string,
  replacement: RuntimeFormState,
): PrototypeRuntimeState {
  return {
    ...state,
    formStates: state.formStates.map((form) => (form.formId === formId ? replacement : form)),
  };
}

function replaceEntitySet(
  state: PrototypeRuntimeState,
  schemaId: string,
  replacement: RuntimeEntitySet,
): PrototypeRuntimeState {
  return {
    ...state,
    entitySets: state.entitySets.map((set) => (set.schemaId === schemaId ? replacement : set)),
  };
}

function requireAllocation(allocations: RuntimeAllocation[], key: string): string {
  return requireItem(
    allocations.find((allocation) => allocation.key === key),
    "runtime_entity_allocation_missing",
    `Runtime entity allocation ${key} does not exist`,
  ).entityId;
}

function applyEffect(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  event: RuntimeEvent,
  effect: RuntimeEffect,
  eventIndex: number,
  branch: RuntimeEffectBranch,
  effectIndex: number,
  allocations: RuntimeAllocation[],
): EffectResult {
  switch (effect.kind) {
    case "setVariable":
      return {
        state: replaceVariableValue(
          definition,
          state,
          effect.variableId,
          evaluateValueExpression(state, effect.value, event),
        ),
        stop: false,
        outcome: "applied",
      };
    case "validateForm": {
      const errors = validateForm(definition, state, effect.formId);
      const form = requireFormState(state, effect.formId);
      const nextState = replaceFormState(state, effect.formId, { ...form, errors });
      return {
        state: nextState,
        stop: errors.length > 0,
        outcome: errors.length > 0 ? "validation_failed" : "applied",
      };
    }
    case "createEntity": {
      const entityId = requireAllocation(allocations, `${eventIndex}:${branch}:${effectIndex}`);
      const schema = requireItem(
        definition.entitySchemas.find((candidate) => candidate.id === effect.schemaId),
        "runtime_entity_schema_missing",
        `Runtime schema ${effect.schemaId} does not exist`,
      );
      const fields = schema.fields.map((field) => {
        const assignment = requireItem(
          effect.values.find((candidate) => candidate.fieldId === field.id),
          "runtime_entity_field_assignment_missing",
          `Create effect is missing field ${field.id}`,
        );
        const value = evaluateValueExpression(state, assignment.value, event);
        if (!valueMatchesType(value, field.valueType, field.nullable)) {
          throw new RuntimeCoreError(
            "runtime_entity_field_type_mismatch",
            `Entity field ${field.id} value does not match ${field.valueType}`,
          );
        }
        return { fieldId: field.id, value };
      });
      const set = requireEntitySet(state, effect.schemaId);
      const withEntity = replaceEntitySet(state, effect.schemaId, {
        ...set,
        entities: [...set.entities, { id: entityId, schemaId: effect.schemaId, fields }],
      });
      return {
        state: replaceVariableValue(definition, withEntity, effect.resultVariableId, {
          type: "entityRef",
          schemaId: effect.schemaId,
          entityId,
        }),
        stop: false,
        outcome: "applied",
      };
    }
    case "updateEntity": {
      const entityRef = resolveEntityRef(state, effect.entityRef, event);
      if (entityRef.schemaId !== effect.schemaId) {
        throw new RuntimeCoreError(
          "runtime_entity_schema_mismatch",
          `Entity ref schema ${entityRef.schemaId} does not match ${effect.schemaId}`,
        );
      }
      const schema = requireItem(
        definition.entitySchemas.find((candidate) => candidate.id === effect.schemaId),
        "runtime_entity_schema_missing",
        `Runtime schema ${effect.schemaId} does not exist`,
      );
      const set = requireEntitySet(state, effect.schemaId);
      let found = false;
      const entities = set.entities.map((entity) => {
        if (entity.id !== entityRef.entityId) {
          return entity;
        }
        found = true;
        const fields = entity.fields.map((fieldValue) => {
          const update = effect.updates.find(
            (candidate) => candidate.fieldId === fieldValue.fieldId,
          );
          if (update === undefined) {
            return fieldValue;
          }
          const field = requireItem(
            schema.fields.find((candidate) => candidate.id === update.fieldId),
            "runtime_entity_field_missing",
            `Runtime field ${update.fieldId} does not exist`,
          );
          const value = evaluateValueExpression(state, update.value, event);
          if (!valueMatchesType(value, field.valueType, field.nullable)) {
            throw new RuntimeCoreError(
              "runtime_entity_field_type_mismatch",
              `Entity field ${field.id} value does not match ${field.valueType}`,
            );
          }
          return { fieldId: fieldValue.fieldId, value };
        });
        return { ...entity, fields };
      });
      if (!found) {
        throw new RuntimeCoreError(
          "runtime_entity_missing",
          `Runtime entity ${entityRef.entityId} does not exist`,
        );
      }
      return {
        state: replaceEntitySet(state, effect.schemaId, { ...set, entities }),
        stop: false,
        outcome: "applied",
      };
    }
    case "navigate": {
      if (!definition.pageIds.includes(effect.targetPageId)) {
        throw new RuntimeCoreError(
          "runtime_page_missing",
          `Runtime page ${effect.targetPageId} does not exist`,
        );
      }
      return {
        state: {
          ...state,
          currentPageId: effect.targetPageId,
          navigationStack:
            state.currentPageId === effect.targetPageId
              ? state.navigationStack
              : [...state.navigationStack, state.currentPageId],
        },
        stop: false,
        outcome: "applied",
      };
    }
    case "notify":
      return {
        state: {
          ...state,
          notifications: [
            ...state.notifications,
            {
              id: `${state.sessionId}:${state.sequenceNo + 1}:${eventIndex}:${effectIndex}`,
              level: effect.level,
              message: effect.message,
            },
          ],
        },
        stop: false,
        outcome: "applied",
      };
  }
}

function runtimeNodeEventIdentity(event: RuntimeEvent): RuntimeNodeEventIdentity | null {
  switch (event.kind) {
    case "nodeActivated":
      return { nodeId: event.nodeId, event: event.event };
    case "tableRowActivated":
      return { nodeId: event.nodeId, event: "rowActivated" };
    case "fieldValueCommitted":
    case "switchSimulatedRole":
      return null;
  }
}

function findRuleForEvent(
  definition: RuntimeDefinition,
  event: RuntimeEvent,
): RuntimeBehaviorRule | null {
  const identity = runtimeNodeEventIdentity(event);
  if (identity === null) {
    return null;
  }
  const matches = definition.rules.filter(
    (rule) =>
      rule.enabled &&
      rule.trigger.kind === "nodeEvent" &&
      rule.trigger.nodeId === identity.nodeId &&
      rule.trigger.event === identity.event,
  );
  if (matches.length > 1) {
    throw new RuntimeCoreError(
      "runtime_rule_ambiguous",
      `Multiple runtime rules match node ${identity.nodeId} event ${identity.event}`,
    );
  }
  return matches[0] ?? null;
}

function assertTableRowVisible(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  event: RuntimeEvent,
): void {
  if (event.kind !== "tableRowActivated") {
    return;
  }
  const viewModel = deriveRuntimeViewModel(definition, state);
  const rows = viewModel.nodes
    .find((node) => node.nodeId === event.nodeId)
    ?.properties.find((property) => property.target === "tableRows");
  if (rows?.target !== "tableRows") {
    throw new RuntimeCoreError(
      "runtime_table_binding_missing",
      `Runtime table ${event.nodeId} has no rows binding`,
    );
  }
  const visible = rows.rows.some(
    (entity) =>
      entity.id === event.entityRef.entityId && entity.schemaId === event.entityRef.schemaId,
  );
  if (!visible) {
    throw new RuntimeCoreError(
      "runtime_table_entity_not_visible",
      `Runtime entity ${event.entityRef.entityId} is not visible in table ${event.nodeId}`,
    );
  }
}

function applyFieldValueEvent(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  event: RuntimeEvent,
): PrototypeRuntimeState {
  if (event.kind !== "fieldValueCommitted") {
    return state;
  }
  const formDefinition = requireItem(
    definition.forms.find((form) => form.id === event.formId),
    "runtime_form_definition_missing",
    `Runtime form definition ${event.formId} does not exist`,
  );
  const field = requireItem(
    formDefinition.fields.find((candidate) => candidate.id === event.fieldId),
    "runtime_form_field_missing",
    `Runtime form field ${event.fieldId} does not exist`,
  );
  if (event.value.type !== field.valueType) {
    throw new RuntimeCoreError(
      "runtime_form_field_type_mismatch",
      `Runtime form field ${event.fieldId} requires ${field.valueType}`,
    );
  }
  const form = requireFormState(state, event.formId);
  return replaceFormState(state, event.formId, {
    ...form,
    values: form.values.map((entry) =>
      entry.fieldId === event.fieldId ? { ...entry, value: cloneRuntimeValue(event.value) } : entry,
    ),
    errors: form.errors.filter((error) => error.fieldId !== event.fieldId),
  });
}

function applyRoleSwitchEvent(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  event: RuntimeEvent,
): PrototypeRuntimeState {
  if (event.kind !== "switchSimulatedRole") {
    return state;
  }
  if (!state.allowSimulatedRoleSwitch) {
    throw new RuntimeCoreError(
      "runtime_role_switch_forbidden",
      "Runtime scenario does not allow simulated role switching",
    );
  }
  if (!definition.roles.some((role) => role.id === event.roleId)) {
    throw new RuntimeCoreError(
      "runtime_role_missing",
      `Runtime role ${event.roleId} does not exist`,
    );
  }
  return { ...state, actorRoleId: event.roleId };
}

function applyRuleEffects(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  event: RuntimeEvent,
  eventIndex: number,
  branch: RuntimeEffectBranch,
  effects: RuntimeEffect[],
  allocations: RuntimeAllocation[],
  traces: RuntimeEffectTrace[],
): EffectResult {
  let current = state;
  let outcome: RuntimeTransitionReduction["outcome"] = "applied";
  for (const [effectIndex, effect] of effects.entries()) {
    const beforeState = cloneState(current);
    const result = applyEffect(
      definition,
      current,
      event,
      effect,
      eventIndex,
      branch,
      effectIndex,
      allocations,
    );
    current = result.state;
    outcome = result.outcome;
    traces.push({
      eventIndex,
      effectIndex,
      effectKind: effect.kind,
      beforeState,
      afterState: cloneState(current),
    });
    if (result.stop) {
      return { state: current, stop: true, outcome };
    }
  }
  return { state: current, stop: false, outcome };
}

function reduceEventBatch(
  definition: RuntimeDefinition,
  baseState: PrototypeRuntimeState,
  batch: RuntimeEventBatch,
  allocations: RuntimeAllocation[],
): RuntimeTransitionReduction {
  let state = cloneState(baseState);
  let outcome: RuntimeTransitionReduction["outcome"] = "applied";
  const matchedRuleIds: string[] = [];
  const effectTraces: RuntimeEffectTrace[] = [];

  for (const [eventIndex, event] of batch.events.entries()) {
    state = applyFieldValueEvent(definition, state, event);
    state = applyRoleSwitchEvent(definition, state, event);
    const identity = runtimeNodeEventIdentity(event);
    const rule = findRuleForEvent(definition, event);
    if (identity === null) {
      continue;
    }
    if (rule === null) {
      throw new RuntimeCoreError(
        "runtime_rule_missing",
        `No runtime rule matches node ${identity.nodeId}`,
      );
    }
    assertTableRowVisible(definition, state, event);
    matchedRuleIds.push(rule.id);
    const guardPasses =
      rule.guard === null || evaluatePredicate(definition, state, rule.guard, event);
    const branch: RuntimeEffectBranch = guardPasses ? "effects" : "guardFalseEffects";
    const effects = rule[branch];
    if (!guardPasses) {
      outcome = "guard_false";
    }
    const effectResult = applyRuleEffects(
      definition,
      state,
      event,
      eventIndex,
      branch,
      effects,
      allocations,
      effectTraces,
    );
    state = effectResult.state;
    if (effectResult.outcome === "validation_failed") {
      outcome = "validation_failed";
    }
    if (effectResult.stop) {
      break;
    }
  }

  return {
    state: { ...state, sequenceNo: baseState.sequenceNo + 1 },
    outcome,
    matchedRuleIds,
    effectTraces,
  };
}

const runtimeMachine = setup({
  types: {
    context: {} as RuntimeMachineContext,
    events: {} as RuntimeMachineEvent,
    input: {} as RuntimeMachineInput,
  },
  actions: {
    applyRuntimeEventBatch: assign(({ context, event }) => {
      const reduction = reduceEventBatch(
        context.definition,
        context.state,
        event.batch,
        event.allocations,
      );
      return { ...context, state: reduction.state, reduction };
    }),
  },
}).createMachine({
  id: "prototype-runtime",
  initial: "ready",
  context: ({ input }) => ({ ...input, reduction: null }),
  states: {
    ready: {
      on: {
        "runtime.eventBatch": {
          actions: "applyRuntimeEventBatch",
        },
      },
    },
  },
});

async function prepareRuntimeAllocations(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  batch: RuntimeEventBatch,
): Promise<RuntimeAllocation[]> {
  const pending: Array<Promise<RuntimeAllocation>> = [];
  for (const [eventIndex, event] of batch.events.entries()) {
    const rule = findRuleForEvent(definition, event);
    if (rule === null) {
      continue;
    }
    const branches: RuntimeEffectBranch[] = ["effects", "guardFalseEffects"];
    for (const branch of branches) {
      for (const [effectIndex, effect] of rule[branch].entries()) {
        if (effect.kind !== "createEntity") {
          continue;
        }
        const key = `${eventIndex}:${branch}:${effectIndex}`;
        const name = `${state.sessionId}:${state.sequenceNo + 1}:${key}`;
        pending.push(
          deterministicUuidV5(RUNTIME_ENTITY_NAMESPACE, name).then((entityId) => ({
            key,
            entityId,
          })),
        );
      }
    }
  }
  return Promise.all(pending);
}

function compareRuntimeValues(left: RuntimeValue, right: RuntimeValue): number {
  if (left.type !== right.type) {
    return left.type < right.type ? -1 : 1;
  }
  switch (left.type) {
    case "null":
      return 0;
    case "boolean": {
      if (right.type !== "boolean" || left.value === right.value) return 0;
      return left.value ? 1 : -1;
    }
    case "integer": {
      if (right.type !== "integer" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "string": {
      if (right.type !== "string" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "enum": {
      if (right.type !== "enum" || left.value === right.value) return 0;
      return left.value < right.value ? -1 : 1;
    }
    case "entityRef": {
      if (right.type !== "entityRef") return 0;
      const leftKey = `${left.schemaId}:${left.entityId}`;
      const rightKey = `${right.schemaId}:${right.entityId}`;
      if (leftKey === rightKey) return 0;
      return leftKey < rightKey ? -1 : 1;
    }
  }
}

export function deriveRuntimeViewModel(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
): RuntimeViewModel {
  const byNode = new Map<string, RuntimeViewProperty[]>();
  const placeholderEvent: RuntimeEvent = {
    kind: "switchSimulatedRole",
    roleId: state.actorRoleId,
  };

  for (const binding of definition.viewBindings) {
    const existing = byNode.get(binding.nodeId) ?? [];
    let property: RuntimeViewProperty;
    switch (binding.target) {
      case "textContent":
        property = {
          target: "textContent",
          value: evaluateValueExpression(state, binding.value, placeholderEvent),
        };
        break;
      case "visibility":
        property = {
          target: "visibility",
          value: {
            type: "boolean",
            value: evaluatePredicate(definition, state, binding.predicate, placeholderEvent),
          },
        };
        break;
      case "tableRows": {
        const set = requireEntitySet(state, binding.schemaId);
        const rows = set.entities.map(cloneEntity);
        const sortFieldId = binding.sortFieldId;
        if (sortFieldId !== null) {
          rows.sort((left, right) => {
            const compared = compareRuntimeValues(
              requireFieldValue(left.fields, sortFieldId),
              requireFieldValue(right.fields, sortFieldId),
            );
            return binding.sortDirection === "asc" ? compared : -compared;
          });
        }
        property = { target: "tableRows", rows };
        break;
      }
    }
    byNode.set(binding.nodeId, [...existing, property]);
  }

  const nodes: RuntimeNodeViewModel[] = Array.from(byNode, ([nodeId, properties]) => ({
    nodeId,
    properties: [...properties].sort((left, right) => {
      if (left.target === right.target) return 0;
      return left.target < right.target ? -1 : 1;
    }),
  })).sort((left, right) => {
    if (left.nodeId === right.nodeId) return 0;
    return left.nodeId < right.nodeId ? -1 : 1;
  });
  return { nodes };
}

export async function applyRuntimeEventBatch(
  definition: RuntimeDefinition,
  state: PrototypeRuntimeState,
  batch: RuntimeEventBatch,
): Promise<RuntimeTransitionResult> {
  const definitionErrors = validateRuntimeDefinition(definition);
  if (definitionErrors.length > 0) {
    throw new RuntimeCoreError("runtime_definition_invalid", definitionErrors.join("; "));
  }
  const stateErrors = validateRuntimeState(definition, state);
  if (stateErrors.length > 0) {
    throw new RuntimeCoreError("runtime_state_invalid", stateErrors.join("; "));
  }
  if (batch.expectedSequenceNo !== state.sequenceNo) {
    throw new RuntimeCoreError(
      "runtime_sequence_conflict",
      `Expected runtime sequence ${batch.expectedSequenceNo}, current is ${state.sequenceNo}`,
    );
  }
  if (batch.events.length === 0 || batch.events.length > 20) {
    throw new RuntimeCoreError(
      "runtime_event_batch_size_invalid",
      "Runtime event batch must contain between 1 and 20 events",
    );
  }
  const baseStateHash = await hashRuntimeValue(state);
  const allocations = await prepareRuntimeAllocations(definition, state, batch);
  const actor = createActor(runtimeMachine, { input: { definition, state } });
  let transitionError: unknown;
  let transitionFailed = false;
  const subscription = actor.subscribe({
    error: (error) => {
      transitionFailed = true;
      transitionError = error;
    },
  });
  actor.start();
  actor.send({ type: "runtime.eventBatch", batch, allocations });
  const reduction = actor.getSnapshot().context.reduction;
  subscription.unsubscribe();
  actor.stop();
  if (transitionFailed) {
    throw transitionError;
  }
  if (reduction === null) {
    throw new RuntimeCoreError(
      "runtime_transition_missing",
      "XState runtime transition produced no reduction",
    );
  }
  const viewModel = deriveRuntimeViewModel(definition, reduction.state);
  const [resultStateHash, resultViewModelHash, effects] = await Promise.all([
    hashRuntimeValue(reduction.state),
    hashRuntimeValue(viewModel),
    Promise.all(
      reduction.effectTraces.map(async (trace) => ({
        eventIndex: trace.eventIndex,
        effectIndex: trace.effectIndex,
        effectKind: trace.effectKind,
        beforeStateHash: await hashRuntimeValue(trace.beforeState),
        afterStateHash: await hashRuntimeValue(trace.afterState),
      })),
    ),
  ]);

  return {
    state: reduction.state,
    viewModel,
    report: {
      clientEventId: batch.clientEventId,
      baseSequenceNo: state.sequenceNo,
      resultSequenceNo: reduction.state.sequenceNo,
      outcome: reduction.outcome,
      matchedRuleIds: reduction.matchedRuleIds,
      baseStateHash,
      resultStateHash,
      resultViewModelHash,
      effects,
    },
  };
}
