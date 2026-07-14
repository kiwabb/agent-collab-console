import type {
  EntityRefRuntimeValue,
  IntegerRuntimeValue,
  PrototypeRuntimeState,
  RuntimeDefinition,
  RuntimeEventBatch,
  StringRuntimeValue,
  RuntimeTransitionResult,
  RuntimeValue,
} from "./types";
import { applyRuntimeEventBatch, createInitialRuntimeState } from "./runtimeCore";
import {
  parsePrototypeRuntimeStateJson,
  serializePrototypeRuntimeState,
} from "./runtimeStateCodec";

export const PROCUREMENT_IDS = {
  roles: {
    applicant: "role-applicant",
    manager: "role-manager",
  },
  pages: {
    list: "page-purchase-list",
    create: "page-purchase-create",
    detail: "page-purchase-detail",
  },
  nodes: {
    requestTable: "node-request-table",
    submitRequest: "node-submit-request",
    approveRequest: "node-approve-request",
    detailTitle: "node-detail-title",
    detailStatus: "node-detail-status",
  },
  schema: {
    request: "schema-purchase-request",
  },
  fields: {
    title: "field-title",
    amount: "field-amount",
    status: "field-status",
  },
  forms: {
    createRequest: "form-create-request",
  },
  variables: {
    selectedRequest: "variable-selected-request",
  },
  scenarios: {
    happyPath: "scenario-purchase-approval",
  },
  rules: {
    submit: "rule-submit-request",
    select: "rule-select-request",
    approve: "rule-approve-request",
  },
} as const;

function nullValue(): RuntimeValue {
  return { type: "null" };
}

function stringValue(value: string): StringRuntimeValue {
  return { type: "string", value };
}

function integerValue(value: number): IntegerRuntimeValue {
  return { type: "integer", value };
}

function enumValue(value: string): RuntimeValue {
  return { type: "enum", value };
}

export const PROCUREMENT_RUNTIME_DEFINITION: RuntimeDefinition = {
  runtimeSchemaVersion: 1,
  pageIds: [PROCUREMENT_IDS.pages.list, PROCUREMENT_IDS.pages.create, PROCUREMENT_IDS.pages.detail],
  roles: [
    { id: PROCUREMENT_IDS.roles.applicant, key: "applicant", label: "申请人" },
    { id: PROCUREMENT_IDS.roles.manager, key: "manager", label: "主管" },
  ],
  variables: [
    {
      id: PROCUREMENT_IDS.variables.selectedRequest,
      key: "selected-request",
      valueType: "entityRef",
      nullable: true,
      defaultValue: nullValue(),
    },
  ],
  entitySchemas: [
    {
      id: PROCUREMENT_IDS.schema.request,
      key: "purchase-request",
      fields: [
        {
          id: PROCUREMENT_IDS.fields.title,
          key: "title",
          valueType: "string",
          nullable: false,
        },
        {
          id: PROCUREMENT_IDS.fields.amount,
          key: "amount",
          valueType: "integer",
          nullable: false,
        },
        {
          id: PROCUREMENT_IDS.fields.status,
          key: "status",
          valueType: "enum",
          nullable: false,
        },
      ],
    },
  ],
  forms: [
    {
      id: PROCUREMENT_IDS.forms.createRequest,
      key: "create-purchase-request",
      fields: [
        {
          id: PROCUREMENT_IDS.fields.title,
          key: "title",
          valueType: "string",
          initialValue: stringValue(""),
          required: true,
          minInteger: null,
        },
        {
          id: PROCUREMENT_IDS.fields.amount,
          key: "amount",
          valueType: "integer",
          initialValue: integerValue(0),
          required: true,
          minInteger: 1,
        },
      ],
    },
  ],
  viewBindings: [
    {
      id: "binding-request-table",
      nodeId: PROCUREMENT_IDS.nodes.requestTable,
      target: "tableRows",
      schemaId: PROCUREMENT_IDS.schema.request,
      sortFieldId: PROCUREMENT_IDS.fields.title,
      sortDirection: "asc",
    },
    {
      id: "binding-detail-title",
      nodeId: PROCUREMENT_IDS.nodes.detailTitle,
      target: "textContent",
      value: {
        kind: "entityField",
        entityRef: {
          kind: "variable",
          variableId: PROCUREMENT_IDS.variables.selectedRequest,
        },
        fieldId: PROCUREMENT_IDS.fields.title,
        fallback: stringValue(""),
      },
    },
    {
      id: "binding-detail-status",
      nodeId: PROCUREMENT_IDS.nodes.detailStatus,
      target: "textContent",
      value: {
        kind: "entityField",
        entityRef: {
          kind: "variable",
          variableId: PROCUREMENT_IDS.variables.selectedRequest,
        },
        fieldId: PROCUREMENT_IDS.fields.status,
        fallback: enumValue("not-selected"),
      },
    },
    {
      id: "binding-approve-visible",
      nodeId: PROCUREMENT_IDS.nodes.approveRequest,
      target: "visibility",
      predicate: { kind: "roleIs", roleId: PROCUREMENT_IDS.roles.manager },
    },
  ],
  rules: [
    {
      id: PROCUREMENT_IDS.rules.submit,
      key: "submit-request",
      enabled: true,
      trigger: {
        kind: "nodeEvent",
        nodeId: PROCUREMENT_IDS.nodes.submitRequest,
        event: "submit",
      },
      guard: { kind: "roleIs", roleId: PROCUREMENT_IDS.roles.applicant },
      effects: [
        { kind: "validateForm", formId: PROCUREMENT_IDS.forms.createRequest },
        {
          kind: "createEntity",
          schemaId: PROCUREMENT_IDS.schema.request,
          resultVariableId: PROCUREMENT_IDS.variables.selectedRequest,
          values: [
            {
              fieldId: PROCUREMENT_IDS.fields.title,
              value: {
                kind: "formField",
                formId: PROCUREMENT_IDS.forms.createRequest,
                fieldId: PROCUREMENT_IDS.fields.title,
              },
            },
            {
              fieldId: PROCUREMENT_IDS.fields.amount,
              value: {
                kind: "formField",
                formId: PROCUREMENT_IDS.forms.createRequest,
                fieldId: PROCUREMENT_IDS.fields.amount,
              },
            },
            {
              fieldId: PROCUREMENT_IDS.fields.status,
              value: { kind: "literal", value: enumValue("pending") },
            },
          ],
        },
        { kind: "navigate", targetPageId: PROCUREMENT_IDS.pages.detail },
        { kind: "notify", level: "success", message: "采购申请已提交" },
      ],
      guardFalseEffects: [{ kind: "notify", level: "error", message: "当前模拟角色不能提交申请" }],
    },
    {
      id: PROCUREMENT_IDS.rules.select,
      key: "select-request",
      enabled: true,
      trigger: {
        kind: "nodeEvent",
        nodeId: PROCUREMENT_IDS.nodes.requestTable,
        event: "rowActivated",
      },
      guard: null,
      effects: [
        {
          kind: "setVariable",
          variableId: PROCUREMENT_IDS.variables.selectedRequest,
          value: { kind: "eventEntityRef" },
        },
        { kind: "navigate", targetPageId: PROCUREMENT_IDS.pages.detail },
      ],
      guardFalseEffects: [],
    },
    {
      id: PROCUREMENT_IDS.rules.approve,
      key: "approve-request",
      enabled: true,
      trigger: {
        kind: "nodeEvent",
        nodeId: PROCUREMENT_IDS.nodes.approveRequest,
        event: "click",
      },
      guard: {
        kind: "all",
        items: [
          { kind: "roleIs", roleId: PROCUREMENT_IDS.roles.manager },
          {
            kind: "compare",
            operator: "eq",
            left: {
              kind: "entityField",
              entityRef: {
                kind: "variable",
                variableId: PROCUREMENT_IDS.variables.selectedRequest,
              },
              fieldId: PROCUREMENT_IDS.fields.status,
              fallback: enumValue("not-selected"),
            },
            right: { kind: "literal", value: enumValue("pending") },
          },
        ],
      },
      effects: [
        {
          kind: "updateEntity",
          schemaId: PROCUREMENT_IDS.schema.request,
          entityRef: {
            kind: "variable",
            variableId: PROCUREMENT_IDS.variables.selectedRequest,
          },
          updates: [
            {
              fieldId: PROCUREMENT_IDS.fields.status,
              value: { kind: "literal", value: enumValue("approved") },
            },
          ],
        },
        { kind: "notify", level: "success", message: "采购申请已审批通过" },
      ],
      guardFalseEffects: [{ kind: "notify", level: "error", message: "当前申请不能审批" }],
    },
  ],
  scenarios: [
    {
      id: PROCUREMENT_IDS.scenarios.happyPath,
      key: "purchase-approval-happy-path",
      actorRoleId: PROCUREMENT_IDS.roles.applicant,
      startPageId: PROCUREMENT_IDS.pages.create,
      initialVariables: [
        { variableId: PROCUREMENT_IDS.variables.selectedRequest, value: nullValue() },
      ],
      entityFixtures: [],
      allowSimulatedRoleSwitch: true,
    },
  ],
};

export function procurementApprovalEventBatches(): RuntimeEventBatch[] {
  return [
    {
      clientEventId: "event-submit-request",
      expectedSequenceNo: 0,
      events: [
        {
          kind: "fieldValueCommitted",
          nodeId: "node-request-title-input",
          formId: PROCUREMENT_IDS.forms.createRequest,
          fieldId: PROCUREMENT_IDS.fields.title,
          value: stringValue("研发笔记本电脑"),
        },
        {
          kind: "fieldValueCommitted",
          nodeId: "node-request-amount-input",
          formId: PROCUREMENT_IDS.forms.createRequest,
          fieldId: PROCUREMENT_IDS.fields.amount,
          value: integerValue(12_500),
        },
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.submitRequest,
          event: "submit",
        },
      ],
    },
    {
      clientEventId: "event-switch-manager",
      expectedSequenceNo: 1,
      events: [{ kind: "switchSimulatedRole", roleId: PROCUREMENT_IDS.roles.manager }],
    },
    {
      clientEventId: "event-approve-request",
      expectedSequenceNo: 2,
      events: [
        {
          kind: "nodeActivated",
          nodeId: PROCUREMENT_IDS.nodes.approveRequest,
          event: "click",
        },
      ],
    },
  ];
}

export async function runProcurementApprovalScenario(
  sessionId: string,
  jsonRoundTripBetweenTransitions: boolean,
): Promise<RuntimeTransitionResult[]> {
  let state: PrototypeRuntimeState = createInitialRuntimeState(
    PROCUREMENT_RUNTIME_DEFINITION,
    PROCUREMENT_IDS.scenarios.happyPath,
    sessionId,
  );
  const results: RuntimeTransitionResult[] = [];
  for (const batch of procurementApprovalEventBatches()) {
    const result = await applyRuntimeEventBatch(PROCUREMENT_RUNTIME_DEFINITION, state, batch);
    results.push(result);
    state = jsonRoundTripBetweenTransitions
      ? parsePrototypeRuntimeStateJson(serializePrototypeRuntimeState(result.state))
      : result.state;
  }
  return results;
}

export function selectedRequestRef(state: PrototypeRuntimeState): EntityRefRuntimeValue | null {
  const selected = state.variableValues.find(
    (entry) => entry.variableId === PROCUREMENT_IDS.variables.selectedRequest,
  )?.value;
  return selected?.type === "entityRef" ? selected : null;
}
