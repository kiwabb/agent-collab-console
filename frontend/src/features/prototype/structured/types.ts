import type {
  RuntimeBehaviorRule,
  RuntimeDefinition,
  RuntimeEvent,
  RuntimeTransitionOutcome,
  RuntimeValue,
} from "../runtime/types";

export type StructuredPrototypeRecordingKind =
  "studio_preview" | "recorded_review" | "shared_preview";

export interface StructuredPrototypeLength {
  unit: "px" | "percent" | "rem" | "auto";
  value: string | null;
}

export interface StructuredPrototypeFreeformPosition {
  x: string;
  y: string;
}

interface StructuredPrototypeFreeformGridCommon {
  id: string;
  version: 1;
  visible: boolean;
  snapEnabled: boolean;
  origin: StructuredPrototypeFreeformPosition;
}

export interface StructuredPrototypeSquareGrid extends StructuredPrototypeFreeformGridCommon {
  type: "square";
  params: {
    size: string;
    colorTokenKey: string;
    opacity: string;
  };
}

export interface StructuredPrototypeAxisGrid extends StructuredPrototypeFreeformGridCommon {
  type: "columns" | "rows";
  params: {
    count: number;
    itemSize: string | null;
    gutter: string;
    margin: string;
    alignment: "stretch" | "start" | "center" | "end";
    colorTokenKey: string;
    opacity: string;
  };
}

export type StructuredPrototypeFreeformGrid =
  StructuredPrototypeSquareGrid | StructuredPrototypeAxisGrid;

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
  position?: StructuredPrototypeFreeformPosition;
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
  position?: StructuredPrototypeFreeformPosition | null;
}

export interface StructuredPrototypeResponsiveOverride {
  breakpoint: "sm" | "md" | "lg";
  layoutItem: Omit<StructuredPrototypeLayoutUpdate, "position">;
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

export interface StructuredPrototypeGridColumnOverride {
  minWidth: number;
  columns: number;
}

export interface StructuredPrototypeGridNode extends StructuredPrototypeNodeCommon {
  type: "Grid";
  columns: number;
  gap: number;
  padding: StructuredPrototypePadding;
  columnOverrides: StructuredPrototypeGridColumnOverride[];
  children: StructuredPrototypeNode[];
}

export interface StructuredPrototypeFormNode extends StructuredPrototypeNodeCommon {
  type: "Form";
  formDefinitionId: string;
  gap: number;
  padding: StructuredPrototypePadding;
  children: StructuredPrototypeNode[];
}

export interface StructuredPrototypeFreeformNode extends StructuredPrototypeNodeCommon {
  type: "Freeform";
  /** Empty grids are omitted from canonical JSON to preserve legacy document hashes. */
  grids?: StructuredPrototypeFreeformGrid[];
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
  formDefinitionId: string | null;
  formFieldId: string | null;
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
  fieldId: string | null;
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

export interface StructuredPrototypeDividerNode extends StructuredPrototypeNodeCommon {
  type: "Divider";
  spacing: number;
  tone: "default" | "muted";
}

export interface StructuredPrototypeBadgeNode extends StructuredPrototypeNodeCommon {
  type: "Badge";
  label: string;
  tone: "default" | "success" | "warning" | "danger";
  iconName: string | null;
}

export type StructuredPrototypeNode =
  | StructuredPrototypeStackNode
  | StructuredPrototypeGridNode
  | StructuredPrototypeFormNode
  | StructuredPrototypeFreeformNode
  | StructuredPrototypeTextNode
  | StructuredPrototypeInputNode
  | StructuredPrototypeButtonNode
  | StructuredPrototypeTableNode
  | StructuredPrototypeDividerNode
  | StructuredPrototypeBadgeNode;

export interface StructuredPrototypePage {
  id: string;
  key: string;
  title: string;
  route: string;
  viewport: { width: number; height: number };
  root: StructuredPrototypeNode;
}

interface StructuredPrototypeShellCommon {
  title: string;
  accentColorTokenKey: string;
  navigationBackgroundColorTokenKey: string;
  contentBackgroundColorTokenKey: string;
  surfaceColorTokenKey: string;
}

export interface StructuredPrototypeSidebarShell extends StructuredPrototypeShellCommon {
  kind: "sidebar";
  navigationWidth: number;
  expandedMinWidth: number;
}

export interface StructuredPrototypeTopbarShell extends StructuredPrototypeShellCommon {
  kind: "topbar";
}

export type StructuredPrototypeShell =
  StructuredPrototypeSidebarShell | StructuredPrototypeTopbarShell;

export interface StructuredPrototypeDocument {
  schemaVersion: 1;
  id: string;
  title: string;
  locale: "zh-CN" | "en-US";
  settings: {
    defaultViewport: "desktop" | "tablet" | "mobile";
    theme: "light" | "dark" | "system";
    shell: StructuredPrototypeShell;
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

export interface NewStructuredPrototypeGridNode extends NewStructuredPrototypeNodeCommon {
  type: "Grid";
  columns: number;
  gap: number;
  padding: StructuredPrototypePadding;
  columnOverrides: StructuredPrototypeGridColumnOverride[];
  children: NewStructuredPrototypeNode[];
}

export interface NewStructuredPrototypeFormNode extends NewStructuredPrototypeNodeCommon {
  type: "Form";
  formDefinitionId: string;
  gap: number;
  padding: StructuredPrototypePadding;
  children: NewStructuredPrototypeNode[];
}

export interface NewStructuredPrototypeFreeformNode extends NewStructuredPrototypeNodeCommon {
  type: "Freeform";
  grids?: StructuredPrototypeFreeformGrid[];
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
  formDefinitionId: string | null;
  formFieldId: string | null;
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

export interface NewStructuredPrototypeDividerNode extends NewStructuredPrototypeNodeCommon {
  type: "Divider";
  spacing: number;
  tone: "default" | "muted";
}

export interface NewStructuredPrototypeBadgeNode extends NewStructuredPrototypeNodeCommon {
  type: "Badge";
  label: string;
  tone: "default" | "success" | "warning" | "danger";
  iconName: string | null;
}

export type NewStructuredPrototypeNode =
  | NewStructuredPrototypeStackNode
  | NewStructuredPrototypeGridNode
  | NewStructuredPrototypeFormNode
  | NewStructuredPrototypeFreeformNode
  | NewStructuredPrototypeTextNode
  | NewStructuredPrototypeInputNode
  | NewStructuredPrototypeButtonNode
  | NewStructuredPrototypeTableNode
  | NewStructuredPrototypeDividerNode
  | NewStructuredPrototypeBadgeNode;

export type StructuredPrototypeNodeRef =
  { kind: "existing"; nodeId: string } | { kind: "new"; newNodeKey: string };

export type StructuredPrototypeBehaviorRuleDefinition = Omit<RuntimeBehaviorRule, "id">;

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
  | {
      kind: "stackLayout";
      direction: StructuredPrototypeStackNode["direction"];
      gap: number;
      align: StructuredPrototypeStackNode["align"];
      justify: StructuredPrototypeStackNode["justify"];
      padding: StructuredPrototypePadding;
    }
  | {
      kind: "gridLayout";
      columns: number;
      gap: number;
      padding: StructuredPrototypePadding;
      columnOverrides: StructuredPrototypeGridColumnOverride[];
    }
  | {
      kind: "formLayout";
      gap: number;
      padding: StructuredPrototypePadding;
    }
  | {
      kind: "freeformGrids";
      grids: StructuredPrototypeFreeformGrid[];
    }
  | {
      kind: "responsiveLayout";
      responsive: StructuredPrototypeResponsiveOverride[];
    }
  | { kind: "badgeTone"; tone: "default" | "success" | "warning" | "danger" }
  | {
      kind: "dividerStyle";
      spacing?: number | undefined;
      tone?: "default" | "muted" | undefined;
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
      targetPosition?: StructuredPrototypeFreeformPosition | null;
    }
  | { kind: "removeNode"; nodeId: string }
  | { kind: "updateNodeName"; nodeId: string; name: string }
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
  | { kind: "reorderPage"; pageId: string; targetIndex: number }
  | {
      kind: "addPage";
      afterPageId: string;
      newPageKey: string;
      title: string;
      includeInNavigation: boolean;
    }
  | { kind: "duplicatePage"; pageId: string; newPageKey: string; title: string }
  | { kind: "renamePage"; pageId: string; title: string }
  | { kind: "deletePage"; pageId: string }
  | { kind: "reorderNavigationItem"; itemId: string; targetIndex: number }
  | {
      kind: "setRuntimeFlowNodePosition";
      flowNodeId: string;
      x: number;
      y: number;
    }
  | {
      kind: "setRuntimeEntityField";
      scenarioId: string;
      schemaId: string;
      entityId: string;
      fieldId: string;
      value: RuntimeValue;
    }
  | {
      kind: "addBehaviorRule";
      newRuleKey: string;
      definition: StructuredPrototypeBehaviorRuleDefinition;
    }
  | {
      kind: "replaceBehaviorRule";
      ruleId: string;
      definition: StructuredPrototypeBehaviorRuleDefinition;
    }
  | { kind: "removeBehaviorRule"; ruleId: string };

export type StructuredPrototypeFreeformMoveEvidenceAxis = "x" | "y";
export type StructuredPrototypeFreeformMoveEvidenceWinner =
  "raw" | "alignment" | "spacing" | "grid";
export type StructuredPrototypeFreeformMoveEvidenceCandidateOutcome =
  "winner" | "farther" | "tiePriority" | "crossAxisInvalid";

export interface StructuredPrototypeFreeformMoveEvidencePoint {
  x: string;
  y: string;
}

export interface StructuredPrototypeFreeformMoveEvidenceBounds extends StructuredPrototypeFreeformMoveEvidencePoint {
  width: string;
  height: string;
}

export interface StructuredPrototypeFreeformMoveEvidenceSibling extends StructuredPrototypeFreeformMoveEvidenceBounds {
  nodeId: string;
}

interface StructuredPrototypeFreeformMoveEvidenceCandidateCommon {
  axis: StructuredPrototypeFreeformMoveEvidenceAxis;
  position: string;
  correction: string;
  distance: string;
  sortKey: string;
  outcome: StructuredPrototypeFreeformMoveEvidenceCandidateOutcome;
}

export interface StructuredPrototypeFreeformMoveAlignmentEvidenceCandidate extends StructuredPrototypeFreeformMoveEvidenceCandidateCommon {
  source: "alignment";
  coordinate: string;
  movingAnchor: "left" | "center" | "right" | "top" | "middle" | "bottom";
  targetAnchor: "left" | "center" | "right" | "top" | "middle" | "bottom";
  targetKind: "container" | "sibling";
  targetNodeId: string | null;
}

export interface StructuredPrototypeFreeformMoveSpacingEvidenceCandidate extends StructuredPrototypeFreeformMoveEvidenceCandidateCommon {
  source: "spacing";
  placement: "before" | "between" | "after";
  gap: string;
  referenceNodeIds: [string, string];
}

export interface StructuredPrototypeFreeformMoveGridEvidenceCandidate extends StructuredPrototypeFreeformMoveEvidenceCandidateCommon {
  source: "grid";
  gridId: string;
  gridType: StructuredPrototypeFreeformGrid["type"];
  gridLineIndex: number;
  coordinate: string;
  movingAnchor: "left" | "center" | "right" | "top" | "middle" | "bottom";
}

export type StructuredPrototypeFreeformMoveEvidenceCandidate =
  | StructuredPrototypeFreeformMoveAlignmentEvidenceCandidate
  | StructuredPrototypeFreeformMoveSpacingEvidenceCandidate
  | StructuredPrototypeFreeformMoveGridEvidenceCandidate;

export interface StructuredPrototypeFreeformMoveEvidence {
  evidenceVersion: 2;
  kind: "freeformMove";
  snapSolverVersion: "structured-prototype-freeform-snap/v1";
  snapSolverSourceHash: string;
  documentId: string;
  draftId: string;
  freeformId: string;
  baseHeadSequenceNo: number;
  baseDocumentHash: string;
  selectedNodeIds: string[];
  grids: StructuredPrototypeFreeformGrid[];
  gridListHash: string;
  gridSnappingEnabled: boolean;
  previewScale: string;
  clientThreshold: "6";
  selectionBounds: StructuredPrototypeFreeformMoveEvidenceBounds;
  directSiblings: StructuredPrototypeFreeformMoveEvidenceSibling[];
  containerSize: { width: string; height: string };
  requestedDelta: StructuredPrototypeFreeformMoveEvidencePoint;
  rawPosition: StructuredPrototypeFreeformMoveEvidencePoint;
  finalPosition: StructuredPrototypeFreeformMoveEvidencePoint;
  correction: StructuredPrototypeFreeformMoveEvidencePoint;
  bypassSnapping: boolean;
  axisWinners: {
    x: StructuredPrototypeFreeformMoveEvidenceWinner;
    y: StructuredPrototypeFreeformMoveEvidenceWinner;
  };
  candidates: StructuredPrototypeFreeformMoveEvidenceCandidate[];
  terminalReason: "pointerup";
}

export interface StructuredPrototypeCommandBatch {
  commandContractVersion: 1;
  commands: StructuredPrototypeCommand[];
  summary: string;
  evidence?: StructuredPrototypeFreeformMoveEvidence;
}

export interface StructuredPrototypeDraft {
  contractVersion: 1;
  operationId: string;
  correlationId: string;
  documentId: string;
  draftId: string;
  headSequenceNo: number;
  documentHash: string;
  canUndo: boolean;
  canRedo: boolean;
  document: StructuredPrototypeDocument;
}

export interface DeleteStructuredPrototypeResult {
  contractVersion: 1;
  operationId: string;
  correlationId: string;
  deleted: boolean;
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
  pinnedDocumentObjectHash: string;
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
  replacesSessionId: string | null;
  resetManifestHash: string | null;
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

export interface MutateStructuredPrototypeHistoryRequest {
  contractVersion: 1;
  clientRequestId: string;
  expectedHeadSequenceNo: number;
  expectedDocumentHash: string;
}

export interface CreateStructuredPrototypeRuntimeSessionRequest {
  contractVersion: 1;
  clientRequestId: string;
  scenarioId: string;
  recordingKind: StructuredPrototypeRecordingKind;
  actorSubjectId: string | null;
}

export interface ResetStructuredPrototypeRuntimeSessionRequest {
  contractVersion: 1;
  clientRequestId: string;
  causeOperationId: string | null;
  expectedOldHeadSequenceNo: number;
  expectedOldStateHash: string;
  expectedOldViewModelHash: string;
  expectedOldRuntimeCoreBundleHash: string;
  targetDraftId: string;
  expectedTargetHeadSequenceNo: number;
  expectedTargetDocumentHash: string;
  scenarioId: string;
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
  summary?: string | null;
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

export type StructuredPrototypeRevisionSource = "user" | "ai" | "initial_generation";

export interface StructuredPrototypePublishedRevision {
  revisionId: string;
  revisionNo: number;
  summary: string;
  source: StructuredPrototypeRevisionSource;
  isCurrent: boolean;
  renderRunId: string;
  artifactId: string;
  rendererVersion: string;
  documentHash: string;
  outputHash: string;
  publishedAt: string;
  artifactPath: string;
}

export interface StructuredPrototypePublicationEvent {
  kind: "publish" | "rollback";
  revisionNo: number;
  occurredAt: string;
  summary: string | null;
}

export interface StructuredPrototypeRevisionHistory {
  contractVersion: 1;
  documentId: string;
  currentRevisionNo: number | null;
  revisions: StructuredPrototypePublishedRevision[];
  events: StructuredPrototypePublicationEvent[];
}

export interface StructuredPrototypeRevisionDiffPage {
  id: string;
  title: string;
  route: string;
}

export interface StructuredPrototypeRevisionDiffPageChange
  extends StructuredPrototypeRevisionDiffPage {
  titleChanged: boolean;
  routeChanged: boolean;
  nodesAdded: number;
  nodesRemoved: number;
  nodesModified: number;
}

export interface StructuredPrototypeRevisionDiff {
  contractVersion: 1;
  documentId: string;
  baseRevisionNo: number;
  targetRevisionNo: number;
  identical: boolean;
  titleFrom: string | null;
  titleTo: string | null;
  pagesAdded: StructuredPrototypeRevisionDiffPage[];
  pagesRemoved: StructuredPrototypeRevisionDiffPage[];
  pagesModified: StructuredPrototypeRevisionDiffPageChange[];
  flowsAdded: number;
  flowsRemoved: number;
  flowsModified: number;
  componentDefinitionsChanged: boolean;
  settingsChanged: boolean;
  tokensChanged: boolean;
  navigationChanged: boolean;
  runtimeChanged: boolean;
  assetRefsAdded: number;
  assetRefsRemoved: number;
}

export interface RollbackStructuredPrototypeRequest {
  contractVersion: 1;
  clientRequestId: string;
  targetRevisionNo: number;
  expectedCurrentRevisionNo: number;
}

export interface RolledBackStructuredPrototype extends StructuredPrototypePublication {
  operationId: string;
  correlationId: string;
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

export type StructuredPrototypeGenerationRuntimeValue =
  | { type: "null" }
  | { type: "boolean"; value: boolean }
  | { type: "integer"; value: number }
  | { type: "string"; value: string }
  | { type: "enum"; value: string };

export type StructuredPrototypeGenerationEntityRefExpression =
  { kind: "variable"; variableKey: string } | { kind: "eventEntityRef" };

export type StructuredPrototypeGenerationExpression =
  | { kind: "literal"; value: StructuredPrototypeGenerationRuntimeValue }
  | { kind: "variable"; variableKey: string }
  | { kind: "formField"; formKey: string; fieldKey: string }
  | { kind: "eventEntityRef" }
  | {
      kind: "entityField";
      entityRef: StructuredPrototypeGenerationEntityRefExpression;
      schemaKey: string;
      fieldKey: string;
      fallback: StructuredPrototypeGenerationRuntimeValue;
    };

export type StructuredPrototypeGenerationPredicate =
  | { kind: "all"; items: StructuredPrototypeGenerationPredicate[] }
  | { kind: "roleIs"; roleKey: string }
  | { kind: "formValid"; formKey: string }
  | {
      kind: "compare";
      operator: "eq" | "ne";
      left: StructuredPrototypeGenerationExpression;
      right: StructuredPrototypeGenerationExpression;
    };

interface StructuredPrototypeGenerationFieldAssignment {
  fieldKey: string;
  value: StructuredPrototypeGenerationExpression;
}

export type StructuredPrototypeGenerationEffect =
  | {
      kind: "setVariable";
      variableKey: string;
      value: StructuredPrototypeGenerationExpression;
    }
  | { kind: "validateForm"; formKey: string }
  | {
      kind: "createEntity";
      schemaKey: string;
      resultVariableKey: string;
      values: StructuredPrototypeGenerationFieldAssignment[];
    }
  | {
      kind: "updateEntity";
      schemaKey: string;
      entityRef: StructuredPrototypeGenerationEntityRefExpression;
      updates: StructuredPrototypeGenerationFieldAssignment[];
    }
  | { kind: "navigate"; targetPageKey: string }
  | {
      kind: "notify";
      level: "info" | "success" | "warning" | "error";
      message: string;
    };

export type StructuredPrototypeGenerationViewBindingIntent =
  | {
      key: string;
      pageKey: string;
      target: "textContent";
      value: StructuredPrototypeGenerationExpression;
    }
  | {
      key: string;
      pageKey: string;
      target: "visibility";
      predicate: StructuredPrototypeGenerationPredicate;
    }
  | {
      key: string;
      pageKey: string;
      target: "tableRows";
      schemaKey: string;
      sortFieldKey: string | null;
      sortDirection: "asc" | "desc";
    };

export type StructuredPrototypeGenerationScenarioStep =
  | {
      kind: "commitFormField";
      pageKey: string;
      formKey: string;
      fieldKey: string;
      value: Extract<StructuredPrototypeGenerationRuntimeValue, { type: "string" | "integer" }>;
      expectedOutcome: "applied" | "guard_false" | "validation_failed";
    }
  | {
      kind: "activateBehavior";
      behaviorIntentKey: string;
      expectedOutcome: "applied" | "guard_false" | "validation_failed";
    }
  | {
      kind: "activateEntityBehavior";
      behaviorIntentKey: string;
      schemaKey: string;
      entityKey: string;
      expectedOutcome: "applied" | "guard_false" | "validation_failed";
    }
  | {
      kind: "switchRole";
      roleKey: string;
      expectedOutcome: "applied" | "guard_false" | "validation_failed";
    };

export interface StructuredPrototypeGenerationBlueprint {
  contractVersion: 3;
  documentTitle: string;
  productIntent: string;
  outputLocale: "zh-CN" | "en-US";
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
    behaviorIntentKey: string;
    targetPageKey: string;
  }>;
  roleIntents: Array<{ key: string; label: string }>;
  entityIntents: Array<{
    key: string;
    fields: Array<{
      key: string;
      valueType: "boolean" | "integer" | "string" | "enum";
      nullable: boolean;
    }>;
  }>;
  variableIntents: Array<{
    key: string;
    valueType: "null" | "boolean" | "integer" | "string" | "enum" | "entityRef";
    nullable: boolean;
    entitySchemaKey: string | null;
    defaultValue: StructuredPrototypeGenerationRuntimeValue;
  }>;
  formIntents: Array<{
    key: string;
    pageKey: string;
    fields: Array<{
      key: string;
      valueType: "string" | "integer";
      initialValue: Extract<
        StructuredPrototypeGenerationRuntimeValue,
        { type: "string" | "integer" }
      >;
      required: boolean;
      minInteger: number | null;
    }>;
  }>;
  viewBindingIntents: StructuredPrototypeGenerationViewBindingIntent[];
  behaviorIntents: Array<{
    key: string;
    sourcePageKey: string;
    guard: StructuredPrototypeGenerationPredicate | null;
    effects: StructuredPrototypeGenerationEffect[];
    guardFalseEffects: StructuredPrototypeGenerationEffect[];
  }>;
  scenarioIntents: Array<{
    key: string;
    actorRoleKey: string;
    startPageKey: string;
    initialVariables: Array<{
      variableKey: string;
      value: StructuredPrototypeGenerationRuntimeValue;
    }>;
    entityFixtures: Array<{
      schemaKey: string;
      entities: Array<{
        key: string;
        fields: Array<{
          fieldKey: string;
          value: StructuredPrototypeGenerationRuntimeValue;
        }>;
      }>;
    }>;
    allowSimulatedRoleSwitch: boolean;
    scriptedSteps: StructuredPrototypeGenerationScenarioStep[];
    milestones: Array<{
      afterStep: number;
      currentPageKey: string | null;
      variableValues: Array<{
        variableKey: string;
        value: StructuredPrototypeGenerationRuntimeValue;
      }>;
      entityFieldValues: Array<{
        schemaKey: string;
        entityKey: string;
        fieldKey: string;
        value: StructuredPrototypeGenerationRuntimeValue;
      }>;
    }>;
  }>;
  startPageKeys: string[];
}

export interface StructuredPrototypeGenerationItem {
  id: string;
  runId: string;
  kind: "blueprint" | "foundation" | "page";
  itemKey: string;
  pageKey: string | null;
  itemOrdinal: number;
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
  sourcePolicy: "committed_head_v1" | null;
  sourceSnapshotObjectHash: string | null;
  sourceFingerprint: string | null;
  sourceSnapshotRef: string | null;
  repositoryObjectFormat: string | null;
  worktreeBaseCommit: string | null;
  repositoryProjectPrefix: string | null;
  repositoryTreeObjectId: string | null;
  workingTreeDirty: boolean | null;
  excludedTrackedChangeCount: number | null;
  excludedUntrackedCount: number | null;
  sourceFileExclusionPolicy: "dotenv_checkout_filter_v1" | null;
  excludedSensitiveFileCount: number | null;
  excludedStatusHash: string | null;
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
  operationId: string;
  correlationId: string;
  job: StructuredPrototypeGenerationJob;
  documentId: string;
  draftId: string;
  checkpointId: string;
  headSequenceNo: number;
  documentHash: string;
}

export interface StructuredPrototypeGenerationConfirmResult {
  contractVersion: 1;
  operationId: string;
  correlationId: string;
  job: StructuredPrototypeGenerationJob;
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
