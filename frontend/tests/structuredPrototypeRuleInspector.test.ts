import assert from "node:assert/strict";
import test from "node:test";

import {
  addBehaviorRuleBatch,
  removeBehaviorRuleBatch,
  replaceBehaviorRuleBatch,
} from "../src/features/prototype/structured/structuredPrototypeCommands";
import {
  buildStructuredPrototypeRuleDefinition,
  createStructuredPrototypeRuleEffect,
  createStructuredPrototypeRuleDraft,
  createStructuredPrototypeRuleExpression,
  createStructuredPrototypeRuleRuntimeValue,
  isStructuredPrototypeRuleTriggerEligible,
  moveStructuredPrototypeRuleEffect,
  structuredPrototypeCreateEntitySchemaOptions,
  structuredPrototypeRuleInspectorStateKey,
  structuredPrototypeRuleTriggerCandidates,
  validateStructuredPrototypeRuleDraft,
} from "../src/features/prototype/structured/structuredPrototypeRuleDraft";
import type { StructuredPrototypeDocument } from "../src/features/prototype/structured/types";
import {
  createProcurementPrototypeDocument,
  STRUCTURED_PROCUREMENT_IDS,
} from "./fixtures/procurementDocumentFixture";

const FIXTURE_IDS = {
  requestEntity: "11111111-1111-4111-8111-111111111111",
  otherSchema: "22222222-2222-4222-8222-222222222222",
  otherEntity: "33333333-3333-4333-8333-333333333333",
  otherVariable: "44444444-4444-4444-8444-444444444444",
  relatedEntityField: "55555555-5555-4555-8555-555555555555",
} as const;

function ruleDocument(): StructuredPrototypeDocument {
  return {
    ...createProcurementPrototypeDocument(),
    id: "00000000-0000-4000-8000-000000000100",
  };
}

function documentWithEntityFixtures(): StructuredPrototypeDocument {
  const document = structuredClone(ruleDocument());
  const requestSchema = document.runtime.entitySchemas[0];
  const scenario = document.runtime.scenarios[0];
  assert.ok(requestSchema);
  assert.ok(scenario);
  scenario.entityFixtures = [
    {
      schemaId: requestSchema.id,
      entities: [
        {
          id: FIXTURE_IDS.requestEntity,
          schemaId: requestSchema.id,
          fields: [],
        },
      ],
    },
  ];
  return document;
}

function ruleDefinitionFor(document: StructuredPrototypeDocument, ruleId: string) {
  const rule = document.runtime.rules.find((candidate) => candidate.id === ruleId);
  assert.ok(rule);
  const definition = buildStructuredPrototypeRuleDefinition(rule);
  assert.ok(definition);
  return { rule, definition };
}

function entityRefSetVariableDefinition(
  document: StructuredPrototypeDocument,
  value:
    | { kind: "literal"; value: { type: "entityRef"; schemaId: string; entityId: string } }
    | { kind: "variable"; variableId: string }
    | { kind: "formField"; formId: string; fieldId: string }
    | { kind: "eventEntityRef" }
    | {
        kind: "entityField";
        entityRef: { kind: "variable"; variableId: string };
        fieldId: string;
        fallback: { type: "entityRef"; schemaId: string; entityId: string };
      },
) {
  const { rule, definition } = ruleDefinitionFor(document, STRUCTURED_PROCUREMENT_IDS.rules.select);
  return {
    rule,
    definition: {
      ...definition,
      effects: [
        {
          kind: "setVariable" as const,
          variableId: STRUCTURED_PROCUREMENT_IDS.variables.selectedRequest,
          value,
        },
      ],
    },
  };
}

test("rule trigger candidates only expose interactions the current renderer can emit", () => {
  const document = ruleDocument();
  const createCandidates = structuredPrototypeRuleTriggerCandidates(
    document,
    STRUCTURED_PROCUREMENT_IDS.pages.create,
  );
  assert.deepEqual(
    createCandidates.map(({ nodeId, event }) => [nodeId, event]),
    [
      [STRUCTURED_PROCUREMENT_IDS.nodes.submitRequest, "submit"],
      [STRUCTURED_PROCUREMENT_IDS.nodes.submitRequest, "click"],
    ],
  );
  assert.equal(
    isStructuredPrototypeRuleTriggerEligible(document, {
      kind: "nodeEvent",
      nodeId: STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
      event: "rowActivated",
    }),
    true,
  );
  assert.equal(
    isStructuredPrototypeRuleTriggerEligible(document, {
      kind: "nodeEvent",
      nodeId: STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
      event: "click",
    }),
    false,
  );
  const withoutTableBinding = structuredClone(document);
  withoutTableBinding.runtime.viewBindings = withoutTableBinding.runtime.viewBindings.filter(
    (binding) => binding.target !== "tableRows",
  );
  assert.equal(
    isStructuredPrototypeRuleTriggerEligible(withoutTableBinding, {
      kind: "nodeEvent",
      nodeId: STRUCTURED_PROCUREMENT_IDS.nodes.requestTable,
      event: "rowActivated",
    }),
    false,
  );
});

test("existing rules round-trip without simplifying nested guards or either effect list", () => {
  const document = ruleDocument();
  for (const existing of document.runtime.rules) {
    const draft = createStructuredPrototypeRuleDraft(document, {
      kind: "existingRule",
      rule: existing,
    });
    assert.ok(draft);
    const definition = buildStructuredPrototypeRuleDefinition(draft);
    assert.ok(definition);
    assert.deepEqual(definition, {
      key: existing.key,
      enabled: existing.enabled,
      trigger: existing.trigger,
      guard: existing.guard,
      effects: existing.effects,
      guardFalseEffects: existing.guardFalseEffects,
    });
    assert.notEqual(definition, draft);
    assert.notEqual(definition.effects, existing.effects);
  }
});

test("a pending page connection requires an explicit trigger and only defaults its navigate effect", () => {
  const document = ruleDocument();
  const draft = createStructuredPrototypeRuleDraft(document, {
    kind: "pendingConnection",
    sourcePageId: STRUCTURED_PROCUREMENT_IDS.pages.create,
    targetPageId: STRUCTURED_PROCUREMENT_IDS.pages.detail,
  });
  assert.ok(draft);
  assert.equal(draft.key, "flow-purchase-create-to-purchase-detail");
  assert.equal(draft.trigger, null);
  assert.deepEqual(draft.effects, [
    { kind: "navigate", targetPageId: STRUCTURED_PROCUREMENT_IDS.pages.detail },
  ]);
  assert.deepEqual(draft.guardFalseEffects, []);
  assert.deepEqual(validateStructuredPrototypeRuleDraft(document, draft, null), [
    { code: "trigger_required", path: "trigger" },
  ]);
  assert.equal(buildStructuredPrototypeRuleDefinition(draft), null);
});

test("effect moves preserve exact order across multiple navigate and non-navigate effects", () => {
  const effects = [
    { kind: "navigate", targetPageId: "page-a" },
    { kind: "notify", level: "info", message: "first" },
    { kind: "navigate", targetPageId: "page-b" },
  ] as const;
  assert.deepEqual(
    moveStructuredPrototypeRuleEffect(effects, 2, 0).map((effect) => effect.kind),
    ["navigate", "navigate", "notify"],
  );
  assert.deepEqual(moveStructuredPrototypeRuleEffect(effects, -1, 0), effects);
});

test("rule validation reports invalid document references and row-only event expressions", () => {
  const document = ruleDocument();
  const existing = document.runtime.rules.find(
    (rule) => rule.id === STRUCTURED_PROCUREMENT_IDS.rules.approve,
  );
  assert.ok(existing);
  const draft = buildStructuredPrototypeRuleDefinition({
    ...existing,
    key: "edited-approval",
    trigger: {
      kind: "nodeEvent",
      nodeId: STRUCTURED_PROCUREMENT_IDS.nodes.approveRequest,
      event: "click",
    },
    guard: { kind: "roleIs", roleId: "missing-role" },
    effects: [
      {
        kind: "setVariable",
        variableId: STRUCTURED_PROCUREMENT_IDS.variables.selectedRequest,
        value: { kind: "eventEntityRef" },
      },
      { kind: "navigate", targetPageId: "missing-page" },
    ],
  });
  assert.ok(draft);
  const issues = validateStructuredPrototypeRuleDraft(document, draft, existing.id);
  assert.deepEqual(
    issues.map(({ code, path }) => [code, path]),
    [
      ["unknown_role", "guard.roleId"],
      ["event_context_unavailable", "effects[0].value"],
      ["unknown_page", "effects[1].targetPageId"],
    ],
  );
});

test("runtime literal validation rejects invalid enum and oversized string values", () => {
  const document = ruleDocument();
  const { rule, definition } = ruleDefinitionFor(
    document,
    STRUCTURED_PROCUREMENT_IDS.rules.approve,
  );
  const invalidEnumEffect = {
    kind: "updateEntity" as const,
    schemaId: STRUCTURED_PROCUREMENT_IDS.schema.request,
    entityRef: {
      kind: "variable" as const,
      variableId: STRUCTURED_PROCUREMENT_IDS.variables.selectedRequest,
    },
    updates: [
      {
        fieldId: STRUCTURED_PROCUREMENT_IDS.schema.status,
        value: {
          kind: "literal" as const,
          value: { type: "enum" as const, value: "value\n" },
        },
      },
    ],
  };
  const invalidEnum = { ...definition, effects: [invalidEnumEffect] };
  const enumIssues = validateStructuredPrototypeRuleDraft(document, invalidEnum, rule.id);
  assert.ok(enumIssues.some((issue) => issue.code === "invalid_enum_value"));
  const emptyEnum = {
    ...definition,
    effects: [
      {
        ...invalidEnumEffect,
        updates: [
          {
            fieldId: STRUCTURED_PROCUREMENT_IDS.schema.status,
            value: { kind: "literal" as const, value: { type: "enum" as const, value: "" } },
          },
        ],
      },
    ],
  };
  assert.ok(
    validateStructuredPrototypeRuleDraft(document, emptyEnum, rule.id).some(
      (issue) => issue.code === "invalid_enum_value",
    ),
  );

  const invalidString = {
    ...definition,
    guard: {
      kind: "compare" as const,
      operator: "eq" as const,
      left: {
        kind: "literal" as const,
        value: { type: "string" as const, value: "x".repeat(8_001) },
      },
      right: { kind: "literal" as const, value: { type: "string" as const, value: "ok" } },
    },
  };
  const stringIssues = validateStructuredPrototypeRuleDraft(document, invalidString, rule.id);
  assert.ok(stringIssues.some((issue) => issue.code === "runtime_string_too_long"));
});

test("entityRef literal factories require a schema fixture and never create empty IDs", () => {
  const emptyDocument = ruleDocument();
  const trigger = emptyDocument.runtime.rules[1]?.trigger;
  assert.ok(trigger);
  assert.equal(createStructuredPrototypeRuleRuntimeValue(emptyDocument, "entityRef"), null);
  assert.equal(
    createStructuredPrototypeRuleExpression(emptyDocument, trigger, "literal", "entityRef"),
    null,
  );

  const document = documentWithEntityFixtures();
  assert.deepEqual(createStructuredPrototypeRuleRuntimeValue(document, "entityRef"), {
    type: "entityRef",
    schemaId: STRUCTURED_PROCUREMENT_IDS.schema.request,
    entityId: FIXTURE_IDS.requestEntity,
  });
});

test("entityRef literal validation rejects invalid UUIDs, missing fixtures, and wrong schemas", () => {
  const noFixtureDocument = ruleDocument();
  const noFixture = entityRefSetVariableDefinition(noFixtureDocument, {
    kind: "literal",
    value: {
      type: "entityRef",
      schemaId: STRUCTURED_PROCUREMENT_IDS.schema.request,
      entityId: FIXTURE_IDS.requestEntity,
    },
  });
  const noFixtureIssues = validateStructuredPrototypeRuleDraft(
    noFixtureDocument,
    noFixture.definition,
    noFixture.rule.id,
  );
  assert.ok(noFixtureIssues.some((issue) => issue.code === "entity_fixture_missing"));

  const invalidIds = entityRefSetVariableDefinition(noFixtureDocument, {
    kind: "literal",
    value: { type: "entityRef", schemaId: "not-a-uuid", entityId: "also-not-a-uuid" },
  });
  const invalidIdIssues = validateStructuredPrototypeRuleDraft(
    noFixtureDocument,
    invalidIds.definition,
    invalidIds.rule.id,
  );
  assert.deepEqual(
    invalidIdIssues
      .filter((issue) => issue.code === "invalid_entity_id")
      .map((issue) => issue.path),
    ["effects[0].value.value.schemaId", "effects[0].value.value.entityId"],
  );

  const document = documentWithEntityFixtures();
  const scenario = document.runtime.scenarios[0];
  assert.ok(scenario);
  document.runtime.entitySchemas.push({
    id: FIXTURE_IDS.otherSchema,
    key: "other-record",
    fields: [],
  });
  scenario.entityFixtures.push({
    schemaId: FIXTURE_IDS.otherSchema,
    entities: [{ id: FIXTURE_IDS.otherEntity, schemaId: FIXTURE_IDS.otherSchema, fields: [] }],
  });
  const wrongSchema = entityRefSetVariableDefinition(document, {
    kind: "literal",
    value: {
      type: "entityRef",
      schemaId: FIXTURE_IDS.otherSchema,
      entityId: FIXTURE_IDS.otherEntity,
    },
  });
  const wrongSchemaIssues = validateStructuredPrototypeRuleDraft(
    document,
    wrongSchema.definition,
    wrongSchema.rule.id,
  );
  assert.ok(wrongSchemaIssues.some((issue) => issue.code === "entity_schema_mismatch"));

  const correctSchema = entityRefSetVariableDefinition(document, {
    kind: "literal",
    value: {
      type: "entityRef",
      schemaId: STRUCTURED_PROCUREMENT_IDS.schema.request,
      entityId: FIXTURE_IDS.requestEntity,
    },
  });
  assert.deepEqual(
    validateStructuredPrototypeRuleDraft(document, correctSchema.definition, correctSchema.rule.id),
    [],
  );
});

test("setVariable validates entityRef schema identity for variable, event, and entity-field expressions", () => {
  const document = documentWithEntityFixtures();
  const scenario = document.runtime.scenarios[0];
  const requestSchema = document.runtime.entitySchemas[0];
  assert.ok(scenario);
  assert.ok(requestSchema);
  document.runtime.entitySchemas.push({
    id: FIXTURE_IDS.otherSchema,
    key: "other-record",
    fields: [],
  });
  document.runtime.variables.push({
    id: FIXTURE_IDS.otherVariable,
    key: "other-record-ref",
    valueType: "entityRef",
    nullable: true,
    entitySchemaId: FIXTURE_IDS.otherSchema,
    defaultValue: { type: "null" },
  });
  scenario.entityFixtures.push({
    schemaId: FIXTURE_IDS.otherSchema,
    entities: [{ id: FIXTURE_IDS.otherEntity, schemaId: FIXTURE_IDS.otherSchema, fields: [] }],
  });
  requestSchema.fields.push({
    id: FIXTURE_IDS.relatedEntityField,
    key: "related-record",
    valueType: "entityRef",
    nullable: true,
  });

  const variableExpression = entityRefSetVariableDefinition(document, {
    kind: "variable",
    variableId: FIXTURE_IDS.otherVariable,
  });
  assert.ok(
    validateStructuredPrototypeRuleDraft(
      document,
      variableExpression.definition,
      variableExpression.rule.id,
    ).some((issue) => issue.code === "entity_schema_mismatch"),
  );

  const formExpression = entityRefSetVariableDefinition(document, {
    kind: "formField",
    formId: STRUCTURED_PROCUREMENT_IDS.form.create,
    fieldId: STRUCTURED_PROCUREMENT_IDS.form.title,
  });
  assert.ok(
    validateStructuredPrototypeRuleDraft(
      document,
      formExpression.definition,
      formExpression.rule.id,
    ).some((issue) => issue.code === "expression_type_mismatch"),
  );

  const eventExpression = entityRefSetVariableDefinition(document, { kind: "eventEntityRef" });
  assert.deepEqual(
    validateStructuredPrototypeRuleDraft(
      document,
      eventExpression.definition,
      eventExpression.rule.id,
    ),
    [],
  );

  const entityFieldExpression = entityRefSetVariableDefinition(document, {
    kind: "entityField",
    entityRef: {
      kind: "variable",
      variableId: STRUCTURED_PROCUREMENT_IDS.variables.selectedRequest,
    },
    fieldId: FIXTURE_IDS.relatedEntityField,
    fallback: {
      type: "entityRef",
      schemaId: FIXTURE_IDS.otherSchema,
      entityId: FIXTURE_IDS.otherEntity,
    },
  });
  assert.ok(
    validateStructuredPrototypeRuleDraft(
      document,
      entityFieldExpression.definition,
      entityFieldExpression.rule.id,
    ).some((issue) => issue.code === "entity_schema_mismatch"),
  );
});

test("createEntity options only expose schemas with a matching entityRef result variable", () => {
  const document = ruleDocument();
  document.runtime.entitySchemas.push({
    id: FIXTURE_IDS.otherSchema,
    key: "orphan-record",
    fields: [],
  });
  assert.deepEqual(
    structuredPrototypeCreateEntitySchemaOptions(document).map((schema) => schema.id),
    [STRUCTURED_PROCUREMENT_IDS.schema.request],
  );
  const trigger = document.runtime.rules[0]?.trigger;
  assert.ok(trigger);
  assert.deepEqual(createStructuredPrototypeRuleEffect(document, trigger, "createEntity"), {
    kind: "createEntity",
    schemaId: STRUCTURED_PROCUREMENT_IDS.schema.request,
    resultVariableId: STRUCTURED_PROCUREMENT_IDS.variables.selectedRequest,
    values: [],
  });
});

test("pending inspector state identity stays stable across document rule changes", () => {
  const pending = {
    kind: "pendingConnection" as const,
    sourcePageId: STRUCTURED_PROCUREMENT_IDS.pages.create,
    targetPageId: STRUCTURED_PROCUREMENT_IDS.pages.detail,
  };
  assert.equal(
    structuredPrototypeRuleInspectorStateKey(pending),
    `${pending.sourcePageId}:${pending.targetPageId}`,
  );
  const document = ruleDocument();
  const existing = document.runtime.rules[0];
  assert.ok(existing);
  assert.notEqual(
    structuredPrototypeRuleInspectorStateKey({ kind: "existingRule", rule: existing }),
    structuredPrototypeRuleInspectorStateKey({
      kind: "existingRule",
      rule: { ...existing, key: "changed-rule" },
    }),
  );
});

test("behavior rule command builders emit the exact executable command shapes", () => {
  const document = ruleDocument();
  const rule = document.runtime.rules[0];
  assert.ok(rule);
  const definition = buildStructuredPrototypeRuleDefinition(rule);
  assert.ok(definition);
  assert.deepEqual(addBehaviorRuleBatch(definition.key, definition), {
    commandContractVersion: 1,
    summary: "Add behavior rule",
    commands: [
      {
        kind: "addBehaviorRule",
        newRuleKey: definition.key,
        definition,
      },
    ],
  });
  assert.deepEqual(replaceBehaviorRuleBatch(rule.id, definition), {
    commandContractVersion: 1,
    summary: "Replace behavior rule",
    commands: [{ kind: "replaceBehaviorRule", ruleId: rule.id, definition }],
  });
  assert.deepEqual(removeBehaviorRuleBatch(rule.id), {
    commandContractVersion: 1,
    summary: "Remove behavior rule",
    commands: [{ kind: "removeBehaviorRule", ruleId: rule.id }],
  });
  assert.throws(() => addBehaviorRuleBatch("different-key", definition), /newRuleKey must match/);
});
