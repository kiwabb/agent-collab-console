import { isRecord, safeJsonParse } from "@/lib/utils";
import type {
  PrototypeGenerationItemPhase,
  PrototypeGenerationItemStatus,
  PrototypeGenerationRun,
  PrototypeGenerationRunItem,
  PrototypeGenerationRunStatus,
  PrototypePlan,
  PrototypePlanAction,
  PrototypePlanAnalysisPhase,
  PrototypePlanConfidence,
  PrototypePlanDiscoveryOrigin,
  PrototypePlanEvidence,
  PrototypePlanEvidenceKind,
  PrototypePlanItem,
  PrototypePlanOutputLocale,
  PrototypePlanReviewStatus,
  PrototypePlanScope,
  PrototypePlanStatus,
  PrototypePlanSurfaceKind,
  PrototypeProjectContext,
  PrototypeStreamHeartbeat,
} from "@/lib/types";

export interface FailedPrototypeStreamItem {
  prototype_id: string;
  message: string;
}

const PLAN_KEYS = [
  "contract_version",
  "id",
  "project_id",
  "status",
  "repository_fingerprint",
  "scope",
  "project_context",
  "global_instruction",
  "output_locale",
  "analysis_phase",
  "analysis_completed",
  "analysis_total",
  "diagnostics",
  "error_message",
  "created_at",
  "updated_at",
  "items",
] as const;

const PLAN_ITEM_KEYS = [
  "id",
  "plan_id",
  "candidate_id",
  "package_root",
  "surface_kind",
  "route_patterns",
  "primary_source_path",
  "source_paths",
  "layout_paths",
  "title",
  "summary",
  "brief",
  "states",
  "evidence_ids",
  "evidence",
  "confidence",
  "action",
  "selected",
  "source_hash",
  "discovery_origin",
  "review_status",
  "prototype_id",
  "created_at",
  "updated_at",
] as const;

const EVIDENCE_KEYS = [
  "evidence_id",
  "kind",
  "path",
  "start_line",
  "end_line",
  "detail",
  "content",
  "confidence",
  "diagnostic",
] as const;

const GENERATION_RUN_KEYS = [
  "contract_version",
  "id",
  "plan_id",
  "project_id",
  "status",
  "repository_fingerprint",
  "total",
  "processed",
  "succeeded",
  "running",
  "pending",
  "completed",
  "failed",
  "error_message",
  "started_at",
  "completed_at",
  "created_at",
  "updated_at",
  "items",
] as const;

const GENERATION_ITEM_KEYS = [
  "id",
  "run_id",
  "plan_item_id",
  "prototype_id",
  "status",
  "title",
  "attempt",
  "phase",
  "output_chars",
  "last_event_at",
  "status_message",
  "task_id",
  "execution_process_id",
  "error_message",
  "version_no",
  "started_at",
  "completed_at",
  "created_at",
  "updated_at",
] as const;

const PROJECT_CONTEXT_KEYS = [
  "product_summary",
  "audience",
  "visual_language",
  "shared_layout",
] as const;

const PLAN_SCOPE_KEYS = ["packages", "supported_packages", "candidate_count"] as const;
const HEARTBEAT_KEYS = ["contract_version", "resource_id", "sent_at"] as const;

function hasEventData(event: Event): event is Event & { data: unknown } {
  return "data" in event;
}

function eventData(event: Event): unknown {
  return hasEventData(event) ? event.data : null;
}

function hasExactKeys(record: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(record);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

function readString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function readNullableString(
  record: Record<string, unknown>,
  key: string,
): string | null | undefined {
  const value = record[key];
  return typeof value === "string" || value === null ? value : undefined;
}

function readNullableTimestamp(
  record: Record<string, unknown>,
  key: string,
): string | null | undefined {
  const value = readNullableString(record, key);
  if (typeof value !== "string") return value;
  return Number.isFinite(Date.parse(value)) ? value : undefined;
}

function readBoolean(record: Record<string, unknown>, key: string): boolean | null {
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

function readNonNegativeInteger(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function readPositiveInteger(record: Record<string, unknown>, key: string): number | null {
  const value = readNonNegativeInteger(record, key);
  return value !== null && value > 0 ? value : null;
}

function readNullableNonNegativeInteger(
  record: Record<string, unknown>,
  key: string,
): number | null | undefined {
  const value = record[key];
  if (value === null) return null;
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function readStringArrayValue(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

function parseArray<T>(value: unknown, parseItem: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const parsed: T[] = [];
  for (const item of value) {
    const next = parseItem(item);
    if (next === null) return null;
    parsed.push(next);
  }
  return parsed;
}

function isPlanStatus(value: string): value is PrototypePlanStatus {
  return (
    value === "queued" ||
    value === "analyzing" ||
    value === "ready" ||
    value === "analysis_failed" ||
    value === "stale" ||
    value === "interrupted"
  );
}

function isAnalysisPhase(value: string): value is PrototypePlanAnalysisPhase {
  return (
    value === "queued" ||
    value === "scanning" ||
    value === "planning" ||
    value === "validating" ||
    value === "complete" ||
    value === "stale" ||
    value === "failed"
  );
}

function isOutputLocale(value: string): value is PrototypePlanOutputLocale {
  return value === "zh-CN" || value === "en-US";
}

function isPlanConfidence(value: string): value is PrototypePlanConfidence {
  return value === "high" || value === "medium" || value === "low";
}

function isPlanDiscoveryOrigin(value: string): value is PrototypePlanDiscoveryOrigin {
  return value === "static" || value === "claude";
}

function isPlanReviewStatus(value: string): value is PrototypePlanReviewStatus {
  return value === "provisional" || value === "confirmed" || value === "needs_confirmation";
}

function isPlanEvidenceKind(value: string): value is PrototypePlanEvidenceKind {
  return (
    value === "react-router-route" ||
    value === "vue-router-route" ||
    value === "file-route" ||
    value === "page-directory" ||
    value === "page-source" ||
    value === "layout" ||
    value === "style" ||
    value === "parser"
  );
}

function isPlanAction(value: string): value is PrototypePlanAction {
  return (
    value === "create" ||
    value === "update" ||
    value === "unchanged" ||
    value === "missing" ||
    value === "unsupported"
  );
}

function isPlanSurfaceKind(value: string): value is PrototypePlanSurfaceKind {
  return (
    value === "web" ||
    value === "desktop" ||
    value === "browser-extension" ||
    value === "mobile" ||
    value === "unknown"
  );
}

function isGenerationRunStatus(value: string): value is PrototypeGenerationRunStatus {
  return (
    value === "queued" ||
    value === "running" ||
    value === "completed" ||
    value === "partial" ||
    value === "failed" ||
    value === "interrupted"
  );
}

function isGenerationItemStatus(value: string): value is PrototypeGenerationItemStatus {
  return (
    value === "pending" ||
    value === "generating" ||
    value === "done" ||
    value === "failed" ||
    value === "interrupted" ||
    value === "skipped"
  );
}

function isGenerationItemPhase(value: string): value is PrototypeGenerationItemPhase {
  return (
    value === "queued" ||
    value === "starting" ||
    value === "streaming" ||
    value === "persisting" ||
    value === "completed" ||
    value === "failed" ||
    value === "interrupted" ||
    value === "skipped"
  );
}

interface GenerationItemLifecycle {
  status: PrototypeGenerationItemStatus;
  phase: PrototypeGenerationItemPhase;
  lastEventAt: string | null;
  errorMessage: string | null;
  versionNo: number | null;
  startedAt: string | null;
  completedAt: string | null;
}

function hasValidGenerationItemLifecycle(lifecycle: GenerationItemLifecycle): boolean {
  const { status, phase, lastEventAt, errorMessage, versionNo, startedAt, completedAt } = lifecycle;
  if (lastEventAt === null) return false;

  switch (status) {
    case "pending":
      return (
        phase === "queued" &&
        errorMessage === null &&
        versionNo === null &&
        startedAt === null &&
        completedAt === null
      );
    case "generating":
      return (
        (phase === "starting" || phase === "streaming" || phase === "persisting") &&
        errorMessage === null &&
        versionNo === null &&
        startedAt !== null &&
        completedAt === null
      );
    case "done":
      return (
        phase === "completed" &&
        errorMessage === null &&
        versionNo !== null &&
        versionNo > 0 &&
        startedAt !== null &&
        completedAt !== null
      );
    case "failed":
      return (
        phase === "failed" &&
        errorMessage !== null &&
        errorMessage.trim().length > 0 &&
        versionNo === null &&
        completedAt !== null
      );
    case "interrupted":
      return (
        phase === "interrupted" &&
        errorMessage !== null &&
        errorMessage.trim().length > 0 &&
        versionNo === null &&
        completedAt !== null
      );
    case "skipped":
      return (
        phase === "skipped" && errorMessage === null && versionNo === null && completedAt !== null
      );
  }
}

function readProjectContext(value: unknown): PrototypeProjectContext | null {
  if (!isRecord(value)) return null;
  if (!hasExactKeys(value, PROJECT_CONTEXT_KEYS)) return null;
  const productSummary = readString(value, "product_summary");
  const audience = readString(value, "audience");
  const visualLanguage = readString(value, "visual_language");
  const sharedLayout = readString(value, "shared_layout");
  if (
    productSummary === null ||
    audience === null ||
    visualLanguage === null ||
    sharedLayout === null
  ) {
    return null;
  }
  return {
    product_summary: productSummary,
    audience,
    visual_language: visualLanguage,
    shared_layout: sharedLayout,
  };
}

function readPlanScope(value: unknown): PrototypePlanScope | null {
  if (!isRecord(value)) return null;
  if (!hasExactKeys(value, PLAN_SCOPE_KEYS)) return null;
  const packages = readStringArrayValue(value["packages"]);
  const supportedPackages = readStringArrayValue(value["supported_packages"]);
  const candidateCount = readNonNegativeInteger(value, "candidate_count");
  if (!packages || !supportedPackages || candidateCount === null) return null;
  return {
    packages,
    supported_packages: supportedPackages,
    candidate_count: candidateCount,
  };
}

function readPlanEvidence(value: unknown): PrototypePlanEvidence | null {
  if (!isRecord(value) || !hasExactKeys(value, EVIDENCE_KEYS)) return null;
  const evidenceId = readString(value, "evidence_id");
  const kind = readString(value, "kind");
  const path = readString(value, "path");
  const startLine = readPositiveInteger(value, "start_line");
  const endLine = readPositiveInteger(value, "end_line");
  const detail = readString(value, "detail");
  const content = readString(value, "content");
  const confidence = readString(value, "confidence");
  const diagnostic = readNullableString(value, "diagnostic");
  if (
    !evidenceId ||
    evidenceId.length > 200 ||
    !kind ||
    !isPlanEvidenceKind(kind) ||
    !path ||
    path.length > 2_000 ||
    startLine === null ||
    endLine === null ||
    endLine < startLine ||
    detail === null ||
    detail.length > 4_000 ||
    content === null ||
    content.length > 12_000 ||
    confidence === null ||
    !isPlanConfidence(confidence) ||
    diagnostic === undefined ||
    (diagnostic !== null && diagnostic.length > 4_000)
  ) {
    return null;
  }
  return {
    evidence_id: evidenceId,
    kind,
    path,
    start_line: startLine,
    end_line: endLine,
    detail,
    content,
    confidence,
    diagnostic,
  };
}

function readPlanItem(value: unknown): PrototypePlanItem | null {
  if (!isRecord(value) || !hasExactKeys(value, PLAN_ITEM_KEYS)) return null;
  const id = readString(value, "id");
  const planId = readString(value, "plan_id");
  const candidateId = readString(value, "candidate_id");
  const packageRoot = readString(value, "package_root");
  const surfaceKind = readString(value, "surface_kind");
  const routePatterns = readStringArrayValue(value["route_patterns"]);
  const primarySourcePath = readNullableString(value, "primary_source_path");
  const sourcePaths = readStringArrayValue(value["source_paths"]);
  const layoutPaths = readStringArrayValue(value["layout_paths"]);
  const title = readString(value, "title");
  const summary = readString(value, "summary");
  const brief = readString(value, "brief");
  const states = readStringArrayValue(value["states"]);
  const evidenceIds = readStringArrayValue(value["evidence_ids"]);
  const evidence = parseArray(value["evidence"], readPlanEvidence);
  const confidence = readString(value, "confidence");
  const action = readString(value, "action");
  const selected = readBoolean(value, "selected");
  const sourceHash = readString(value, "source_hash");
  const discoveryOrigin = readString(value, "discovery_origin");
  const reviewStatus = readString(value, "review_status");
  const prototypeId = readNullableString(value, "prototype_id");
  const createdAt = readNullableTimestamp(value, "created_at");
  const updatedAt = readNullableTimestamp(value, "updated_at");
  if (
    !id ||
    !planId ||
    !candidateId ||
    packageRoot === null ||
    surfaceKind === null ||
    !isPlanSurfaceKind(surfaceKind) ||
    !routePatterns ||
    primarySourcePath === undefined ||
    !sourcePaths ||
    !layoutPaths ||
    !title ||
    !summary ||
    !brief ||
    !states ||
    !evidenceIds ||
    !evidence ||
    confidence === null ||
    !isPlanConfidence(confidence) ||
    action === null ||
    !isPlanAction(action) ||
    selected === null ||
    sourceHash === null ||
    discoveryOrigin === null ||
    !isPlanDiscoveryOrigin(discoveryOrigin) ||
    reviewStatus === null ||
    !isPlanReviewStatus(reviewStatus) ||
    (sourceHash.length === 0 && action !== "missing") ||
    prototypeId === undefined ||
    createdAt === undefined ||
    updatedAt === undefined
  ) {
    return null;
  }
  const knownEvidenceIds = new Set(evidence.map((item) => item.evidence_id));
  const requiresReferencedEvidence =
    action === "create" || action === "update" || action === "unchanged";
  if (
    knownEvidenceIds.size !== evidence.length ||
    new Set(evidenceIds).size !== evidenceIds.length ||
    (requiresReferencedEvidence && evidenceIds.length === 0) ||
    !evidenceIds.every((evidenceId) => knownEvidenceIds.has(evidenceId))
  ) {
    return null;
  }
  return {
    id,
    plan_id: planId,
    candidate_id: candidateId,
    package_root: packageRoot,
    surface_kind: surfaceKind,
    route_patterns: routePatterns,
    primary_source_path: primarySourcePath,
    source_paths: sourcePaths,
    layout_paths: layoutPaths,
    title,
    summary,
    brief,
    states,
    evidence_ids: evidenceIds,
    evidence,
    confidence,
    action,
    selected,
    source_hash: sourceHash,
    discovery_origin: discoveryOrigin,
    review_status: reviewStatus,
    prototype_id: prototypeId,
    created_at: createdAt,
    updated_at: updatedAt,
  };
}

function readPrototypePlan(value: unknown): PrototypePlan | null {
  if (!isRecord(value) || !hasExactKeys(value, PLAN_KEYS) || value["contract_version"] !== 1) {
    return null;
  }
  const id = readString(value, "id");
  const projectId = readString(value, "project_id");
  const status = readString(value, "status");
  const repositoryFingerprint = readString(value, "repository_fingerprint");
  const scope = readPlanScope(value["scope"]);
  const projectContext = readProjectContext(value["project_context"]);
  const globalInstruction = readString(value, "global_instruction");
  const outputLocale = readString(value, "output_locale");
  const analysisPhase = readString(value, "analysis_phase");
  const analysisCompleted = readNonNegativeInteger(value, "analysis_completed");
  const analysisTotal = readNonNegativeInteger(value, "analysis_total");
  const diagnostics = readStringArrayValue(value["diagnostics"]);
  const errorMessage = readNullableString(value, "error_message");
  const createdAt = readNullableTimestamp(value, "created_at");
  const updatedAt = readNullableTimestamp(value, "updated_at");
  const items = parseArray(value["items"], readPlanItem);
  if (
    !id ||
    !projectId ||
    status === null ||
    !isPlanStatus(status) ||
    !repositoryFingerprint ||
    !scope ||
    !projectContext ||
    globalInstruction === null ||
    outputLocale === null ||
    !isOutputLocale(outputLocale) ||
    analysisPhase === null ||
    !isAnalysisPhase(analysisPhase) ||
    analysisCompleted === null ||
    analysisTotal === null ||
    analysisCompleted > analysisTotal ||
    !diagnostics ||
    errorMessage === undefined ||
    createdAt === undefined ||
    updatedAt === undefined ||
    !items ||
    items.some((item) => item.plan_id !== id)
  ) {
    return null;
  }
  return {
    contract_version: 1,
    id,
    project_id: projectId,
    status,
    repository_fingerprint: repositoryFingerprint,
    scope,
    project_context: projectContext,
    global_instruction: globalInstruction,
    output_locale: outputLocale,
    analysis_phase: analysisPhase,
    analysis_completed: analysisCompleted,
    analysis_total: analysisTotal,
    diagnostics,
    error_message: errorMessage,
    created_at: createdAt,
    updated_at: updatedAt,
    items,
  };
}

function readGenerationRunItem(value: unknown): PrototypeGenerationRunItem | null {
  if (!isRecord(value) || !hasExactKeys(value, GENERATION_ITEM_KEYS)) return null;
  const id = readString(value, "id");
  const runId = readString(value, "run_id");
  const planItemId = readString(value, "plan_item_id");
  const prototypeId = readNullableString(value, "prototype_id");
  const status = readString(value, "status");
  const title = readString(value, "title");
  const attempt = readNonNegativeInteger(value, "attempt");
  const phase = readString(value, "phase");
  const outputChars = readNonNegativeInteger(value, "output_chars");
  const lastEventAt = readNullableTimestamp(value, "last_event_at");
  const statusMessage = readString(value, "status_message");
  const taskId = readNullableString(value, "task_id");
  const executionProcessId = readNullableString(value, "execution_process_id");
  const errorMessage = readNullableString(value, "error_message");
  const versionNo = readNullableNonNegativeInteger(value, "version_no");
  const startedAt = readNullableTimestamp(value, "started_at");
  const completedAt = readNullableTimestamp(value, "completed_at");
  const createdAt = readNullableTimestamp(value, "created_at");
  const updatedAt = readNullableTimestamp(value, "updated_at");
  if (
    !id ||
    !runId ||
    !planItemId ||
    prototypeId === undefined ||
    status === null ||
    !isGenerationItemStatus(status) ||
    title === null ||
    attempt === null ||
    phase === null ||
    !isGenerationItemPhase(phase) ||
    outputChars === null ||
    lastEventAt === undefined ||
    statusMessage === null ||
    taskId === undefined ||
    executionProcessId === undefined ||
    errorMessage === undefined ||
    versionNo === undefined ||
    startedAt === undefined ||
    completedAt === undefined ||
    createdAt === undefined ||
    updatedAt === undefined ||
    !hasValidGenerationItemLifecycle({
      status,
      phase,
      lastEventAt,
      errorMessage,
      versionNo,
      startedAt,
      completedAt,
    })
  ) {
    return null;
  }
  return {
    id,
    run_id: runId,
    plan_item_id: planItemId,
    prototype_id: prototypeId,
    status,
    title,
    attempt,
    phase,
    output_chars: outputChars,
    last_event_at: lastEventAt,
    status_message: statusMessage,
    task_id: taskId,
    execution_process_id: executionProcessId,
    error_message: errorMessage,
    version_no: versionNo,
    started_at: startedAt,
    completed_at: completedAt,
    created_at: createdAt,
    updated_at: updatedAt,
  };
}

function countGenerationStatuses(items: PrototypeGenerationRunItem[]) {
  let succeeded = 0;
  let failed = 0;
  let skipped = 0;
  let running = 0;
  let pending = 0;
  for (const item of items) {
    if (item.status === "done") succeeded += 1;
    else if (item.status === "generating") running += 1;
    else if (item.status === "pending") pending += 1;
    else if (item.status === "skipped") skipped += 1;
    else failed += 1;
  }
  return {
    processed: succeeded + failed + skipped,
    succeeded,
    failed,
    skipped,
    running,
    pending,
  };
}

function readCurrentGenerationRun(value: Record<string, unknown>): PrototypeGenerationRun | null {
  if (!hasExactKeys(value, GENERATION_RUN_KEYS) || value["contract_version"] !== 1) return null;
  const id = readString(value, "id");
  const planId = readString(value, "plan_id");
  const projectId = readString(value, "project_id");
  const status = readString(value, "status");
  const repositoryFingerprint = readString(value, "repository_fingerprint");
  const total = readNonNegativeInteger(value, "total");
  const processed = readNonNegativeInteger(value, "processed");
  const succeeded = readNonNegativeInteger(value, "succeeded");
  const running = readNonNegativeInteger(value, "running");
  const pending = readNonNegativeInteger(value, "pending");
  const completed = readNonNegativeInteger(value, "completed");
  const failed = readNonNegativeInteger(value, "failed");
  const errorMessage = readNullableString(value, "error_message");
  const startedAt = readNullableTimestamp(value, "started_at");
  const completedAt = readNullableTimestamp(value, "completed_at");
  const createdAt = readNullableTimestamp(value, "created_at");
  const updatedAt = readNullableTimestamp(value, "updated_at");
  const items = parseArray(value["items"], readGenerationRunItem);
  if (
    !id ||
    !planId ||
    !projectId ||
    status === null ||
    !isGenerationRunStatus(status) ||
    !repositoryFingerprint ||
    total === null ||
    processed === null ||
    succeeded === null ||
    running === null ||
    pending === null ||
    completed === null ||
    failed === null ||
    errorMessage === undefined ||
    startedAt === undefined ||
    completedAt === undefined ||
    createdAt === undefined ||
    updatedAt === undefined ||
    !items ||
    items.length !== total ||
    items.some((item) => item.run_id !== id)
  ) {
    return null;
  }
  const derived = countGenerationStatuses(items);
  const terminal =
    status === "completed" ||
    status === "partial" ||
    status === "failed" ||
    status === "interrupted";
  if (
    completed !== succeeded ||
    processed + running + pending !== total ||
    derived.processed !== processed ||
    derived.succeeded !== succeeded ||
    derived.failed !== failed ||
    derived.running !== running ||
    derived.pending !== pending ||
    (terminal &&
      (processed !== total ||
        running !== 0 ||
        pending !== 0 ||
        items.some((item) => item.status === "pending" || item.status === "generating")))
  ) {
    return null;
  }
  return {
    contract_version: 1,
    id,
    plan_id: planId,
    project_id: projectId,
    status,
    repository_fingerprint: repositoryFingerprint,
    total,
    processed,
    succeeded,
    running,
    pending,
    completed,
    failed,
    error_message: errorMessage,
    started_at: startedAt,
    completed_at: completedAt,
    created_at: createdAt,
    updated_at: updatedAt,
    items,
  };
}

export function parseSseRecord(event: Event): Record<string, unknown> | null {
  const data = eventData(event);
  if (typeof data !== "string" || data.length === 0) return null;
  const parsed = safeJsonParse(data);
  return isRecord(parsed) ? parsed : null;
}

export function readPrototypePlanSnapshot(event: Event): PrototypePlan | null {
  const record = parseSseRecord(event);
  return record ? readPrototypePlan(record) : null;
}

export function readPrototypeGenerationSnapshot(event: Event): PrototypeGenerationRun | null {
  const record = parseSseRecord(event);
  return record ? readCurrentGenerationRun(record) : null;
}

export function readPrototypeStreamHeartbeat(event: Event): PrototypeStreamHeartbeat | null {
  const record = parseSseRecord(event);
  if (!record || !hasExactKeys(record, HEARTBEAT_KEYS) || record["contract_version"] !== 1) {
    return null;
  }
  const resourceId = readString(record, "resource_id");
  const sentAt = readNullableTimestamp(record, "sent_at");
  return resourceId && sentAt
    ? { contract_version: 1, resource_id: resourceId, sent_at: sentAt }
    : null;
}

export function readSseString(record: Record<string, unknown>, key: string): string | null {
  return readString(record, key);
}

export function readSseNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readSseStringArray(record: Record<string, unknown>, key: string): string[] | null {
  return readStringArrayValue(record[key]);
}

export function readSseErrorMessage(event: Event): string | null {
  const record = parseSseRecord(event);
  return record ? readSseString(record, "message") : null;
}

export function readFailedPrototypeItems(
  record: Record<string, unknown>,
  key: string,
): FailedPrototypeStreamItem[] | null {
  const value = record[key];
  if (!Array.isArray(value)) return null;
  const items: FailedPrototypeStreamItem[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    const prototypeId = readSseString(item, "prototype_id");
    const message = readSseString(item, "message");
    if (!prototypeId || !message) return null;
    items.push({ prototype_id: prototypeId, message });
  }
  return items;
}
