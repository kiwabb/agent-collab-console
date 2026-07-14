export type RuntimeRoleId = string;
export type RuntimePageId = string;
export type RuntimeNodeId = string;
export type RuntimeVariableId = string;
export type RuntimeSchemaId = string;
export type RuntimeFormId = string;
export type RuntimeFieldId = string;

export interface NullRuntimeValue {
  type: "null";
}

export interface BooleanRuntimeValue {
  type: "boolean";
  value: boolean;
}

export interface IntegerRuntimeValue {
  type: "integer";
  value: number;
}

export interface StringRuntimeValue {
  type: "string";
  value: string;
}

export interface EnumRuntimeValue {
  type: "enum";
  value: string;
}

export interface EntityRefRuntimeValue {
  type: "entityRef";
  schemaId: RuntimeSchemaId;
  entityId: string;
}

export type RuntimeValue =
  | NullRuntimeValue
  | BooleanRuntimeValue
  | IntegerRuntimeValue
  | StringRuntimeValue
  | EnumRuntimeValue
  | EntityRefRuntimeValue;

export type RuntimeValueType = RuntimeValue["type"];

export interface RuntimeRoleDefinition {
  id: RuntimeRoleId;
  key: string;
  label: string;
}

export interface RuntimeVariableDefinition {
  id: RuntimeVariableId;
  key: string;
  valueType: RuntimeValueType;
  nullable: boolean;
  defaultValue: RuntimeValue;
}

export interface RuntimeEntityFieldDefinition {
  id: RuntimeFieldId;
  key: string;
  valueType: RuntimeValueType;
  nullable: boolean;
}

export interface RuntimeEntitySchema {
  id: RuntimeSchemaId;
  key: string;
  fields: RuntimeEntityFieldDefinition[];
}

export interface RuntimeFormFieldDefinition {
  id: RuntimeFieldId;
  key: string;
  valueType: "string" | "integer";
  initialValue: StringRuntimeValue | IntegerRuntimeValue;
  required: boolean;
  minInteger: number | null;
}

export interface RuntimeFormDefinition {
  id: RuntimeFormId;
  key: string;
  fields: RuntimeFormFieldDefinition[];
}

export interface RuntimeFieldValue {
  fieldId: RuntimeFieldId;
  value: RuntimeValue;
}

export interface RuntimeVariableValue {
  variableId: RuntimeVariableId;
  value: RuntimeValue;
}

export interface RuntimeEntity {
  id: string;
  schemaId: RuntimeSchemaId;
  fields: RuntimeFieldValue[];
}

export interface RuntimeEntitySet {
  schemaId: RuntimeSchemaId;
  entities: RuntimeEntity[];
}

export interface RuntimeFormError {
  fieldId: RuntimeFieldId;
  code: "required" | "min_integer" | "type_mismatch";
}

export interface RuntimeFormState {
  formId: RuntimeFormId;
  values: RuntimeFieldValue[];
  errors: RuntimeFormError[];
}

export interface RuntimeNotification {
  id: string;
  level: "info" | "success" | "warning" | "error";
  message: string;
}

export interface PrototypeRuntimeState {
  runtimeStateSchemaVersion: 1;
  sessionId: string;
  scenarioId: string;
  runtimeCoreVersion: string;
  stateMachineKernelVersion: string;
  sequenceNo: number;
  actorRoleId: RuntimeRoleId;
  currentPageId: RuntimePageId;
  navigationStack: RuntimePageId[];
  variableValues: RuntimeVariableValue[];
  entitySets: RuntimeEntitySet[];
  formStates: RuntimeFormState[];
  notifications: RuntimeNotification[];
  allowSimulatedRoleSwitch: boolean;
}

export interface LiteralValueExpression {
  kind: "literal";
  value: RuntimeValue;
}

export interface VariableValueExpression {
  kind: "variable";
  variableId: RuntimeVariableId;
}

export interface FormFieldValueExpression {
  kind: "formField";
  formId: RuntimeFormId;
  fieldId: RuntimeFieldId;
}

export interface EventEntityRefExpression {
  kind: "eventEntityRef";
}

export type RuntimeEntityRefExpression = VariableValueExpression | EventEntityRefExpression;

export interface EntityFieldValueExpression {
  kind: "entityField";
  entityRef: RuntimeEntityRefExpression;
  fieldId: RuntimeFieldId;
  fallback: RuntimeValue;
}

export type RuntimeValueExpression =
  | LiteralValueExpression
  | VariableValueExpression
  | FormFieldValueExpression
  | EventEntityRefExpression
  | EntityFieldValueExpression;

export interface AllRuntimePredicate {
  kind: "all";
  items: RuntimePredicate[];
}

export interface RoleIsRuntimePredicate {
  kind: "roleIs";
  roleId: RuntimeRoleId;
}

export interface FormValidRuntimePredicate {
  kind: "formValid";
  formId: RuntimeFormId;
}

export interface CompareRuntimePredicate {
  kind: "compare";
  operator: "eq" | "ne";
  left: RuntimeValueExpression;
  right: RuntimeValueExpression;
}

export type RuntimePredicate =
  | AllRuntimePredicate
  | RoleIsRuntimePredicate
  | FormValidRuntimePredicate
  | CompareRuntimePredicate;

export interface SetVariableEffect {
  kind: "setVariable";
  variableId: RuntimeVariableId;
  value: RuntimeValueExpression;
}

export interface ValidateFormEffect {
  kind: "validateForm";
  formId: RuntimeFormId;
}

export interface CreateEntityEffect {
  kind: "createEntity";
  schemaId: RuntimeSchemaId;
  resultVariableId: RuntimeVariableId;
  values: Array<{
    fieldId: RuntimeFieldId;
    value: RuntimeValueExpression;
  }>;
}

export interface UpdateEntityEffect {
  kind: "updateEntity";
  schemaId: RuntimeSchemaId;
  entityRef: RuntimeEntityRefExpression;
  updates: Array<{
    fieldId: RuntimeFieldId;
    value: RuntimeValueExpression;
  }>;
}

export interface NavigateEffect {
  kind: "navigate";
  targetPageId: RuntimePageId;
}

export interface NotifyEffect {
  kind: "notify";
  level: RuntimeNotification["level"];
  message: string;
}

export type RuntimeEffect =
  | SetVariableEffect
  | ValidateFormEffect
  | CreateEntityEffect
  | UpdateEntityEffect
  | NavigateEffect
  | NotifyEffect;

export interface RuntimeNodeTrigger {
  kind: "nodeEvent";
  nodeId: RuntimeNodeId;
  event: "click" | "submit" | "rowActivated";
}

export interface RuntimeBehaviorRule {
  id: string;
  key: string;
  enabled: boolean;
  trigger: RuntimeNodeTrigger;
  guard: RuntimePredicate | null;
  effects: RuntimeEffect[];
  guardFalseEffects: RuntimeEffect[];
}

export interface TextViewBinding {
  id: string;
  nodeId: RuntimeNodeId;
  target: "textContent";
  value: RuntimeValueExpression;
}

export interface VisibilityViewBinding {
  id: string;
  nodeId: RuntimeNodeId;
  target: "visibility";
  predicate: RuntimePredicate;
}

export interface TableRowsViewBinding {
  id: string;
  nodeId: RuntimeNodeId;
  target: "tableRows";
  schemaId: RuntimeSchemaId;
  sortFieldId: RuntimeFieldId | null;
  sortDirection: "asc" | "desc";
}

export type RuntimeViewBinding = TextViewBinding | VisibilityViewBinding | TableRowsViewBinding;

export interface RuntimeScenario {
  id: string;
  key: string;
  actorRoleId: RuntimeRoleId;
  startPageId: RuntimePageId;
  initialVariables: RuntimeVariableValue[];
  entityFixtures: RuntimeEntitySet[];
  allowSimulatedRoleSwitch: boolean;
}

export interface RuntimeDefinition {
  runtimeSchemaVersion: 1;
  pageIds: RuntimePageId[];
  roles: RuntimeRoleDefinition[];
  variables: RuntimeVariableDefinition[];
  entitySchemas: RuntimeEntitySchema[];
  forms: RuntimeFormDefinition[];
  viewBindings: RuntimeViewBinding[];
  rules: RuntimeBehaviorRule[];
  scenarios: RuntimeScenario[];
}

export interface FieldValueCommittedEvent {
  kind: "fieldValueCommitted";
  nodeId: RuntimeNodeId;
  formId: RuntimeFormId;
  fieldId: RuntimeFieldId;
  value: RuntimeValue;
}

export interface NodeActivatedEvent {
  kind: "nodeActivated";
  nodeId: RuntimeNodeId;
  event: "click" | "submit";
}

export interface TableRowActivatedEvent {
  kind: "tableRowActivated";
  nodeId: RuntimeNodeId;
  entityRef: EntityRefRuntimeValue;
}

export interface SwitchSimulatedRoleEvent {
  kind: "switchSimulatedRole";
  roleId: RuntimeRoleId;
}

export type RuntimeEvent =
  FieldValueCommittedEvent | NodeActivatedEvent | TableRowActivatedEvent | SwitchSimulatedRoleEvent;

export interface RuntimeEventBatch {
  clientEventId: string;
  expectedSequenceNo: number;
  events: RuntimeEvent[];
}

export type RuntimeTransitionOutcome = "applied" | "guard_false" | "validation_failed";

export interface RuntimeEffectTrace {
  eventIndex: number;
  effectIndex: number;
  effectKind: RuntimeEffect["kind"];
  beforeState: PrototypeRuntimeState;
  afterState: PrototypeRuntimeState;
}

export interface RuntimeTransitionReduction {
  state: PrototypeRuntimeState;
  outcome: RuntimeTransitionOutcome;
  matchedRuleIds: string[];
  effectTraces: RuntimeEffectTrace[];
}

export interface RuntimeEffectEvidence {
  eventIndex: number;
  effectIndex: number;
  effectKind: RuntimeEffect["kind"];
  beforeStateHash: string;
  afterStateHash: string;
}

export interface RuntimeTransitionReport {
  clientEventId: string;
  baseSequenceNo: number;
  resultSequenceNo: number;
  outcome: RuntimeTransitionOutcome;
  matchedRuleIds: string[];
  baseStateHash: string;
  resultStateHash: string;
  resultViewModelHash: string;
  effects: RuntimeEffectEvidence[];
}

export interface TextViewProperty {
  target: "textContent";
  value: RuntimeValue;
}

export interface VisibilityViewProperty {
  target: "visibility";
  value: BooleanRuntimeValue;
}

export interface TableRowsViewProperty {
  target: "tableRows";
  rows: RuntimeEntity[];
}

export type RuntimeViewProperty = TextViewProperty | VisibilityViewProperty | TableRowsViewProperty;

export interface RuntimeNodeViewModel {
  nodeId: RuntimeNodeId;
  properties: RuntimeViewProperty[];
}

export interface RuntimeViewModel {
  nodes: RuntimeNodeViewModel[];
}

export interface RuntimeTransitionResult {
  state: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
  report: RuntimeTransitionReport;
}
