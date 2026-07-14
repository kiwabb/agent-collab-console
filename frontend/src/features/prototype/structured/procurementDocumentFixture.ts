import type { RuntimeDefinition, RuntimeValue } from "../runtime/types";
import type { NewStructuredPrototypeDocument, StructuredPrototypeLayoutItem } from "./types";

export const STRUCTURED_PROCUREMENT_IDS = {
  pages: {
    list: "cdb0bb26-ce9d-5a2c-9265-c048aa1da81f",
    create: "4950fd64-c7cf-5db2-a05a-8e67880b874f",
    detail: "3b1d2711-7c5d-5ddd-a13a-392e2d640fae",
  },
  roots: {
    list: "699a78d6-b216-5c1e-975b-d6b51bbb1376",
    create: "d6871a18-92f3-51f5-af16-a86952bcf2b0",
    detail: "95d2f0e9-fab7-5daf-80f1-884f30d839b5",
  },
  nodes: {
    listTitle: "b347ef1d-394f-55ec-82cc-8758350e70ed",
    requestTable: "cf8fe42a-7d26-5cdf-9ffa-6cb6901ee29d",
    createForm: "495a90c7-34ed-5852-a8dd-00baf0c0c335",
    titleInput: "d1dced07-9e49-52f8-9d50-d0d16aef82f8",
    amountInput: "55f44344-6e86-5334-94cc-86e1d358addc",
    submitRequest: "e02d3660-f331-5db0-8ebc-8f7cf22307b6",
    detailHeading: "c6294f7b-362e-538a-935b-900373243f9a",
    detailTitle: "41128cd0-5d85-555b-86bc-3001fed6dd4d",
    detailStatus: "83b85e74-6f40-538f-be3c-d37227316001",
    approveRequest: "c62ff92a-40b4-5d48-a18e-776326e5e0ae",
  },
  navigation: {
    list: "56522b0e-2cf1-526e-b5e8-a1fe4dad58b8",
    create: "87601c84-4a22-59ce-8250-2213ccd1b00b",
    detail: "09951ab9-cb39-56b7-a4f0-bcf426472040",
  },
  roles: {
    applicant: "e628ab94-ae22-546f-8fc7-27af14d260f8",
    manager: "4b163a5a-1cd6-5cd7-94d8-106049142975",
  },
  form: {
    create: "d273fb60-99c3-5047-beb9-2da0c82ba89c",
    title: "198f1593-9adf-50cc-b236-58754c2728aa",
    amount: "9c925df9-ab73-5841-bfab-3a6d82de06df",
  },
  schema: {
    request: "d7680b4a-8f07-5c0a-a19d-3b67ddb3d420",
    title: "f9654767-2634-5222-994a-2736d13eb1ba",
    amount: "0eb4632b-d9cc-553d-a059-39186e6240b1",
    status: "8dd3f59c-95ef-5045-b1a6-bdade4e637c7",
  },
  variables: {
    selectedRequest: "85af2b44-178a-5973-87fe-c7f88e0c80b0",
  },
  bindings: {
    table: "da417aee-740b-57c7-8c01-5dbb4e6e9002",
    detailTitle: "c28876e2-6de6-5da2-a4aa-19c738033f65",
    detailStatus: "b34cc164-646b-52e0-bdf9-a5de75644d98",
    approveVisible: "04e82dbc-486b-5368-ba32-6c6f691cc5bb",
  },
  scenario: "c7f54bc6-a1c2-55c0-bf9a-f7c12800a81f",
  rules: {
    submit: "981525de-cc99-5862-b354-4566e87f7d7e",
    select: "d00b5578-e7c3-55af-9ccf-86c0f309eb8c",
    approve: "ec93f489-4346-5c97-9f68-d20acea97ec1",
  },
  flows: {
    submit: "ed415908-dd56-58f4-b332-979a0f176b04",
    select: "908847cf-9673-523b-a09e-77054c7688bf",
    approve: "2984c278-5dec-5d08-bd2b-ce9f4005e595",
  },
} as const;

const AUTO_LAYOUT: StructuredPrototypeLayoutItem = {
  width: { unit: "auto", value: null },
  minWidth: null,
  maxWidth: null,
  height: { unit: "auto", value: null },
  minHeight: null,
  maxHeight: null,
  grow: 0,
  shrink: 1,
  alignSelf: "stretch",
};

function stringValue(value: string): RuntimeValue {
  return { type: "string", value };
}

function enumValue(value: string): RuntimeValue {
  return { type: "enum", value };
}

function runtimeDefinition(): RuntimeDefinition {
  const ids = STRUCTURED_PROCUREMENT_IDS;
  return {
    runtimeSchemaVersion: 1,
    pageIds: [ids.pages.list, ids.pages.create, ids.pages.detail],
    roles: [
      { id: ids.roles.applicant, key: "applicant", label: "申请人" },
      { id: ids.roles.manager, key: "manager", label: "主管" },
    ],
    variables: [
      {
        id: ids.variables.selectedRequest,
        key: "selected-request",
        valueType: "entityRef",
        nullable: true,
        defaultValue: { type: "null" },
      },
    ],
    entitySchemas: [
      {
        id: ids.schema.request,
        key: "purchase-request",
        fields: [
          { id: ids.schema.title, key: "title", valueType: "string", nullable: false },
          { id: ids.schema.amount, key: "amount", valueType: "integer", nullable: false },
          { id: ids.schema.status, key: "status", valueType: "enum", nullable: false },
        ],
      },
    ],
    forms: [
      {
        id: ids.form.create,
        key: "create-purchase-request",
        fields: [
          {
            id: ids.form.title,
            key: "title",
            valueType: "string",
            initialValue: { type: "string", value: "" },
            required: true,
            minInteger: null,
          },
          {
            id: ids.form.amount,
            key: "amount",
            valueType: "integer",
            initialValue: { type: "integer", value: 0 },
            required: true,
            minInteger: 1,
          },
        ],
      },
    ],
    viewBindings: [
      {
        id: ids.bindings.table,
        nodeId: ids.nodes.requestTable,
        target: "tableRows",
        schemaId: ids.schema.request,
        sortFieldId: ids.schema.title,
        sortDirection: "asc",
      },
      {
        id: ids.bindings.detailTitle,
        nodeId: ids.nodes.detailTitle,
        target: "textContent",
        value: {
          kind: "entityField",
          entityRef: { kind: "variable", variableId: ids.variables.selectedRequest },
          fieldId: ids.schema.title,
          fallback: stringValue("尚未选择申请"),
        },
      },
      {
        id: ids.bindings.detailStatus,
        nodeId: ids.nodes.detailStatus,
        target: "textContent",
        value: {
          kind: "entityField",
          entityRef: { kind: "variable", variableId: ids.variables.selectedRequest },
          fieldId: ids.schema.status,
          fallback: enumValue("not-selected"),
        },
      },
      {
        id: ids.bindings.approveVisible,
        nodeId: ids.nodes.approveRequest,
        target: "visibility",
        predicate: { kind: "roleIs", roleId: ids.roles.manager },
      },
    ],
    rules: [
      {
        id: ids.rules.submit,
        key: "submit-request",
        enabled: true,
        trigger: { kind: "nodeEvent", nodeId: ids.nodes.submitRequest, event: "submit" },
        guard: { kind: "roleIs", roleId: ids.roles.applicant },
        effects: [
          { kind: "validateForm", formId: ids.form.create },
          {
            kind: "createEntity",
            schemaId: ids.schema.request,
            resultVariableId: ids.variables.selectedRequest,
            values: [
              {
                fieldId: ids.schema.title,
                value: { kind: "formField", formId: ids.form.create, fieldId: ids.form.title },
              },
              {
                fieldId: ids.schema.amount,
                value: { kind: "formField", formId: ids.form.create, fieldId: ids.form.amount },
              },
              {
                fieldId: ids.schema.status,
                value: { kind: "literal", value: enumValue("pending") },
              },
            ],
          },
          { kind: "navigate", targetPageId: ids.pages.detail },
          { kind: "notify", level: "success", message: "采购申请已提交" },
        ],
        guardFalseEffects: [
          { kind: "notify", level: "error", message: "当前模拟角色不能提交申请" },
        ],
      },
      {
        id: ids.rules.select,
        key: "select-request",
        enabled: true,
        trigger: { kind: "nodeEvent", nodeId: ids.nodes.requestTable, event: "rowActivated" },
        guard: null,
        effects: [
          {
            kind: "setVariable",
            variableId: ids.variables.selectedRequest,
            value: { kind: "eventEntityRef" },
          },
          { kind: "navigate", targetPageId: ids.pages.detail },
        ],
        guardFalseEffects: [],
      },
      {
        id: ids.rules.approve,
        key: "approve-request",
        enabled: true,
        trigger: { kind: "nodeEvent", nodeId: ids.nodes.approveRequest, event: "click" },
        guard: {
          kind: "all",
          items: [
            { kind: "roleIs", roleId: ids.roles.manager },
            {
              kind: "compare",
              operator: "eq",
              left: {
                kind: "entityField",
                entityRef: { kind: "variable", variableId: ids.variables.selectedRequest },
                fieldId: ids.schema.status,
                fallback: enumValue("not-selected"),
              },
              right: { kind: "literal", value: enumValue("pending") },
            },
          ],
        },
        effects: [
          {
            kind: "updateEntity",
            schemaId: ids.schema.request,
            entityRef: { kind: "variable", variableId: ids.variables.selectedRequest },
            updates: [
              {
                fieldId: ids.schema.status,
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
        id: ids.scenario,
        key: "purchase-approval-happy-path",
        actorRoleId: ids.roles.applicant,
        startPageId: ids.pages.create,
        initialVariables: [{ variableId: ids.variables.selectedRequest, value: { type: "null" } }],
        entityFixtures: [],
        allowSimulatedRoleSwitch: true,
      },
    ],
  };
}

export function createProcurementPrototypeDocument(): NewStructuredPrototypeDocument {
  const ids = STRUCTURED_PROCUREMENT_IDS;
  const common = (id: string, name: string) => ({
    id,
    name,
    visibility: "visible" as const,
    layoutItem: AUTO_LAYOUT,
    responsive: [],
  });
  return {
    schemaVersion: 1,
    title: "Orion 采购协同",
    locale: "zh-CN",
    settings: { defaultViewport: "desktop", theme: "light" },
    tokens: {
      colors: [
        { key: "primary", value: "#126b5f" },
        { key: "surface", value: "#ffffff" },
      ],
      spacing: [{ key: "panel-gap", value: "16px" }],
    },
    componentDefinitions: [],
    pages: [
      {
        id: ids.pages.list,
        key: "purchase-list",
        title: "采购申请列表",
        route: "/purchases",
        viewport: { width: 1440, height: 900 },
        root: {
          ...common(ids.roots.list, "采购申请列表页面"),
          type: "Stack",
          direction: "column",
          gap: 16,
          align: "stretch",
          justify: "start",
          padding: { top: 24, right: 24, bottom: 24, left: 24 },
          children: [
            {
              ...common(ids.nodes.listTitle, "采购申请列表标题"),
              type: "Text",
              content: "采购申请",
              semantic: "heading",
              tone: "default",
            },
            {
              ...common(ids.nodes.requestTable, "采购申请表格"),
              type: "Table",
              columns: [
                { key: "title", label: "申请事项" },
                { key: "amount", label: "金额" },
                { key: "status", label: "状态" },
              ],
              rows: [],
              density: "comfortable",
            },
          ],
        },
      },
      {
        id: ids.pages.create,
        key: "purchase-create",
        title: "创建采购申请",
        route: "/purchases/new",
        viewport: { width: 1440, height: 900 },
        root: {
          ...common(ids.roots.create, "创建采购申请页面"),
          type: "Stack",
          direction: "column",
          gap: 16,
          align: "stretch",
          justify: "start",
          padding: { top: 24, right: 24, bottom: 24, left: 24 },
          children: [
            {
              ...common(ids.nodes.createForm, "采购申请表单"),
              type: "Form",
              formDefinitionId: ids.form.create,
              gap: 14,
              padding: { top: 0, right: 0, bottom: 0, left: 0 },
              children: [
                {
                  ...common(ids.nodes.titleInput, "申请事项输入框"),
                  type: "Input",
                  label: "申请事项",
                  placeholder: "例如：研发团队笔记本电脑",
                  value: "",
                  inputType: "text",
                  required: true,
                  disabled: false,
                },
                {
                  ...common(ids.nodes.amountInput, "采购金额输入框"),
                  type: "Input",
                  label: "采购金额",
                  placeholder: "请输入整数金额",
                  value: "",
                  inputType: "number",
                  required: true,
                  disabled: false,
                },
                {
                  ...common(ids.nodes.submitRequest, "提交采购申请按钮"),
                  type: "Button",
                  label: "提交申请",
                  variant: "primary",
                  size: "medium",
                  disabled: false,
                  iconName: null,
                },
              ],
            },
          ],
        },
      },
      {
        id: ids.pages.detail,
        key: "purchase-detail",
        title: "采购申请详情",
        route: "/purchases/detail",
        viewport: { width: 1440, height: 900 },
        root: {
          ...common(ids.roots.detail, "采购申请详情页面"),
          type: "Stack",
          direction: "column",
          gap: 14,
          align: "stretch",
          justify: "start",
          padding: { top: 24, right: 24, bottom: 24, left: 24 },
          children: [
            {
              ...common(ids.nodes.detailHeading, "采购申请详情标题"),
              type: "Text",
              content: "采购申请详情",
              semantic: "heading",
              tone: "default",
            },
            {
              ...common(ids.nodes.detailTitle, "申请事项"),
              type: "Text",
              content: "尚未选择申请",
              semantic: "body",
              tone: "default",
            },
            {
              ...common(ids.nodes.detailStatus, "申请状态"),
              type: "Text",
              content: "not-selected",
              semantic: "label",
              tone: "muted",
            },
            {
              ...common(ids.nodes.approveRequest, "审批通过按钮"),
              type: "Button",
              label: "审批通过",
              variant: "primary",
              size: "medium",
              disabled: false,
              iconName: null,
            },
          ],
        },
      },
    ],
    navigation: {
      items: [
        {
          id: ids.navigation.list,
          key: "purchase-list",
          label: "采购申请",
          targetPageId: ids.pages.list,
        },
        {
          id: ids.navigation.create,
          key: "purchase-create",
          label: "创建申请",
          targetPageId: ids.pages.create,
        },
        {
          id: ids.navigation.detail,
          key: "purchase-detail",
          label: "申请详情",
          targetPageId: ids.pages.detail,
        },
      ],
    },
    flows: [
      {
        id: ids.flows.submit,
        key: "submit-request",
        ruleId: ids.rules.submit,
        fromNodeId: ids.nodes.submitRequest,
        toPageId: ids.pages.detail,
      },
      {
        id: ids.flows.select,
        key: "select-request",
        ruleId: ids.rules.select,
        fromNodeId: ids.nodes.requestTable,
        toPageId: ids.pages.detail,
      },
      {
        id: ids.flows.approve,
        key: "approve-request",
        ruleId: ids.rules.approve,
        fromNodeId: ids.nodes.approveRequest,
        toPageId: ids.pages.detail,
      },
    ],
    runtime: runtimeDefinition(),
    assetRefs: [],
  };
}

export const STRUCTURED_PROTOTYPE_AUTO_LAYOUT = AUTO_LAYOUT;
