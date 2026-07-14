import type {
  PrototypeGenerationRun,
  PrototypeGenerationRunItem,
  PrototypePlan,
  PrototypePlanAction,
  PrototypePlanAnalysisPhase,
  PrototypePlanEvidenceKind,
  PrototypePlanItem,
  PrototypeProjectContext,
} from "@/lib/types";
import type { Locale } from "@/lib/i18n";

export interface PrototypeGenerationProgress {
  processed: number;
  succeeded: number;
  failed: number;
  running: number;
  pending: number;
  total: number;
  percent: number;
  totalOutputChars: number;
  latestEventAt: string | null;
  currentItems: PrototypeGenerationRunItem[];
  failedItems: PrototypeGenerationRunItem[];
}

export interface LocalizedPrototypeMessage {
  key: string;
  params?: Record<string, string | number>;
}

export interface PrototypePlanDraftState {
  instruction: string;
  context: PrototypeProjectContext;
}

export interface PrototypeGenerationReconcileOptions {
  allowNewerRun?: boolean;
}

const TERMINAL_RUN_STATUSES = new Set<PrototypeGenerationRun["status"]>([
  "completed",
  "partial",
  "failed",
  "interrupted",
]);

export const PROTOTYPE_POLL_EXHAUSTED_ERROR = "prototype generation polling recovery exhausted";

export function isPrototypeGenerationRunActive(run: PrototypeGenerationRun | null): boolean {
  return run !== null && !TERMINAL_RUN_STATUSES.has(run.status);
}

export function isPrototypePlanActionGeneratable(action: PrototypePlanAction): boolean {
  return action === "create" || action === "update";
}

export function countSelectedGeneratablePrototypePlanItems(items: PrototypePlanItem[]): number {
  return items.filter((item) => item.selected && isPrototypePlanActionGeneratable(item.action))
    .length;
}

export function reconcilePrototypePlanDraft(
  current: PrototypePlanDraftState,
  snapshot: PrototypePlan,
  isDirty: boolean,
): PrototypePlanDraftState {
  if (isDirty) return current;
  return {
    instruction: snapshot.global_instruction,
    context: snapshot.project_context,
  };
}

export function prototypePlanDraftsEqual(
  left: PrototypePlanDraftState,
  right: PrototypePlanDraftState,
): boolean {
  return (
    left.instruction === right.instruction &&
    left.context.product_summary === right.context.product_summary &&
    left.context.audience === right.context.audience &&
    left.context.visual_language === right.context.visual_language &&
    left.context.shared_layout === right.context.shared_layout
  );
}

export function reconcilePrototypePlanItemDraft(
  current: PrototypePlanItem | null,
  snapshot: PrototypePlanItem | null,
  isDirty: boolean,
): PrototypePlanItem | null {
  return isDirty && current?.id === snapshot?.id ? current : snapshot;
}

export function prototypePlanItemDraftsEqual(
  left: PrototypePlanItem,
  right: PrototypePlanItem,
): boolean {
  return (
    left.id === right.id &&
    left.title === right.title &&
    left.summary === right.summary &&
    left.brief === right.brief &&
    left.states.length === right.states.length &&
    left.states.every((state, index) => state === right.states[index])
  );
}

export function shouldAcceptPrototypeGenerationRun(
  current: PrototypeGenerationRun | null,
  incoming: PrototypeGenerationRun,
  options: PrototypeGenerationReconcileOptions = {},
): boolean {
  if (!current || current.id === incoming.id) return true;
  if (!options.allowNewerRun || current.plan_id !== incoming.plan_id) return false;
  return comparePrototypeGenerationRunRevision(incoming, current) > 0;
}

export function shouldAcceptPrototypePlanSnapshot(
  current: PrototypePlan | null,
  incoming: PrototypePlan,
): boolean {
  if (!current) return true;
  const currentUpdatedAt = timestamp(current.updated_at);
  const incomingUpdatedAt = timestamp(incoming.updated_at);
  if (currentUpdatedAt !== null && incomingUpdatedAt === null) return false;
  if (currentUpdatedAt !== null && incomingUpdatedAt !== null) {
    return incomingUpdatedAt >= currentUpdatedAt;
  }
  return true;
}

export function matchesPrototypePlanStreamResource(
  incoming: PrototypePlan,
  expectedPlanId: string,
  expectedProjectId: string,
  loadedProjectId: string | null,
): boolean {
  return (
    loadedProjectId !== null &&
    loadedProjectId === expectedProjectId &&
    incoming.id === expectedPlanId &&
    incoming.project_id === loadedProjectId
  );
}

export function derivePrototypeGenerationProgress(
  run: PrototypeGenerationRun,
): PrototypeGenerationProgress {
  let totalOutputChars = 0;
  let latestEventAt: string | null = null;
  const currentItems: PrototypeGenerationRunItem[] = [];
  const failedItems: PrototypeGenerationRunItem[] = [];
  for (const item of run.items) {
    totalOutputChars += item.output_chars;
    if (
      item.last_event_at &&
      (latestEventAt === null || Date.parse(item.last_event_at) > Date.parse(latestEventAt))
    ) {
      latestEventAt = item.last_event_at;
    }
    if (item.status === "generating") currentItems.push(item);
    if (item.status === "failed" || item.status === "interrupted") {
      failedItems.push(item);
    }
  }
  return {
    processed: run.processed,
    succeeded: run.succeeded,
    failed: run.failed,
    running: run.running,
    pending: run.pending,
    total: run.total,
    percent: run.total === 0 ? 0 : Math.min(100, Math.round((run.processed / run.total) * 100)),
    totalOutputChars,
    latestEventAt,
    currentItems,
    failedItems,
  };
}

function timestamp(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function reconcilePrototypeGenerationRun(
  current: PrototypeGenerationRun | null,
  incoming: PrototypeGenerationRun,
  options: PrototypeGenerationReconcileOptions = {},
): PrototypeGenerationRun {
  if (!shouldAcceptPrototypeGenerationRun(current, incoming, options)) return current ?? incoming;
  if (!current || current.id !== incoming.id) return incoming;
  if (!isPrototypeGenerationRunActive(current) && isPrototypeGenerationRunActive(incoming)) {
    return current;
  }
  const currentUpdatedAt = timestamp(current.updated_at);
  const incomingUpdatedAt = timestamp(incoming.updated_at);
  if (currentUpdatedAt !== null && incomingUpdatedAt === null) return current;
  if (
    currentUpdatedAt !== null &&
    incomingUpdatedAt !== null &&
    incomingUpdatedAt < currentUpdatedAt
  ) {
    return current;
  }
  if (incoming.processed < current.processed) return current;
  return incoming;
}

function comparePrototypeGenerationRunRevision(
  left: PrototypeGenerationRun,
  right: PrototypeGenerationRun,
): number {
  const createdComparison = compareTimestamps(left.created_at, right.created_at);
  if (createdComparison !== 0) return createdComparison;
  const updatedComparison = compareTimestamps(left.updated_at, right.updated_at);
  if (updatedComparison !== 0) return updatedComparison;
  return 0;
}

function compareTimestamps(left: string | null, right: string | null): number {
  const leftTimestamp = timestamp(left);
  const rightTimestamp = timestamp(right);
  if (leftTimestamp === rightTimestamp) return 0;
  if (leftTimestamp === null) return -1;
  if (rightTimestamp === null) return 1;
  return leftTimestamp > rightTimestamp ? 1 : -1;
}

export function prototypeAnalysisPercent(completed: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((completed / total) * 100));
}

export function prototypeAnalysisPhaseKey(phase: PrototypePlanAnalysisPhase): string {
  return `prototype.plan.analysisPhase.${phase}`;
}

export function formatPrototypeElapsed(
  startedAt: string | null,
  completedAt: string | null,
  nowMs: number,
): string {
  const started = timestamp(startedAt);
  if (started === null) return "--:--";
  const completed = timestamp(completedAt);
  const elapsedSeconds = Math.max(0, Math.floor(((completed ?? nowMs) - started) / 1000));
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  const minuteText = String(minutes).padStart(2, "0");
  const secondText = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${minuteText}:${secondText}` : `${minuteText}:${secondText}`;
}

export function prototypeEvidenceKindKey(kind: PrototypePlanEvidenceKind): string {
  const keys: Record<PrototypePlanEvidenceKind, string> = {
    "react-router-route": "prototype.plan.evidenceKind.reactRouterRoute",
    "vue-router-route": "prototype.plan.evidenceKind.vueRouterRoute",
    "file-route": "prototype.plan.evidenceKind.fileRoute",
    "page-directory": "prototype.plan.evidenceKind.pageDirectory",
    "page-source": "prototype.plan.evidenceKind.pageSource",
    layout: "prototype.plan.evidenceKind.layout",
    style: "prototype.plan.evidenceKind.style",
    parser: "prototype.plan.evidenceKind.parser",
  };
  return keys[kind];
}

export function prototypeEvidenceDetailMessage(
  detail: string,
  locale: Locale = "en-US",
): LocalizedPrototypeMessage | null {
  if (!detail) return null;
  if (detail === "bounded source evidence") {
    return { key: "prototype.plan.evidenceBoundedSource" };
  }
  if (detail === "directory fallback") {
    return { key: "prototype.plan.evidenceDirectoryFallback" };
  }
  const routeRelationship = /^(.*?) -> (.*)$/.exec(detail);
  if (routeRelationship?.[1] && routeRelationship[2]) {
    return {
      key: "prototype.plan.evidenceRouteRelationship",
      params: { component: routeRelationship[1], route: routeRelationship[2] },
    };
  }
  const diagnostic = prototypeDiagnosticMessage(detail, locale);
  if (diagnostic.key === "prototype.plan.diagnostic.unknownLocalized") {
    return { key: "prototype.plan.evidenceDetailUnknownLocalized" };
  }
  if (diagnostic.key !== "prototype.plan.diagnostic.raw") return diagnostic;
  return { key: "prototype.plan.evidenceDiscovery", params: { detail } };
}

export function prototypeDiagnosticMessage(
  diagnostic: string,
  locale: Locale = "en-US",
): LocalizedPrototypeMessage {
  const packagedDiagnostics: Record<string, string> = {
    "package.json is not valid JSON": "prototype.plan.diagnostic.packageInvalidPackageJson",
    "browser extension surface is detected but not supported in MVP":
      "prototype.plan.diagnostic.packageBrowserExtensionUnsupported",
    "React package has no supported route declaration; fallback discovery is low confidence":
      "prototype.plan.diagnostic.packageReactFallback",
    "no supported web framework signal was found":
      "prototype.plan.diagnostic.packageUnsupportedFramework",
  };
  for (const [message, key] of Object.entries(packagedDiagnostics)) {
    const suffix = `: ${message}`;
    if (diagnostic.endsWith(suffix)) {
      return {
        key,
        params: { package: diagnostic.slice(0, -suffix.length) || "." },
      };
    }
  }
  if (diagnostic === "package.json is not valid JSON") {
    return { key: "prototype.plan.diagnostic.invalidPackageJson" };
  }
  if (diagnostic === "browser extension surface is detected but not supported in MVP") {
    return { key: "prototype.plan.diagnostic.browserExtensionUnsupported" };
  }
  if (
    diagnostic ===
    "React package has no supported route declaration; fallback discovery is low confidence"
  ) {
    return { key: "prototype.plan.diagnostic.reactFallback" };
  }
  if (diagnostic === "no supported web framework signal was found") {
    return { key: "prototype.plan.diagnostic.unsupportedFramework" };
  }
  if (diagnostic === "route declaration was not found; directory fallback is low confidence") {
    return { key: "prototype.plan.diagnostic.directoryFallback" };
  }
  if (diagnostic === "React Router package has no readable route entry") {
    return { key: "prototype.plan.diagnostic.noRouteEntry" };
  }
  if (diagnostic === "React Router entry contains syntax errors; route candidates are partial") {
    return { key: "prototype.plan.diagnostic.routeSyntax" };
  }
  if (diagnostic === "Project changed during analysis; analyze again.") {
    return { key: "prototype.plan.diagnostic.projectChanged" };
  }
  const dynamicPath = /^React Router path at line (\d+) is not statically evaluable$/.exec(
    diagnostic,
  );
  const line = dynamicPath?.[1];
  if (line) {
    return { key: "prototype.plan.diagnostic.dynamicRoute", params: { line } };
  }
  if (locale === "zh-CN" && !/[\u3400-\u9fff]/.test(diagnostic)) {
    return { key: "prototype.plan.diagnostic.unknownLocalized" };
  }
  return { key: "prototype.plan.diagnostic.raw", params: { message: diagnostic } };
}

export function prototypePlanErrorMessage(message: string): LocalizedPrototypeMessage {
  if (
    message === "project evidence changed during analysis" ||
    message === "Project changed during analysis; analyze again."
  ) {
    return { key: "prototype.plan.error.sourceChanged" };
  }
  if (message === "prototype planning runtime returned no result") {
    return { key: "prototype.plan.error.noResult" };
  }
  if (message === "prototype planning runtime returned invalid JSON") {
    return { key: "prototype.plan.error.invalidJson" };
  }
  if (message === "prototype planning result did not match the required schema") {
    return { key: "prototype.plan.error.invalidSchema" };
  }
  const invalidSchema = /^prototype planning result did not match the required schema: (.+)$/.exec(
    message,
  )?.[1];
  if (invalidSchema) {
    return {
      key: "prototype.plan.error.invalidSchemaDetail",
      params: { detail: invalidSchema },
    };
  }
  if (message === "prototype plan analysis failed") {
    return { key: "prototype.plan.error.analysisFailed" };
  }
  if (message === "prototype planning runtime is unavailable") {
    return { key: "prototype.plan.error.runtimeUnavailable" };
  }
  if (message === "prototype planning reached the token limit for a single page") {
    return { key: "prototype.plan.error.pageTokenLimit" };
  }
  const localeMismatch =
    /^prototype planning result did not follow the (en-US|zh-CN) output locale: (.+)$/.exec(
      message,
    );
  if (localeMismatch?.[1] && localeMismatch[2]) {
    return {
      key: "prototype.plan.error.outputLocale",
      params: { locale: localeMismatch[1], detail: localeMismatch[2] },
    };
  }
  const promptLimit = /^prototype planning evidence exceeds prompt limit \((\d+) > (\d+)\)$/.exec(
    message,
  );
  if (promptLimit?.[1] && promptLimit[2]) {
    return {
      key: "prototype.plan.error.promptLimit",
      params: { actual: promptLimit[1], limit: promptLimit[2] },
    };
  }
  const uncovered = /^prototype planning result did not cover candidates: (.+)$/.exec(message)?.[1];
  if (uncovered) {
    return { key: "prototype.plan.error.candidateCoverage", params: { detail: uncovered } };
  }
  const unknownEvidence = /^prototype planning result referenced unknown evidence IDs: (.+)$/.exec(
    message,
  )?.[1];
  if (unknownEvidence) {
    return {
      key: "prototype.plan.error.unknownEvidence",
      params: { detail: unknownEvidence },
    };
  }
  return { key: "prototype.plan.error.raw", params: { message } };
}

export function prototypeGenerationErrorMessage(message: string): LocalizedPrototypeMessage {
  if (message === "prototype_plan_missing" || message.startsWith("prototype plan not found:")) {
    return { key: "prototype.plan.generationError.planMissing" };
  }
  if (message === "prototype generation stream ended without done") {
    return { key: "prototype.plan.generationError.noDone" };
  }
  if (message === PROTOTYPE_POLL_EXHAUSTED_ERROR) {
    return { key: "prototype.plan.generationPollingExhausted" };
  }
  if (
    message ===
    "prototype stream stopped before a complete HTML document because the model reached its max token limit"
  ) {
    return { key: "prototype.plan.generationError.maxTokens" };
  }
  if (message === "LLM returned an incomplete HTML document; generation was not saved") {
    return { key: "prototype.plan.generationError.incompleteHtml" };
  }
  if (message === "prototype artifact is not a complete HTML document") {
    return { key: "prototype.plan.generationError.incompleteHtml" };
  }
  if (
    message === "prototype UI engineer returned invalid manifest JSON" ||
    message === "prototype UI engineer returned an invalid manifest" ||
    message === "prototype UI engineer returned no manifest"
  ) {
    return { key: "prototype.plan.generationError.artifactManifest" };
  }
  if (
    message === "prototype run item id is not filesystem-safe" ||
    message === "prototype artifact path is unsafe" ||
    message === "prototype artifact path does not match the run staging path" ||
    message === "prototype worktree path is a symlink" ||
    message === "prototype artifact path contains a symlink" ||
    message === "prototype artifact is outside its worktree boundary" ||
    message === "prototype source path is unsafe" ||
    message === "prototype source path contains a symlink" ||
    message === "prototype source path is outside the worktree" ||
    message === "prototype staging cleanup escaped the worktree"
  ) {
    return { key: "prototype.plan.generationError.artifactBoundary" };
  }
  if (message === "prototype worktree is unavailable") {
    return { key: "prototype.plan.generationError.worktreeUnavailable" };
  }
  if (
    message === "prototype artifact file is missing" ||
    message === "prototype artifact could not be read"
  ) {
    return { key: "prototype.plan.generationError.artifactUnavailable" };
  }
  if (message === "prototype staging directory contains unexpected files") {
    return { key: "prototype.plan.generationError.artifactUnexpectedFiles" };
  }
  const sizeLimit = /^prototype artifact exceeds the (\d+)-byte size limit$/.exec(message)?.[1];
  if (sizeLimit) {
    return { key: "prototype.plan.generationError.artifactTooLarge", params: { limit: sizeLimit } };
  }
  if (message === "prototype artifact byte size does not match its manifest") {
    return { key: "prototype.plan.generationError.artifactSizeMismatch" };
  }
  if (message === "prototype artifact is not valid UTF-8") {
    return { key: "prototype.plan.generationError.artifactEncoding" };
  }
  if (message === "prototype artifact checksum does not match its manifest") {
    return { key: "prototype.plan.generationError.artifactChecksum" };
  }
  const forbiddenScheme = /^prototype artifact uses forbidden URL scheme: (.+)$/.exec(message)?.[1];
  if (forbiddenScheme) {
    return {
      key: "prototype.plan.generationError.artifactUrlScheme",
      params: { scheme: forbiddenScheme },
    };
  }
  const externalOrigin = /^prototype artifact uses a non-whitelisted external origin: (.+)$/.exec(
    message,
  )?.[1];
  if (externalOrigin) {
    return {
      key: "prototype.plan.generationError.artifactExternalOrigin",
      params: { origin: externalOrigin },
    };
  }
  if (message === "prototype UI engineer task disappeared") {
    return { key: "prototype.plan.generationError.uiEngineerTaskMissing" };
  }
  if (message === "prototype UI engineer execution process correlation is inconsistent") {
    return { key: "prototype.plan.generationError.uiEngineerCorrelation" };
  }
  if (
    message === "prototype UI engineer runtime launch is disabled" ||
    message === "prototype UI engineer runtime catalog is unavailable" ||
    message === "prototype UI engineer requires an enabled Claude executor" ||
    message === "prototype UI engineer Claude runtime is not configured" ||
    message === "prototype UI engineer resolved to a non-Claude executor" ||
    message === "prototype generation runtime is unavailable" ||
    message === "no usable LLM executor configured"
  ) {
    return { key: "prototype.plan.generationError.uiEngineerRuntime" };
  }
  if (
    message === "prototype UI engineer Claude CLI availability could not be checked" ||
    message === "prototype UI engineer requires an available Claude CLI command"
  ) {
    return { key: "prototype.plan.generationError.claudeCliUnavailable" };
  }
  const engineerFailure = /^prototype UI engineer (?:failed|runtime failed): (.+)$/.exec(
    message,
  )?.[1];
  if (engineerFailure) {
    return {
      key: "prototype.plan.generationError.uiEngineerFailed",
      params: { detail: engineerFailure },
    };
  }
  if (message === "prototype workspace belongs to a different project") {
    return { key: "prototype.plan.generationError.workspaceMismatch" };
  }
  if (
    message === "isolated prototype source could not be verified" ||
    message === "isolated prototype source fingerprint does not match the reviewed plan" ||
    message === "project evidence is stale; analyze the project again"
  ) {
    return { key: "prototype.plan.generationError.sourceChanged" };
  }
  if (message === "prototype plan changed; refresh before generating") {
    return { key: "prototype.plan.generationError.planChanged" };
  }
  if (message === "prototype UI engineer modified project source outside its staging directory") {
    return { key: "prototype.plan.generationError.sourceModified" };
  }
  if (message === "prototype staging artifact could not be cleaned") {
    return { key: "prototype.plan.generationError.artifactCleanup" };
  }
  const activityPhase = /^prototype activity persistence failed during (.+)$/.exec(message)?.[1];
  if (activityPhase) {
    return {
      key: "prototype.plan.generationError.activityPersistence",
      params: { phase: activityPhase },
    };
  }
  if (message === "generation governance gates are unavailable") {
    return { key: "prototype.plan.generationError.governanceUnavailable" };
  }
  if (message === "no selected candidates are eligible for generation") {
    return { key: "prototype.plan.generationError.noEligibleItems" };
  }
  if (message === "generation run has no failed or interrupted items") {
    return { key: "prototype.plan.generationError.noRetryItems" };
  }
  return { key: "prototype.plan.generationError.raw", params: { message } };
}

export function boundedPrototypeEvidenceExcerpt(
  content: string,
  limit = 1_600,
): { text: string; truncated: boolean } {
  if (content.length <= limit) return { text: content, truncated: false };
  return { text: content.slice(0, limit), truncated: true };
}
