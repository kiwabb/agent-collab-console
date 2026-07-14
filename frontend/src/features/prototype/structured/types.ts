import type { RuntimeDefinition, RuntimeEvent, RuntimeTransitionOutcome } from "../runtime/types";

export type StructuredPrototypeRecordingKind =
  "studio_preview" | "recorded_review" | "shared_preview";

export interface StructuredPrototypeLength {
  unit: "px" | "percent" | "rem" | "auto";
  value: string | null;
}

export interface StructuredPrototypeLayoutItem {
  width: StructuredPrototypeLength;
  minWidth: StructuredPrototypeLength | null;
  maxWidth: StructuredPrototypeLength | null;
  height: StructuredPrototypeLength;
  minHeight: StructuredPrototypeLength | null;
  maxHeight: StructuredPrototypeLength | null;
  grow: number;
  shrink: number;
  alignSelf: "auto" | "start" | "center" | "end" | "stretch";
}

export interface StructuredPrototypeLayoutUpdate {
  width?: StructuredPrototypeLength;
  minWidth?: StructuredPrototypeLength | null;
  maxWidth?: StructuredPrototypeLength | null;
  height?: StructuredPrototypeLength;
  minHeight?: StructuredPrototypeLength | null;
  maxHeight?: StructuredPrototypeLength | null;
  grow?: number;
  shrink?: number;
  alignSelf?: "auto" | "start" | "center" | "end" | "stretch";
}

export interface StructuredPrototypeResponsiveOverride {
  breakpoint: "sm" | "md" | "lg";
  layoutItem: StructuredPrototypeLayoutUpdate;
}

export interface StructuredPrototypePadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

interface StructuredPrototypeNodeCommon {
  id: string;
  name: string;
  visibility: "visible" | "hidden";
  layoutItem: StructuredPrototypeLayoutItem;
  responsive: StructuredPrototypeResponsiveOverride[];
}

export interface StructuredPrototypeStackNode extends StructuredPrototypeNodeCommon {
  type: "Stack";
  direction: "row" | "column";
  gap: number;
  align: "start" | "center" | "end" | "stretch";
  justify: "start" | "center" | "end" | "between";
  padding: StructuredPrototypePadding;
  children: StructuredPrototypeNode[];
}

export interface StructuredPrototypeFormNode extends StructuredPrototypeNodeCommon {
  type: "Form";
  formDefinitionId: string;
  gap: number;
  padding: StructuredPrototypePadding;
  children: StructuredPrototypeNode[];
}

export interface StructuredPrototypeTextNode extends StructuredPrototypeNodeCommon {
  type: "Text";
  content: string;
  semantic: "heading" | "body" | "label" | "caption";
  tone: "default" | "muted" | "success" | "warning" | "danger";
}

export interface StructuredPrototypeInputNode extends StructuredPrototypeNodeCommon {
  type: "Input";
  label: string;
  placeholder: string;
  value: string;
  inputType: "text" | "number" | "email";
  required: boolean;
  disabled: boolean;
}

export interface StructuredPrototypeButtonNode extends StructuredPrototypeNodeCommon {
  type: "Button";
  label: string;
  variant: "primary" | "secondary" | "danger" | "ghost";
  size: "small" | "medium" | "large";
  disabled: boolean;
  iconName: string | null;
}

export interface StructuredPrototypeTableColumn {
  key: string;
  label: string;
}

export interface StructuredPrototypeTableCell {
  columnKey: string;
  value: string;
}

export interface StructuredPrototypeTableRow {
  id: string;
  cells: StructuredPrototypeTableCell[];
}

export interface StructuredPrototypeTableNode extends StructuredPrototypeNodeCommon {
  type: "Table";
  columns: StructuredPrototypeTableColumn[];
  rows: StructuredPrototypeTableRow[];
  density: "compact" | "comfortable";
}

export type StructuredPrototypeNode =
  | StructuredPrototypeStackNode
  | StructuredPrototypeFormNode
  | StructuredPrototypeTextNode
  | StructuredPrototypeInputNode
  | StructuredPrototypeButtonNode
  | StructuredPrototypeTableNode;

export interface StructuredPrototypePage {
  id: string;
  key: string;
  title: string;
  route: string;
  viewport: { width: number; height: number };
  root: StructuredPrototypeNode;
}

export interface StructuredPrototypeDocument {
  schemaVersion: 1;
  id: string;
  title: string;
  locale: "zh-CN" | "en-US";
  settings: {
    defaultViewport: "desktop" | "tablet" | "mobile";
    theme: "light" | "dark" | "system";
  };
  tokens: {
    colors: Array<{ key: string; value: string }>;
    spacing: Array<{ key: string; value: string }>;
  };
  componentDefinitions: Array<{
    id: string;
    key: string;
    root: StructuredPrototypeNode;
  }>;
  pages: StructuredPrototypePage[];
  navigation: {
    items: Array<{ id: string; key: string; label: string; targetPageId: string }>;
  };
  flows: Array<{
    id: string;
    key: string;
    ruleId: string;
    fromNodeId: string;
    toPageId: string | null;
  }>;
  runtime: RuntimeDefinition;
  assetRefs: Array<{
    id: string;
    contentHash: string;
    mediaType: "image/png" | "image/jpeg" | "image/webp" | "image/svg+xml";
    alt: string;
  }>;
}

export type NewStructuredPrototypeDocument = Omit<StructuredPrototypeDocument, "id">;

interface NewStructuredPrototypeNodeCommon {
  newNodeKey: string;
  name: string;
  visibility: "visible" | "hidden";
  layoutItem: StructuredPrototypeLayoutItem;
  responsive: StructuredPrototypeResponsiveOverride[];
}

export interface NewStructuredPrototypeStackNode extends NewStructuredPrototypeNodeCommon {
  type: "Stack";
  direction: "row" | "column";
  gap: number;
  align: "start" | "center" | "end" | "stretch";
  justify: "start" | "center" | "end" | "between";
  padding: StructuredPrototypePadding;
  children: NewStructuredPrototypeNode[];
}

export interface NewStructuredPrototypeFormNode extends NewStructuredPrototypeNodeCommon {
  type: "Form";
  formDefinitionId: string;
  gap: number;
  padding: StructuredPrototypePadding;
  children: NewStructuredPrototypeNode[];
}

export interface NewStructuredPrototypeTextNode extends NewStructuredPrototypeNodeCommon {
  type: "Text";
  content: string;
  semantic: "heading" | "body" | "label" | "caption";
  tone: "default" | "muted" | "success" | "warning" | "danger";
}

export interface NewStructuredPrototypeInputNode extends NewStructuredPrototypeNodeCommon {
  type: "Input";
  label: string;
  placeholder: string;
  value: string;
  inputType: "text" | "number" | "email";
  required: boolean;
  disabled: boolean;
}

export interface NewStructuredPrototypeButtonNode extends NewStructuredPrototypeNodeCommon {
  type: "Button";
  label: string;
  variant: "primary" | "secondary" | "danger" | "ghost";
  size: "small" | "medium" | "large";
  disabled: boolean;
  iconName: string | null;
}

export interface NewStructuredPrototypeTableNode extends NewStructuredPrototypeNodeCommon {
  type: "Table";
  columns: StructuredPrototypeTableColumn[];
  rows: StructuredPrototypeTableRow[];
  density: "compact" | "comfortable";
}

export type NewStructuredPrototypeNode =
  | NewStructuredPrototypeStackNode
  | NewStructuredPrototypeFormNode
  | NewStructuredPrototypeTextNode
  | NewStructuredPrototypeInputNode
  | NewStructuredPrototypeButtonNode
  | NewStructuredPrototypeTableNode;

export type StructuredPrototypeNodeRef =
  { kind: "existing"; nodeId: string } | { kind: "new"; newNodeKey: string };

export type StructuredPrototypeNodePropertyUpdate =
  | { kind: "textContent"; content: string }
  | { kind: "label"; label: string }
  | { kind: "placeholder"; placeholder: string }
  | {
      kind: "buttonVariant";
      variant: "primary" | "secondary" | "danger" | "ghost";
    }
  | { kind: "disabled"; disabled: boolean }
  | { kind: "inputValue"; value: string }
  | {
      kind: "tableData";
      columns: StructuredPrototypeTableColumn[];
      rows: StructuredPrototypeTableRow[];
    }
  | { kind: "visibility"; visibility: "visible" | "hidden" };

export type StructuredPrototypeCommand =
  | {
      kind: "insertNode";
      parent: StructuredPrototypeNodeRef;
      slot: null;
      index: number;
      node: NewStructuredPrototypeNode;
    }
  | {
      kind: "moveNode";
      node: StructuredPrototypeNodeRef;
      targetParent: StructuredPrototypeNodeRef;
      targetSlot: null;
      targetIndex: number;
    }
  | { kind: "removeNode"; nodeId: string }
  | {
      kind: "setNodeProperty";
      node: StructuredPrototypeNodeRef;
      update: StructuredPrototypeNodePropertyUpdate;
    }
  | {
      kind: "setNodeLayout";
      node: StructuredPrototypeNodeRef;
      update: StructuredPrototypeLayoutUpdate;
    }
  | { kind: "reorderPage"; pageId: string; targetIndex: number };

export interface StructuredPrototypeCommandBatch {
  commandContractVersion: 1;
  commands: StructuredPrototypeCommand[];
  summary: string;
}

export interface StructuredPrototypeDraft {
  contractVersion: 1;
  operationId: string;
  correlationId: string;
  documentId: string;
  draftId: string;
  headSequenceNo: number;
  documentHash: string;
  document: StructuredPrototypeDocument;
}

export interface AppliedStructuredPrototypeCommands extends StructuredPrototypeDraft {
  appliedBatchId: string;
  allocatedEntityIds: Array<{ newNodeKey: string; entityId: string }>;
  affectedEntityIds: string[];
}

export interface StructuredPrototypeRuntimeSession {
  contractVersion: 1;
  operationId: string;
  correlationId: string;
  sessionId: string;
  documentId: string;
  sourceKind: "draft" | "ai_preview" | "published_revision";
  sourceId: string;
  status: "active" | "completed" | "interrupted" | "corrupt";
  recordingKind: StructuredPrototypeRecordingKind;
  headSequenceNo: number;
  stateHash: string;
  viewModelHash: string;
  stateJson: string;
  viewModelJson: string;
  runtimeCoreVersion: string;
  runtimeCoreBundleHash: string;
  stateMachineKernelVersion: string;
  checkpointId: string;
  checkpointSequenceNo: number;
  replayedEventBatchIds: string[];
}

export interface AppliedStructuredPrototypeRuntimeEvents extends StructuredPrototypeRuntimeSession {
  eventBatchId: string;
  outcome: RuntimeTransitionOutcome;
}

export interface CreateStructuredPrototypeRequest {
  contractVersion: 1;
  clientRequestId: string;
  document: NewStructuredPrototypeDocument;
}

export interface ApplyStructuredPrototypeCommandsRequest {
  contractVersion: 1;
  clientRequestId: string;
  expectedHeadSequenceNo: number;
  expectedDocumentHash: string;
  batch: StructuredPrototypeCommandBatch;
}

export interface CreateStructuredPrototypeRuntimeSessionRequest {
  contractVersion: 1;
  clientRequestId: string;
  scenarioId: string;
  recordingKind: StructuredPrototypeRecordingKind;
  actorSubjectId: string | null;
}

export interface ApplyStructuredPrototypeRuntimeEventsRequest {
  contractVersion: 1;
  clientRequestId: string;
  expectedHeadSequenceNo: number;
  expectedStateHash: string;
  batch: {
    clientEventId: string;
    expectedSequenceNo: number;
    events: RuntimeEvent[];
  };
}

export interface CheckpointStructuredPrototypeRuntimeSessionRequest {
  contractVersion: 1;
  clientRequestId: string;
}

export interface PublishStructuredPrototypeRequest {
  contractVersion: 1;
  clientRequestId: string;
  expectedHeadSequenceNo: number;
  expectedDocumentHash: string;
}

export interface StructuredPrototypePublication {
  contractVersion: 1;
  documentId: string;
  revisionId: string;
  revisionNo: number;
  renderRunId: string;
  artifactId: string;
  rendererVersion: string;
  documentHash: string;
  outputHash: string;
  outputManifestHash: string;
  visualPreflightReportHash: string;
  publishedAt: string;
  sharePath: string;
  artifactPath: string;
}

export interface PublishedStructuredPrototype extends StructuredPrototypePublication {
  operationId: string;
  correlationId: string;
  activeDraft: StructuredPrototypeDraft;
}

export type StructuredPrototypeGenerationJobStatus =
  | "queued"
  | "planning"
  | "awaiting_confirmation"
  | "generating"
  | "assembling"
  | "validating"
  | "rendering_preview"
  | "ready"
  | "accepted"
  | "failed"
  | "interrupted"
  | "cancelled";

export interface StructuredPrototypeGenerationBlueprint {
  contractVersion: 1;
  documentTitle: string;
  productIntent: string;
  outputLocale: "zh-CN";
  foundationIntent: {
    visualLanguage: string;
    density: "compact" | "comfortable";
    responsiveStrategy: string;
  };
  pages: Array<{
    pageKey: string;
    title: string;
    route: string;
    purpose: string;
    navigationGroupKey: string;
  }>;
  navigation: Array<{ key: string; label: string; targetPageKey: string }>;
  flowIntents: Array<{
    key: string;
    sourcePageKey: string;
    sourceNodeKey: string;
    event: "click" | "submit" | "rowActivated";
    targetPageKey: string;
  }>;
  roleIntents: string[];
  entityIntents: string[];
  formIntents: string[];
  scenarioIntents: string[];
  startPageKeys: string[];
}

export interface StructuredPrototypeGenerationItem {
  id: string;
  runId: string;
  kind: "blueprint" | "foundation" | "page";
  itemKey: string;
  pageKey: string | null;
  status: "pending" | "generating" | "validating" | "done" | "failed" | "interrupted";
  phase: string;
  taskKind: string;
  operationId: string;
  contextObjectHash: string;
  outputObjectHash: string | null;
  submissionId: string | null;
  submissionNormalizedFields: string[];
  taskId: string | null;
  executionProcessId: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  updatedAt: string;
}

export interface StructuredPrototypeGenerationJob {
  contractVersion: 1;
  id: string;
  projectId: string;
  status: StructuredPrototypeGenerationJobStatus;
  operationId: string;
  blueprintVersion: number;
  blueprintHash: string | null;
  blueprint: StructuredPrototypeGenerationBlueprint | null;
  candidateObjectHash: string | null;
  previewArtifactId: string | null;
  previewOutputHash: string | null;
  replayManifestObjectHash: string | null;
  documentId: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  running: number;
  pending: number;
  items: StructuredPrototypeGenerationItem[];
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  canConfirm: boolean;
  canAccept: boolean;
  previewPath: string | null;
}

export interface StructuredPrototypeGenerationAcceptResult {
  contractVersion: 1;
  job: StructuredPrototypeGenerationJob;
  documentId: string;
  draftId: string;
  checkpointId: string;
  headSequenceNo: number;
  documentHash: string;
}

export type PrototypeAiEditRunStatus =
  | "queued"
  | "building_context"
  | "generating"
  | "validating"
  | "rendering_preview"
  | "preview_ready"
  | "completed_answer"
  | "completed_clarification"
  | "applied"
  | "rejected"
  | "stale"
  | "failed"
  | "interrupted";

export interface PrototypeAiSelection {
  scope: "selection" | "page" | "document" | "flow";
  pageId: string | null;
  selectedNodeIds: string[];
  flowId: string | null;
  viewport: "desktop" | "tablet" | "mobile";
}

export interface PrototypeAiThread {
  contractVersion: 1;
  id: string;
  documentId: string;
  title: string;
  status: "active" | "archived";
  createdAt: string;
  updatedAt: string;
}

export interface PrototypeAiMessage {
  id: string;
  role: "user" | "assistant";
  kind: "instruction" | "answer" | "clarification" | "proposal" | "error";
  content: string;
  runId: string | null;
  commandBatchId: string | null;
  status: "pending" | "completed" | "failed" | "rejected" | "applied";
  createdAt: string;
  updatedAt: string;
}

export interface PrototypeAiEditRun {
  contractVersion: 1;
  id: string;
  threadId: string;
  userMessageId: string;
  assistantMessageId: string | null;
  documentId: string;
  draftId: string;
  operationId: string;
  status: PrototypeAiEditRunStatus;
  baseHeadSequenceNo: number;
  baseDocumentHash: string;
  contextObjectHash: string | null;
  outcomeObjectHash: string | null;
  submissionId: string | null;
  submissionRequestHash: string | null;
  submissionAcceptedAt: string | null;
  replayManifestObjectHash: string | null;
  proposedCommandBatchHash: string | null;
  candidateObjectHash: string | null;
  previewRenderRunId: string | null;
  previewArtifactId: string | null;
  previewPath: string | null;
  summary: string | null;
  affectedEntityIds: string[];
  taskId: string | null;
  executionProcessId: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  canApply: boolean;
  canReject: boolean;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export interface PrototypeAiThreadSnapshot {
  contractVersion: 1;
  thread: PrototypeAiThread;
  messages: PrototypeAiMessage[];
  latestRun: PrototypeAiEditRun | null;
}

export interface SendPrototypeAiMessageRequest {
  contractVersion: 1;
  clientMessageId: string;
  draftId: string;
  expectedHeadSequenceNo: number;
  expectedDocumentHash: string;
  content: string;
  selection: PrototypeAiSelection;
}

export interface AppliedPrototypeAiProposal {
  contractVersion: 1;
  run: PrototypeAiEditRun;
  draft: StructuredPrototypeDraft;
  commandBatchId: string;
}
