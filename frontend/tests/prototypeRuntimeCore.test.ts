import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canonicalRuntimeJson,
  hashRuntimeValue,
} from "../src/features/prototype/runtime/canonical";
import {
  PROCUREMENT_IDS,
  PROCUREMENT_RUNTIME_DEFINITION,
  procurementApprovalEventBatches,
  runProcurementApprovalScenario,
  selectedRequestRef,
} from "./fixtures/procurementRuntimeFixture";
import {
  applyRuntimeEventBatch,
  createInitialRuntimeState,
  deriveRuntimeViewModel,
  RUNTIME_CORE_VERSION,
  RuntimeCoreError,
  validateRuntimeDefinition,
  validateRuntimeState,
  XSTATE_KERNEL_VERSION,
} from "../src/features/prototype/runtime/runtimeCore";
import {
  parsePrototypeRuntimeState,
  parsePrototypeRuntimeStateJson,
  parseRuntimeViewModelJson,
  RuntimeStateCodecError,
  serializePrototypeRuntimeState,
} from "../src/features/prototype/runtime/runtimeStateCodec";
import type {
  PrototypeRuntimeState,
  RuntimeDefinition,
  RuntimeEntity,
  RuntimeEventBatch,
  RuntimeTransitionResult,
  RuntimeValue,
  RuntimeViewModel,
} from "../src/features/prototype/runtime/types";

function initialState(sessionId = "runtime-test-session"): PrototypeRuntimeState {
  return createInitialRuntimeState(
    PROCUREMENT_RUNTIME_DEFINITION,
    PROCUREMENT_IDS.scenarios.happyPath,
    sessionId,
  );
}

function requireBatch(batches: RuntimeEventBatch[], index: number): RuntimeEventBatch {
  const batch = batches[index];
  assert.ok(batch, `event batch ${index} must exist`);
  return batch;
}

function requireResult(results: RuntimeTransitionResult[], index: number): RuntimeTransitionResult {
  const result = results[index];
  assert.ok(result, `transition result ${index} must exist`);
  return result;
}

describe("flow layout runtime isolation", () => {
  it("preserves initial runtime state and view-model hashes", async () => {
    const sessionId = "flow-layout-runtime-isolation";
    const baselineState = createInitialRuntimeState(
      PROCUREMENT_RUNTIME_DEFINITION,
      PROCUREMENT_IDS.scenarios.happyPath,
      sessionId,
    );
    const definitionWithLayout: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      flowLayout: {
        nodes: [{ nodeId: PROCUREMENT_IDS.pages.create, x: 420, y: -120 }],
      },
    };
    const layoutState = createInitialRuntimeState(
      definitionWithLayout,
      PROCUREMENT_IDS.scenarios.happyPath,
      sessionId,
    );

    assert.equal(await hashRuntimeValue(layoutState), await hashRuntimeValue(baselineState));
    assert.equal(
      await hashRuntimeValue(deriveRuntimeViewModel(definitionWithLayout, layoutState)),
      await hashRuntimeValue(deriveRuntimeViewModel(PROCUREMENT_RUNTIME_DEFINITION, baselineState)),
    );
  });
});

function requireEntity(state: PrototypeRuntimeState): RuntimeEntity {
  const set = state.entitySets.find(
    (candidate) => candidate.schemaId === PROCUREMENT_IDS.schema.request,
  );
  assert.ok(set, "purchase request entity set must exist");
  const entity = set.entities[0];
  assert.ok(entity, "purchase request entity must exist");
  return entity;
}

function requireEntityField(entity: RuntimeEntity, fieldId: string): RuntimeValue {
  const field = entity.fields.find((candidate) => candidate.fieldId === fieldId);
  assert.ok(field, `entity field ${fieldId} must exist`);
  return field.value;
}

function requireVisibility(viewModel: RuntimeViewModel, nodeId: string): boolean {
  const node = viewModel.nodes.find((candidate) => candidate.nodeId === nodeId);
  assert.ok(node, `view node ${nodeId} must exist`);
  const property = node.properties.find((candidate) => candidate.target === "visibility");
  assert.ok(property?.target === "visibility", `node ${nodeId} must have visibility`);
  return property.value.value;
}

function requireTextValue(viewModel: RuntimeViewModel, nodeId: string): RuntimeValue {
  const node = viewModel.nodes.find((candidate) => candidate.nodeId === nodeId);
  assert.ok(node, `view node ${nodeId} must exist`);
  const property = node.properties.find((candidate) => candidate.target === "textContent");
  assert.ok(property?.target === "textContent", `node ${nodeId} must have textContent`);
  return property.value;
}

function requireFirstTableRow(viewModel: RuntimeViewModel, nodeId: string): RuntimeEntity {
  const node = viewModel.nodes.find((candidate) => candidate.nodeId === nodeId);
  assert.ok(node, `view node ${nodeId} must exist`);
  const property = node.properties.find((candidate) => candidate.target === "tableRows");
  assert.ok(property?.target === "tableRows", `node ${nodeId} must have tableRows`);
  const row = property.rows[0];
  assert.ok(row, `node ${nodeId} must have a row`);
  return row;
}

async function submitValidRequest(sessionId: string): Promise<RuntimeTransitionResult> {
  const submit = requireBatch(procurementApprovalEventBatches(), 0);
  return applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, initialState(sessionId), submit);
}

describe("prototype runtime core", () => {
  it("matches the Python canonical JSON compatibility fixture", async () => {
    const value = { z: 2, "😀": "emoji", "\ue000": "private", a: [true, null, "中文"] };
    assert.equal(
      canonicalRuntimeJson(value),
      '{"a":[true,null,"中文"],"z":2,"\ue000":"private","😀":"emoji"}',
    );
    assert.equal(
      await hashRuntimeValue(value),
      "sha256:13b8db984e15a32f530afbda948a2f354b9fb276e6e73c16c45e0427a26cbfd5",
    );
    assert.throws(() => canonicalRuntimeJson("\ud800"), /valid Unicode/u);
  });

  it("records form validation failure and does not create an entity", async () => {
    const result = await applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, initialState(), {
      clientEventId: "event-invalid-submit",
      expectedSequenceNo: 0,
      events: [
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.submitRequest,
          event: "submit",
        },
      ],
    });

    assert.equal(result.report.outcome, "validation_failed");
    assert.equal(result.state.sequenceNo, 1);
    assert.equal(result.state.entitySets[0]?.entities.length, 0);
    assert.deepEqual(result.state.formStates[0]?.errors, [
      { fieldId: PROCUREMENT_IDS.fields.title, code: "required" },
      { fieldId: PROCUREMENT_IDS.fields.amount, code: "min_integer" },
    ]);
    assert.deepEqual(
      result.report.effects.map((effect) => effect.effectKind),
      ["validateForm"],
    );
    assert.equal(result.report.effects[0]?.eventIndex, 0);
  });

  it("creates a deterministic pending request and records the triggering event index", async () => {
    const [first, second] = await Promise.all([
      submitValidRequest("stable-runtime-session"),
      submitValidRequest("stable-runtime-session"),
    ]);
    const firstRef = selectedRequestRef(first.state);
    const secondRef = selectedRequestRef(second.state);
    assert.ok(firstRef);
    assert.ok(secondRef);
    assert.equal(firstRef.entityId, secondRef.entityId);
    assert.match(
      firstRef.entityId,
      /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u,
    );
    assert.deepEqual(
      requireEntityField(requireEntity(first.state), PROCUREMENT_IDS.fields.status),
      {
        type: "enum",
        value: "pending",
      },
    );
    assert.deepEqual(
      first.report.effects.map((effect) => effect.eventIndex),
      [2, 2, 2, 2],
    );
  });

  it("applies click and submit rules from one field-flushed Button batch in event order", async () => {
    const definition: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      rules: [
        {
          id: "rule-click-before-submit",
          key: "click-before-submit",
          enabled: true,
          trigger: {
            kind: "nodeEvent",
            nodeId: PROCUREMENT_IDS.nodes.submitRequest,
            event: "click",
          },
          guard: null,
          effects: [{ kind: "notify", level: "info", message: "click received" }],
          guardFalseEffects: [],
        },
        ...PROCUREMENT_RUNTIME_DEFINITION.rules,
      ],
    };
    const baseEvents = requireBatch(procurementApprovalEventBatches(), 0).events;
    const firstField = baseEvents[0];
    const secondField = baseEvents[1];
    assert.ok(firstField?.kind === "fieldValueCommitted");
    assert.ok(secondField?.kind === "fieldValueCommitted");

    const result = await applyRuntimeEventBatch(definition, initialState("multi-event-session"), {
      clientEventId: "event-click-and-submit",
      expectedSequenceNo: 0,
      events: [
        firstField,
        secondField,
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.submitRequest,
          event: "click",
        },
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.submitRequest,
          event: "submit",
        },
      ],
    });

    assert.equal(result.report.effects[0]?.effectKind, "notify");
    assert.equal(result.report.effects[0]?.eventIndex, 2);
    assert.ok(result.report.effects.slice(1).every((effect) => effect.eventIndex === 3));
    assert.equal(result.state.entitySets[0]?.entities.length, 1);
  });

  it("shows the approve action only after switching to the manager role", async () => {
    const submitted = await submitValidRequest("role-switch-session");
    assert.equal(
      requireVisibility(
        deriveRuntimeViewModel(PROCUREMENT_RUNTIME_DEFINITION, submitted.state),
        PROCUREMENT_IDS.nodes.approveRequest,
      ),
      false,
    );
    const roleSwitch = requireBatch(procurementApprovalEventBatches(), 1);
    const switched = await applyRuntimeEventBatch(
      PROCUREMENT_RUNTIME_DEFINITION,
      submitted.state,
      roleSwitch,
    );
    assert.equal(switched.state.actorRoleId, PROCUREMENT_IDS.roles.manager);
    assert.equal(requireVisibility(switched.viewModel, PROCUREMENT_IDS.nodes.approveRequest), true);
  });

  it("synchronizes approved status across canonical entity, table, and detail bindings", async () => {
    const results = await runProcurementApprovalScenario("approval-session", false);
    const approved = requireResult(results, 2);

    assert.equal(approved.report.outcome, "applied");
    assert.deepEqual(
      requireEntityField(requireEntity(approved.state), PROCUREMENT_IDS.fields.status),
      { type: "enum", value: "approved" },
    );
    assert.deepEqual(
      requireEntityField(
        requireFirstTableRow(approved.viewModel, PROCUREMENT_IDS.nodes.requestTable),
        PROCUREMENT_IDS.fields.status,
      ),
      { type: "enum", value: "approved" },
    );
    assert.deepEqual(requireTextValue(approved.viewModel, PROCUREMENT_IDS.nodes.detailStatus), {
      type: "enum",
      value: "approved",
    });
  });

  it("produces identical hashes after every validated JSON state round trip", async () => {
    const [inMemory, roundTripped] = await Promise.all([
      runProcurementApprovalScenario("replay-session", false),
      runProcurementApprovalScenario("replay-session", true),
    ]);

    assert.deepEqual(
      roundTripped.map((result) => ({
        state: result.report.resultStateHash,
        view: result.report.resultViewModelHash,
      })),
      inMemory.map((result) => ({
        state: result.report.resultStateHash,
        view: result.report.resultViewModelHash,
      })),
    );
  });

  it("matches the pinned XState 5.32.4 compatibility fixture", async () => {
    const results = await runProcurementApprovalScenario("compatibility-runtime-session", true);

    assert.equal(RUNTIME_CORE_VERSION, "0.2.0-spike");
    assert.equal(XSTATE_KERNEL_VERSION, "5.32.4");
    assert.deepEqual(
      results.map((result) => ({
        stateHash: result.report.resultStateHash,
        viewModelHash: result.report.resultViewModelHash,
        entityId: selectedRequestRef(result.state)?.entityId ?? null,
      })),
      [
        {
          stateHash: "sha256:f7eb738c805681198cd30fb38584dc1e35f0ee3455b4e6e2f8211ff8d07c3e12",
          viewModelHash: "sha256:8a08372298a0bffdc8540c54e5f00f83baeda4e17f6c02337cf27cb478dfcb6c",
          entityId: "d1a600e6-855f-5ad0-8b8b-56e87a48de90",
        },
        {
          stateHash: "sha256:54313544292c2fa496a0877499337b4bd359680b1bc668320f6e001fa8462061",
          viewModelHash: "sha256:9bbcc45f6f923ece4e461f3ec96af5e6a6a9a4201a46e0d229effa8fc0d7fd43",
          entityId: "d1a600e6-855f-5ad0-8b8b-56e87a48de90",
        },
        {
          stateHash: "sha256:a2bbff2041ae041f31701277b637e21767b5b8a86c48fd645879934ad4c64e7f",
          viewModelHash: "sha256:83ad5001aa21d47d77b6e521263fd8754d040305dee8f89bfd20612b693e7646",
          entityId: "d1a600e6-855f-5ad0-8b8b-56e87a48de90",
        },
      ],
    );
  });

  it("refuses applicant approval through the rule guard without changing status", async () => {
    const submitted = await submitValidRequest("guard-session");
    const result = await applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, submitted.state, {
      clientEventId: "event-applicant-approve",
      expectedSequenceNo: 1,
      events: [
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.approveRequest,
          event: "click",
        },
      ],
    });

    assert.equal(result.report.outcome, "guard_false");
    assert.deepEqual(
      requireEntityField(requireEntity(result.state), PROCUREMENT_IDS.fields.status),
      { type: "enum", value: "pending" },
    );
    assert.deepEqual(
      result.report.effects.map((effect) => effect.effectKind),
      ["notify"],
    );
  });

  it("rejects a stale event batch sequence", async () => {
    const submitted = await submitValidRequest("sequence-session");
    const staleBatch = requireBatch(procurementApprovalEventBatches(), 1);
    await assert.rejects(
      () =>
        applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, submitted.state, {
          ...staleBatch,
          expectedSequenceNo: 0,
        }),
      (error: unknown) =>
        error instanceof RuntimeCoreError && error.code === "runtime_sequence_conflict",
    );
  });

  it("rejects state produced by a different runtime kernel before transition", async () => {
    const incompatibleState: PrototypeRuntimeState = {
      ...initialState("incompatible-kernel-session"),
      stateMachineKernelVersion: "5.31.0",
    };
    const submit = requireBatch(procurementApprovalEventBatches(), 0);

    await assert.rejects(
      () => applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, incompatibleState, submit),
      (error: unknown) =>
        error instanceof RuntimeCoreError &&
        error.code === "runtime_state_invalid" &&
        error.message.includes("state machine kernel version 5.31.0 does not match 5.32.4"),
    );
  });

  it("rejects event-scoped expressions in persistent view bindings", () => {
    const invalidDefinition: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      viewBindings: [
        ...PROCUREMENT_RUNTIME_DEFINITION.viewBindings,
        {
          id: "binding-invalid-event-ref",
          nodeId: "node-invalid-event-ref",
          target: "textContent",
          value: { kind: "eventEntityRef" },
        },
      ],
    };

    assert.deepEqual(validateRuntimeDefinition(invalidDefinition), [
      "view binding binding-invalid-event-ref cannot reference the current event entity",
    ]);
  });

  it("rejects duplicate view-binding targets for one runtime node", () => {
    const first = PROCUREMENT_RUNTIME_DEFINITION.viewBindings[0];
    assert.ok(first);
    const invalidDefinition: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      viewBindings: [
        ...PROCUREMENT_RUNTIME_DEFINITION.viewBindings,
        { ...first, id: "binding-duplicate-node-target" },
      ],
    };

    assert.ok(
      validateRuntimeDefinition(invalidDefinition).includes(
        `view binding node targets contains duplicate id ${first.nodeId}:${first.target}`,
      ),
    );
  });

  it("validates entity-reference variable schemas in definitions and replayed state", () => {
    const otherSchemaId = "schema-other";
    const definition: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      entitySchemas: [
        ...PROCUREMENT_RUNTIME_DEFINITION.entitySchemas,
        { id: otherSchemaId, key: "other", fields: [] },
      ],
      variables: PROCUREMENT_RUNTIME_DEFINITION.variables.map((variable) => ({
        ...variable,
        defaultValue: {
          type: "entityRef",
          schemaId: otherSchemaId,
          entityId: "other-default",
        },
      })),
      scenarios: PROCUREMENT_RUNTIME_DEFINITION.scenarios.map((scenario) => ({
        ...scenario,
        initialVariables: [
          {
            variableId: PROCUREMENT_IDS.variables.selectedRequest,
            value: { type: "entityRef", schemaId: otherSchemaId, entityId: "other-initial" },
          },
        ],
      })),
    };

    assert.deepEqual(validateRuntimeDefinition(definition), [
      `variable ${PROCUREMENT_IDS.variables.selectedRequest} default entity schema does not match its definition`,
      `scenario ${PROCUREMENT_IDS.scenarios.happyPath} variable ${PROCUREMENT_IDS.variables.selectedRequest} entity schema does not match its definition`,
    ]);

    const createMismatch: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      entitySchemas: [
        ...PROCUREMENT_RUNTIME_DEFINITION.entitySchemas,
        { id: otherSchemaId, key: "other", fields: [] },
      ],
      variables: PROCUREMENT_RUNTIME_DEFINITION.variables.map((variable) => ({
        ...variable,
        entitySchemaId: otherSchemaId,
      })),
    };
    assert.ok(
      validateRuntimeDefinition(createMismatch).includes(
        `rule ${PROCUREMENT_IDS.rules.submit} create-entity result variable does not match schema ${PROCUREMENT_IDS.schema.request}`,
      ),
    );

    const state = initialState("wrong-schema-replay");
    const wrongState: PrototypeRuntimeState = {
      ...state,
      variableValues: [
        {
          variableId: PROCUREMENT_IDS.variables.selectedRequest,
          value: { type: "entityRef", schemaId: otherSchemaId, entityId: "other-state" },
        },
      ],
    };
    assert.ok(
      validateRuntimeState(PROCUREMENT_RUNTIME_DEFINITION, wrongState).includes(
        `runtime variable ${PROCUREMENT_IDS.variables.selectedRequest} entity schema does not match its definition`,
      ),
    );
  });

  it("rejects an event entity from another schema before writing the variable", async () => {
    const otherSchemaId = "schema-other";
    const otherEntityId = "entity-other";
    const definition: RuntimeDefinition = {
      ...PROCUREMENT_RUNTIME_DEFINITION,
      entitySchemas: [
        ...PROCUREMENT_RUNTIME_DEFINITION.entitySchemas,
        { id: otherSchemaId, key: "other", fields: [] },
      ],
      viewBindings: PROCUREMENT_RUNTIME_DEFINITION.viewBindings.map((binding) =>
        binding.target === "tableRows"
          ? { ...binding, schemaId: otherSchemaId, sortFieldId: null }
          : binding,
      ),
      scenarios: PROCUREMENT_RUNTIME_DEFINITION.scenarios.map((scenario) => ({
        ...scenario,
        entityFixtures: [
          {
            schemaId: otherSchemaId,
            entities: [{ id: otherEntityId, schemaId: otherSchemaId, fields: [] }],
          },
        ],
      })),
    };
    const state = createInitialRuntimeState(
      definition,
      PROCUREMENT_IDS.scenarios.happyPath,
      "wrong-event-schema",
    );

    await assert.rejects(
      () =>
        applyRuntimeEventBatch(definition, state, {
          clientEventId: "wrong-event-schema",
          expectedSequenceNo: 0,
          events: [
            {
              kind: "tableRowActivated",
              nodeId: PROCUREMENT_IDS.nodes.requestTable,
              entityRef: {
                type: "entityRef",
                schemaId: otherSchemaId,
                entityId: otherEntityId,
              },
            },
          ],
        }),
      (error: unknown) =>
        error instanceof RuntimeCoreError &&
        error.code === "runtime_variable_entity_schema_mismatch",
    );
  });

  it("round-trips exact runtime state and rejects malformed or extended state", () => {
    const state = initialState("codec-session");
    const encoded = serializePrototypeRuntimeState(state);
    assert.deepEqual(parsePrototypeRuntimeStateJson(encoded), state);
    assert.throws(
      () => parsePrototypeRuntimeState({ ...state, unexpected: true }),
      (error: unknown) =>
        error instanceof RuntimeStateCodecError &&
        error.message === "runtimeState contains unknown field unexpected",
    );
    assert.throws(
      () => parsePrototypeRuntimeStateJson("{"),
      (error: unknown) => error instanceof RuntimeStateCodecError,
    );
  });

  it("validates runtime view model values before rendering", () => {
    const encoded = JSON.stringify({
      nodes: [
        {
          nodeId: "status",
          properties: [
            { target: "textContent", value: { type: "enum", value: "approved" } },
            { target: "visibility", value: { type: "boolean", value: true } },
          ],
        },
      ],
    });
    assert.deepEqual(parseRuntimeViewModelJson(encoded), {
      nodes: [
        {
          nodeId: "status",
          properties: [
            { target: "textContent", value: { type: "enum", value: "approved" } },
            { target: "visibility", value: { type: "boolean", value: true } },
          ],
        },
      ],
    });
    assert.throws(
      () =>
        parseRuntimeViewModelJson(
          JSON.stringify({
            nodes: [
              {
                nodeId: "status",
                properties: [{ target: "visibility", value: { type: "string", value: "yes" } }],
              },
            ],
          }),
        ),
      RuntimeStateCodecError,
    );
  });
});
