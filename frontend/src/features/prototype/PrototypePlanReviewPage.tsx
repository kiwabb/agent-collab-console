"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, Loader2, RefreshCw, Save, Sparkles } from "lucide-react";

import {
  createPrototypeGenerationRun,
  getPrototypeGenerationRun,
  getLatestPrototypeGenerationRun,
  getPrototypePlan,
  patchPrototypePlan,
  patchPrototypePlanItem,
  patchPrototypePlanSelection,
  reanalyzePrototypePlan,
  retryPrototypeGenerationRun,
} from "@/lib/api/prototypes";
import type {
  PrototypeGenerationRun,
  PrototypePlan,
  PrototypePlanAction,
  PrototypePlanItem,
  PrototypeProjectContext,
} from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { PrototypeAnalysisProgress } from "./PrototypeAnalysisProgress";
import { PrototypeEvidenceList } from "./PrototypeEvidenceList";
import { PrototypeGenerationProgressPanel } from "./PrototypeGenerationProgressPanel";
import {
  countSelectedGeneratablePrototypePlanItems,
  isPrototypeGenerationRunActive,
  isPrototypePlanActionGeneratable,
  prototypeGenerationErrorMessage,
  prototypePlanErrorMessage,
  prototypePlanDraftsEqual,
  prototypePlanItemDraftsEqual,
  prototypeDiagnosticMessage,
  reconcilePrototypePlanDraft,
  reconcilePrototypeGenerationRun,
  reconcilePrototypePlanItemDraft,
  shouldAcceptPrototypePlanSnapshot,
} from "./prototypePlanReviewState";
import { shouldOpenPrototypeWorkbench } from "./prototypeWorkbenchState";
import { usePrototypeGenerationLiveRun } from "./usePrototypeGenerationLiveRun";
import {
  type PrototypePlanConnectionIssue,
  type PrototypePlanPollingIssue,
  usePrototypePlanLiveRecovery,
} from "./usePrototypePlanLiveRecovery";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  projectId: string;
  planId: string;
}

type Translator = (key: string, params?: Record<string, string | number>) => string;
type Filter = "all" | PrototypePlanAction | "low";
type SaveState = "idle" | "saving" | "saved" | "error";

const ACTION_FILTERS: Filter[] = [
  "all",
  "create",
  "update",
  "unchanged",
  "missing",
  "low",
  "unsupported",
];

const PLAN_STATUS_KEYS: Record<PrototypePlan["status"], string> = {
  queued: "prototype.plan.queued",
  analyzing: "prototype.plan.analyzing",
  ready: "prototype.plan.ready",
  analysis_failed: "prototype.plan.analysisFailed",
  stale: "prototype.plan.stale",
  interrupted: "prototype.plan.interrupted",
};

const EMPTY_PROJECT_CONTEXT: PrototypeProjectContext = {
  product_summary: "",
  audience: "",
  visual_language: "",
  shared_layout: "",
};

export function matchesPrototypePlanFilter(item: PrototypePlanItem, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "low") return item.confidence === "low";
  return item.action === filter;
}

export function prototypePlanRecoveryMessageKey(
  connectionIssue: PrototypePlanConnectionIssue | null,
  pollingIssue: PrototypePlanPollingIssue | null,
): string | null {
  if (pollingIssue === "exhausted") return "prototype.plan.analysisPollingExhausted";
  if (pollingIssue === "request_failed") return "prototype.plan.analysisPollingFailed";
  if (pollingIssue === "invalid_resource" || connectionIssue === "invalid_resource") {
    return "prototype.plan.analysisResourceMismatch";
  }
  if (connectionIssue === "invalid_snapshot") return "prototype.plan.analysisSnapshotFailed";
  if (connectionIssue === "disconnected") return "prototype.plan.analysisStreamFailed";
  if (connectionIssue === "silent") return "prototype.plan.analysisStreamSilent";
  return null;
}

function statusLabel(status: PrototypePlan["status"], t: Translator): string {
  return t(PLAN_STATUS_KEYS[status]);
}

function confidenceLabel(confidence: PrototypePlanItem["confidence"], t: Translator): string {
  return t(`prototype.plan.confidence.${confidence}`);
}

function surfaceLabel(surface: string, t: Translator): string {
  if (surface === "web") return t("prototype.plan.surface.web");
  if (surface === "desktop") return t("prototype.plan.surface.desktop");
  if (surface === "browser-extension") return t("prototype.plan.surface.browserExtension");
  if (surface === "mobile") return t("prototype.plan.surface.mobile");
  if (surface === "unknown") return t("prototype.plan.surface.unknown");
  return surface;
}

function actionLabel(action: PrototypePlanAction, t: Translator): string {
  const key = `prototype.plan.filter${action.slice(0, 1).toUpperCase()}${action.slice(1)}`;
  return t(key);
}

function PlanBanner({
  plan,
  t,
  onReanalyze,
  isReanalyzing,
}: {
  plan: PrototypePlan;
  t: Translator;
  onReanalyze: () => void;
  isReanalyzing: boolean;
}) {
  if (plan.status === "ready") return null;
  const failed = plan.status === "analysis_failed";
  const errorMessage = plan.error_message ? prototypePlanErrorMessage(plan.error_message) : null;
  return (
    <div
      role={failed || plan.status === "stale" ? "alert" : "status"}
      aria-live="polite"
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm",
        failed || plan.status === "stale"
          ? "border-status-failed/40 bg-status-failed/10 text-status-failed"
          : "border-status-awaiting/40 bg-status-awaiting/10 text-foreground",
      )}
    >
      <div>
        <div className="font-semibold">{statusLabel(plan.status, t)}</div>
        {errorMessage && (
          <div className="mt-1 text-xs opacity-90">{t(errorMessage.key, errorMessage.params)}</div>
        )}
      </div>
      {["analysis_failed", "stale", "interrupted"].includes(plan.status) && (
        <Button
          className="min-h-11"
          size="xs"
          variant="outline"
          onClick={onReanalyze}
          disabled={isReanalyzing}
        >
          <RefreshCw size={13} className={cn(isReanalyzing && "animate-spin")} />
          {t("prototype.plan.retry")}
        </Button>
      )}
    </div>
  );
}

export function PrototypePlanReviewPage({ projectId, planId }: Props) {
  const { locale, t } = useI18n();
  const { addToast } = useToast();
  const [plan, setPlan] = useState<PrototypePlan | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [surfaceFilter, setSurfaceFilter] = useState("all");
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [context, setContext] = useState<PrototypeProjectContext>(EMPTY_PROJECT_CONTEXT);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [itemDraft, setItemDraft] = useState<PrototypePlanItem | null>(null);
  const [confirmGenerate, setConfirmGenerate] = useState(false);
  const [generationRun, setGenerationRun] = useState<PrototypeGenerationRun | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [isReanalyzing, setIsReanalyzing] = useState(false);
  const [generationStarting, setGenerationStarting] = useState(false);
  const [generationRetrying, setGenerationRetrying] = useState(false);
  const [generationRefreshing, setGenerationRefreshing] = useState(false);
  const [generationRecoveryKey, setGenerationRecoveryKey] = useState(0);
  const [analysisRecoveryKey, setAnalysisRecoveryKey] = useState(0);
  const [selectionSaving, setSelectionSaving] = useState(false);
  const planDraftRef = useRef({ instruction: "", context: EMPTY_PROJECT_CONTEXT });
  const planDraftDirtyRef = useRef(false);
  const activeItemIdRef = useRef<string | null>(null);
  const itemDraftRef = useRef<PrototypePlanItem | null>(null);
  const itemDraftDirtyRef = useRef(false);
  const latestPlanSnapshotRef = useRef<PrototypePlan | null>(null);
  const latestGenerationRunRef = useRef<PrototypeGenerationRun | null>(null);
  const generationNavigationRunIdRef = useRef<string | null>(null);
  const navigatedGenerationRunIdRef = useRef<string | null>(null);
  const selectionMutationIdRef = useRef(0);

  const applyPlan = useCallback((next: PrototypePlan) => {
    if (!shouldAcceptPrototypePlanSnapshot(latestPlanSnapshotRef.current, next)) return;
    latestPlanSnapshotRef.current = next;
    setPlan(next);
    const nextPlanDraft = reconcilePrototypePlanDraft(
      planDraftRef.current,
      next,
      planDraftDirtyRef.current,
    );
    planDraftRef.current = nextPlanDraft;
    setInstruction(nextPlanDraft.instruction);
    setContext(nextPlanDraft.context);

    const currentActiveId = activeItemIdRef.current;
    const nextActiveId =
      currentActiveId && next.items.some((item) => item.id === currentActiveId)
        ? currentActiveId
        : (next.items[0]?.id ?? null);
    activeItemIdRef.current = nextActiveId;
    setActiveItemId(nextActiveId);
    const nextServerItem = next.items.find((item) => item.id === nextActiveId) ?? null;
    const nextItemDraft = reconcilePrototypePlanItemDraft(
      itemDraftRef.current,
      nextServerItem,
      itemDraftDirtyRef.current,
    );
    if (nextItemDraft !== itemDraftRef.current) itemDraftDirtyRef.current = false;
    itemDraftRef.current = nextItemDraft;
    setItemDraft(nextItemDraft);
  }, []);

  const applyGenerationRun = useCallback((next: PrototypeGenerationRun, allowNewerRun: boolean) => {
    const reconciled = reconcilePrototypeGenerationRun(latestGenerationRunRef.current, next, {
      allowNewerRun,
    });
    if (reconciled === latestGenerationRunRef.current) return;
    latestGenerationRunRef.current = reconciled;
    setGenerationRun(reconciled);
  }, []);

  const applyLiveGenerationRun = useCallback(
    (next: PrototypeGenerationRun) => applyGenerationRun(next, false),
    [applyGenerationRun],
  );

  const applyLatestGenerationRun = useCallback(
    (next: PrototypeGenerationRun) => applyGenerationRun(next, true),
    [applyGenerationRun],
  );

  const generationConnection = usePrototypeGenerationLiveRun({
    run: generationRun,
    onSnapshot: applyLiveGenerationRun,
    recoveryKey: generationRecoveryKey,
  });
  const analysisConnection = usePrototypePlanLiveRecovery({
    plan,
    planId,
    projectId,
    onSnapshot: applyPlan,
    recoveryKey: analysisRecoveryKey,
  });

  const load = useCallback(async () => {
    setGenerationRecoveryKey((current) => current + 1);
    setAnalysisRecoveryKey((current) => current + 1);
    try {
      const [next, latestRun] = await Promise.all([
        getPrototypePlan(planId),
        getLatestPrototypeGenerationRun(planId),
      ]);
      if (next.id !== planId || next.project_id !== projectId) {
        throw new Error(t("prototype.plan.analysisResourceMismatch"));
      }
      applyPlan(next);
      if (latestRun) {
        if (isPrototypeGenerationRunActive(latestRun)) {
          generationNavigationRunIdRef.current = latestRun.id;
        }
        applyLatestGenerationRun(latestRun);
      }
      setLoadError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("prototype plan load failed:", err);
      setLoadError(message);
    }
  }, [planId, projectId, applyPlan, applyLatestGenerationRun, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!shouldOpenPrototypeWorkbench(generationRun, generationNavigationRunIdRef.current)) return;
    if (navigatedGenerationRunIdRef.current === generationRun.id) return;
    navigatedGenerationRunIdRef.current = generationRun.id;
    window.location.assign(`/projects/${projectId}/prototypes`);
  }, [generationRun, projectId]);

  const filteredItems = useMemo(
    () =>
      plan?.items.filter(
        (item) =>
          matchesPrototypePlanFilter(item, filter) &&
          (surfaceFilter === "all" || item.surface_kind === surfaceFilter),
      ) ?? [],
    [plan, filter, surfaceFilter],
  );
  const surfaces = useMemo(
    () => [...new Set(plan?.items.map((item) => item.surface_kind) ?? [])].sort(),
    [plan],
  );
  const groupedItems = useMemo(() => {
    const groups = new Map<string, PrototypePlanItem[]>();
    for (const item of filteredItems) {
      const key = `${item.package_root}\u0000${item.surface_kind}`;
      groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    return [...groups.entries()].map(([key, items]) => {
      const [packageRoot = "", surfaceKind = ""] = key.split("\u0000");
      return { key, packageRoot, surfaceKind, items };
    });
  }, [filteredItems]);
  const selectedCount = plan ? countSelectedGeneratablePrototypePlanItems(plan.items) : 0;

  const selectActiveItem = useCallback((item: PrototypePlanItem) => {
    activeItemIdRef.current = item.id;
    setActiveItemId(item.id);
    itemDraftDirtyRef.current = false;
    itemDraftRef.current = item;
    setItemDraft(item);
  }, []);

  const updateInstructionDraft = useCallback((value: string) => {
    planDraftDirtyRef.current = true;
    planDraftRef.current = { ...planDraftRef.current, instruction: value };
    setInstruction(value);
    setSaveState("idle");
  }, []);

  const updateContextDraft = useCallback((key: keyof PrototypeProjectContext, value: string) => {
    const nextContext = { ...planDraftRef.current.context, [key]: value };
    planDraftDirtyRef.current = true;
    planDraftRef.current = { ...planDraftRef.current, context: nextContext };
    setContext(nextContext);
    setSaveState("idle");
  }, []);

  const updateItemDraft = useCallback((next: PrototypePlanItem) => {
    itemDraftDirtyRef.current = true;
    itemDraftRef.current = next;
    setItemDraft(next);
    setSaveState("idle");
  }, []);

  const savePlan = useCallback(async () => {
    setSaveState("saving");
    const savedDraft = planDraftRef.current;
    try {
      const next = await patchPrototypePlan(planId, {
        global_instruction: savedDraft.instruction,
        project_context: savedDraft.context,
      });
      const submittedDraftIsCurrent = prototypePlanDraftsEqual(planDraftRef.current, savedDraft);
      if (submittedDraftIsCurrent) {
        planDraftDirtyRef.current = false;
      }
      applyPlan(next);
      setSaveState(submittedDraftIsCurrent ? "saved" : "idle");
    } catch (err) {
      setSaveState("error");
      console.error("prototype plan save failed:", err);
      addToast({
        type: "error",
        title: t("prototype.plan.saveFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [planId, applyPlan, addToast, t]);

  const saveItem = useCallback(async () => {
    const savedDraft = itemDraftRef.current;
    if (!savedDraft) return;
    setSaveState("saving");
    try {
      const next = await patchPrototypePlanItem(savedDraft.id, {
        title: savedDraft.title,
        summary: savedDraft.summary,
        brief: savedDraft.brief,
        states: savedDraft.states,
      });
      const submittedDraftIsCurrent = Boolean(
        itemDraftRef.current && prototypePlanItemDraftsEqual(itemDraftRef.current, savedDraft),
      );
      if (submittedDraftIsCurrent) {
        itemDraftDirtyRef.current = false;
      }
      applyPlan(next);
      setSaveState(submittedDraftIsCurrent ? "saved" : "idle");
    } catch (err) {
      setSaveState("error");
      console.error("prototype plan item save failed:", err);
      addToast({
        type: "error",
        title: t("prototype.plan.saveFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [applyPlan, addToast, t]);

  const setItemsSelected = useCallback(
    async (items: PrototypePlanItem[], selected: boolean) => {
      const eligible = items.filter((item) => isPrototypePlanActionGeneratable(item.action));
      if (eligible.length === 0 || selectionSaving) return;
      const itemIds = new Set(eligible.map((item) => item.id));
      const previousSelection = new Map(eligible.map((item) => [item.id, item.selected]));
      const mutationId = selectionMutationIdRef.current + 1;
      selectionMutationIdRef.current = mutationId;
      setSelectionSaving(true);
      setPlan((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                itemIds.has(item.id) ? { ...item, selected } : item,
              ),
            }
          : current,
      );
      try {
        const next = await patchPrototypePlanSelection(planId, {
          item_ids: [...itemIds],
          selected,
        });
        if (selectionMutationIdRef.current !== mutationId) return;
        applyPlan(next);
        setLoadError(null);
      } catch (err) {
        console.error("prototype plan bulk selection save failed:", err);
        if (selectionMutationIdRef.current !== mutationId) return;
        setLoadError(err instanceof Error ? err.message : String(err));
        setPlan((current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => {
                  const previous = previousSelection.get(item.id);
                  return previous === undefined ? item : { ...item, selected: previous };
                }),
              }
            : current,
        );
      } finally {
        if (selectionMutationIdRef.current === mutationId) setSelectionSaving(false);
      }
    },
    [applyPlan, planId, selectionSaving],
  );

  const reanalyze = useCallback(async () => {
    setIsReanalyzing(true);
    try {
      const result = await reanalyzePrototypePlan(planId);
      window.location.assign(
        `/projects/${projectId}/prototypes/plans/${encodeURIComponent(result.plan_id)}`,
      );
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
      setIsReanalyzing(false);
    }
  }, [planId, projectId]);

  const startGeneration = useCallback(async () => {
    if (!plan || selectionSaving || saveState === "saving") return;
    setGenerationStarting(true);
    try {
      const latest = await getPrototypePlan(plan.id);
      if (latest.id !== plan.id || latest.project_id !== projectId) {
        throw new Error(t("prototype.plan.analysisResourceMismatch"));
      }
      applyPlan(latest);
      const result = await createPrototypeGenerationRun(latest.id, latest.updated_at);
      generationNavigationRunIdRef.current = result.run_id;
      const next = await getPrototypeGenerationRun(result.run_id);
      applyLatestGenerationRun(next);
      setConfirmGenerate(false);
      setGenerationError(null);
    } catch (err) {
      setGenerationError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerationStarting(false);
    }
  }, [plan, projectId, selectionSaving, saveState, applyPlan, applyLatestGenerationRun, t]);

  const retryGeneration = useCallback(async () => {
    if (!generationRun) return;
    setGenerationRetrying(true);
    try {
      const result = await retryPrototypeGenerationRun(planId, generationRun.id);
      generationNavigationRunIdRef.current = result.run_id;
      const next = await getPrototypeGenerationRun(result.run_id);
      applyLatestGenerationRun(next);
      setGenerationError(null);
    } catch (err) {
      setGenerationError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerationRetrying(false);
    }
  }, [generationRun, planId, applyLatestGenerationRun]);

  const reconcileGeneration = useCallback(async () => {
    if (!generationRun) return;
    setGenerationRecoveryKey((current) => current + 1);
    setGenerationRefreshing(true);
    try {
      const next = await getPrototypeGenerationRun(generationRun.id);
      applyLiveGenerationRun(next);
      setGenerationError(null);
    } catch (err) {
      console.error("prototype generation manual reconciliation failed:", err);
      setGenerationError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerationRefreshing(false);
    }
  }, [generationRun, applyLiveGenerationRun]);

  const generationErrorMessage = generationError
    ? prototypeGenerationErrorMessage(generationError)
    : null;
  const analysisRecoveryMessageKey = prototypePlanRecoveryMessageKey(
    analysisConnection.connectionIssue,
    analysisConnection.pollingIssue,
  );

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/projects/${projectId}/prototypes`}
            className="mb-2 inline-flex min-h-11 items-center gap-1 text-xs text-text-muted hover:text-foreground"
          >
            <ArrowLeft size={13} /> {t("prototype.plan.back")}
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">{t("prototype.plan.title")}</h1>
          {plan && <p className="mt-1 text-sm text-text-muted">{statusLabel(plan.status, t)}</p>}
        </div>
        <div className="grid w-full grid-cols-[0.7fr_0.95fr_1.35fr] items-center gap-2 sm:flex sm:w-auto sm:flex-wrap">
          <Button
            className="min-h-11 w-full sm:w-auto"
            size="sm"
            variant="outline"
            onClick={() => void load()}
          >
            <RefreshCw size={14} />
            {t("prototype.plan.refresh")}
          </Button>
          <Button
            className="min-h-11 w-full sm:w-auto"
            size="sm"
            variant="secondary"
            onClick={() => void savePlan()}
            disabled={!plan || plan.status === "analyzing" || saveState === "saving"}
          >
            <Save size={14} />
            {saveState === "saving" ? t("prototype.plan.saving") : t("prototype.plan.save")}
          </Button>
          {saveState === "saved" && (
            <span role="status" className="col-span-2 text-xs text-status-done sm:col-auto">
              {t("prototype.plan.saved")}
            </span>
          )}
          {saveState === "error" && (
            <span role="alert" className="col-span-2 text-xs text-status-failed sm:col-auto">
              {t("prototype.plan.saveFailed")}
            </span>
          )}
          <Button
            className="min-h-11 min-w-0 w-full px-2 text-xs sm:w-auto sm:px-3 sm:text-sm"
            size="sm"
            onClick={() => setConfirmGenerate(true)}
            disabled={
              !plan ||
              plan.status !== "ready" ||
              selectedCount === 0 ||
              selectionSaving ||
              saveState === "saving" ||
              Boolean(generationRun && ["queued", "running"].includes(generationRun.status))
            }
          >
            <Sparkles size={14} />
            {t("prototype.plan.generateSelected")}
          </Button>
        </div>
      </header>

      {loadError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-status-failed/40 bg-status-failed/10 px-4 py-3 text-sm text-status-failed"
        >
          <span className="min-w-0 break-words">{loadError}</span>
          <Button className="min-h-11" size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw size={14} />
            {t("prototype.plan.refresh")}
          </Button>
        </div>
      )}
      {generationError && !generationRun && (
        <div
          role="alert"
          className="rounded-lg border border-status-failed/40 bg-status-failed/10 px-4 py-3 text-sm text-status-failed"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0 break-words">
              {generationErrorMessage
                ? t(generationErrorMessage.key, generationErrorMessage.params)
                : ""}
            </span>
            <Button className="min-h-11" size="sm" variant="outline" onClick={() => void load()}>
              <RefreshCw size={14} />
              {t("prototype.plan.refresh")}
            </Button>
          </div>
        </div>
      )}
      {plan && (
        <PlanBanner
          plan={plan}
          t={t}
          onReanalyze={() => void reanalyze()}
          isReanalyzing={isReanalyzing}
        />
      )}
      {plan && <PrototypeAnalysisProgress plan={plan} t={t} />}
      {plan && analysisRecoveryMessageKey && (
        <div
          role={analysisConnection.connectionIssue === "silent" ? "status" : "alert"}
          aria-live="polite"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-status-awaiting/40 bg-status-awaiting/10 px-4 py-3 text-sm text-foreground"
        >
          <span className="min-w-0 break-words">
            {t(analysisRecoveryMessageKey)}
            {analysisConnection.usingPollingFallback && (
              <span className="ml-1">{t("prototype.plan.analysisPollingFallback")}</span>
            )}
          </span>
          <Button className="min-h-11" size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw size={14} />
            {t("prototype.plan.refresh")}
          </Button>
        </div>
      )}
      {generationRun && (
        <PrototypeGenerationProgressPanel
          run={generationRun}
          locale={locale}
          t={t}
          actionError={generationError}
          connectionIssue={generationConnection.connectionIssue}
          pollingError={generationConnection.pollingError}
          usingPollingFallback={generationConnection.usingPollingFallback}
          isRetrying={generationRetrying}
          isRefreshing={generationRefreshing}
          onRetry={() => void retryGeneration()}
          onRefresh={() => void reconcileGeneration()}
        />
      )}

      {plan && (
        <>
          <section className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-border-subtle bg-surface-raised/60 p-3">
              <h2 className="mb-3 text-sm font-semibold">{t("prototype.plan.projectContext")}</h2>
              <div className="grid gap-2 sm:grid-cols-2">
                {(["product_summary", "audience", "visual_language", "shared_layout"] as const).map(
                  (key) => (
                    <label key={key} className="space-y-1 text-xs text-text-muted">
                      <span>{t(`prototype.plan.context.${key}`)}</span>
                      <Textarea
                        rows={2}
                        value={context[key]}
                        onChange={(event) => updateContextDraft(key, event.target.value)}
                      />
                    </label>
                  ),
                )}
              </div>
              <label className="mt-3 block space-y-1 text-xs text-text-muted">
                <span>{t("prototype.plan.globalInstruction")}</span>
                <Textarea
                  rows={2}
                  value={instruction}
                  onChange={(event) => updateInstructionDraft(event.target.value)}
                />
              </label>
            </div>
            <div className="rounded-lg border border-border-subtle bg-surface-raised/60 p-3">
              <h2 className="mb-3 text-sm font-semibold">{t("prototype.plan.evidence")}</h2>
              <div className="grid gap-2 text-xs text-text-muted sm:grid-cols-2">
                <div>
                  <span className="font-semibold text-foreground">
                    {t("prototype.plan.package")}:
                  </span>{" "}
                  {plan.scope.packages.join(", ") || "-"}
                </div>
                <div>
                  <span className="font-semibold text-foreground">
                    {t("prototype.plan.selectedCount", { count: selectedCount })}
                  </span>
                </div>
                {plan.diagnostics.map((diagnostic) => {
                  const message = prototypeDiagnosticMessage(diagnostic, locale);
                  return (
                    <div key={diagnostic} className="sm:col-span-2 text-status-awaiting">
                      {t(message.key, message.params)}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          <section
            className="flex flex-wrap items-center gap-2"
            aria-label={t("prototype.plan.action")}
          >
            {ACTION_FILTERS.map((value) => {
              const label =
                value === "all"
                  ? t("prototype.plan.filterAll")
                  : value === "low"
                    ? t("prototype.plan.filterLow")
                    : actionLabel(value, t);
              return (
                <Button
                  className="min-h-11"
                  key={value}
                  size="sm"
                  variant={filter === value ? "default" : "outline"}
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label}
                </Button>
              );
            })}
            <select
              value={surfaceFilter}
              onChange={(event) => setSurfaceFilter(event.target.value)}
              aria-label={t("prototype.plan.surface")}
              className="h-11 min-h-11 rounded-md border border-border-subtle bg-surface-base px-2 text-xs"
            >
              <option value="all">{t("prototype.plan.surfaceAll")}</option>
              {surfaces.map((surface) => (
                <option key={surface} value={surface}>
                  {surfaceLabel(surface, t)}
                </option>
              ))}
            </select>
            <Button
              className="min-h-11"
              size="sm"
              variant="outline"
              onClick={() => void setItemsSelected(filteredItems, true)}
              disabled={
                !filteredItems.some((item) => isPrototypePlanActionGeneratable(item.action)) ||
                plan.status === "analyzing" ||
                selectionSaving
              }
            >
              {t("prototype.plan.selectAll")}
            </Button>
            <Button
              className="min-h-11"
              size="sm"
              variant="outline"
              onClick={() => void setItemsSelected(filteredItems, false)}
              disabled={
                !filteredItems.some((item) => isPrototypePlanActionGeneratable(item.action)) ||
                plan.status === "analyzing" ||
                selectionSaving
              }
            >
              {t("prototype.plan.clearSelection")}
            </Button>
          </section>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
            <section className="min-w-0 overflow-hidden rounded-lg border border-border-subtle bg-surface-raised/60">
              <div className="hidden grid-cols-[44px_minmax(160px,1.3fr)_minmax(120px,1fr)_100px_100px] gap-2 border-b border-border-subtle px-3 py-2 text-xs font-semibold text-text-muted md:grid">
                <span aria-hidden="true" /> <span>{t("prototype.plan.titleLabel")}</span>
                <span>{t("prototype.plan.route")}</span>
                <span>{t("prototype.plan.confidence")}</span>
                <span>{t("prototype.plan.action")}</span>
              </div>
              <div className="divide-y divide-border-subtle">
                {groupedItems.map((group) => (
                  <section key={group.key} aria-label={`${group.packageRoot} ${group.surfaceKind}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2 bg-surface-base/70 px-3 py-2 text-xs font-semibold">
                      <span className="min-w-0 break-words">
                        {group.packageRoot || t("prototype.plan.packageRoot")} ·{" "}
                        {surfaceLabel(group.surfaceKind, t)}
                      </span>
                      <div className="flex gap-1">
                        <Button
                          className="min-h-11"
                          size="sm"
                          variant="ghost"
                          onClick={() => void setItemsSelected(group.items, true)}
                          disabled={
                            !group.items.some((item) =>
                              isPrototypePlanActionGeneratable(item.action),
                            ) ||
                            plan.status === "analyzing" ||
                            selectionSaving
                          }
                        >
                          {t("prototype.plan.selectGroup")}
                        </Button>
                        <Button
                          className="min-h-11"
                          size="sm"
                          variant="ghost"
                          onClick={() => void setItemsSelected(group.items, false)}
                          disabled={
                            !group.items.some((item) =>
                              isPrototypePlanActionGeneratable(item.action),
                            ) ||
                            plan.status === "analyzing" ||
                            selectionSaving
                          }
                        >
                          {t("prototype.plan.clearGroup")}
                        </Button>
                      </div>
                    </div>
                    {group.items.map((item) => (
                      <div
                        key={item.id}
                        className={cn(
                          "grid grid-cols-[44px_minmax(0,1fr)] gap-2 border-t border-border-subtle px-3 py-3 text-xs md:grid-cols-[44px_minmax(160px,1.3fr)_minmax(120px,1fr)_100px_100px]",
                          activeItemId === item.id && "bg-brand/10",
                        )}
                      >
                        <label className="flex size-11 items-start justify-center pt-1">
                          <input
                            type="checkbox"
                            checked={item.selected && isPrototypePlanActionGeneratable(item.action)}
                            onChange={() => void setItemsSelected([item], !item.selected)}
                            disabled={
                              !isPrototypePlanActionGeneratable(item.action) ||
                              plan.status === "analyzing" ||
                              selectionSaving
                            }
                            aria-label={item.title}
                            className="size-4 accent-brand"
                          />
                        </label>
                        <button
                          type="button"
                          className="min-h-11 min-w-0 text-left"
                          aria-current={activeItemId === item.id ? "true" : undefined}
                          onClick={() => selectActiveItem(item)}
                        >
                          <div className="break-words font-semibold text-foreground">
                            {item.title}
                          </div>
                          <div className="break-words text-text-muted md:hidden">
                            {item.package_root} · {surfaceLabel(item.surface_kind, t)}
                          </div>
                        </button>
                        <div className="col-start-2 min-w-0 md:col-start-auto">
                          <div className="break-all font-mono text-text-muted">
                            {item.route_patterns.join(", ") || "-"}
                          </div>
                          <PrototypeEvidenceList item={item} locale={locale} t={t} />
                        </div>
                        <div className="col-start-2 flex flex-wrap gap-2 md:contents">
                          <Badge variant={item.confidence === "low" ? "destructive" : "outline"}>
                            {confidenceLabel(item.confidence, t)}
                          </Badge>
                          <Badge
                            variant={item.action === "unsupported" ? "destructive" : "secondary"}
                          >
                            {actionLabel(item.action, t)}
                          </Badge>
                          {item.review_status !== "confirmed" ? (
                            <Badge variant="outline">
                              {item.review_status === "needs_confirmation"
                                ? t("prototype.plan.needsConfirmation")
                                : t("prototype.plan.discoveryInProgress")}
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </section>
                ))}
                {filteredItems.length === 0 && (
                  <div className="px-4 py-10 text-center text-sm text-text-muted">
                    {t("prototype.plan.noItems")}
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-border-subtle bg-surface-raised/60 p-4">
              <h2 className="mb-3 text-sm font-semibold">{t("prototype.plan.editItem")}</h2>
              {itemDraft ? (
                <div className="space-y-3">
                  <label className="block space-y-1 text-xs text-text-muted">
                    <span>{t("prototype.plan.titleLabel")}</span>
                    <Input
                      className="min-h-11 sm:min-h-0"
                      value={itemDraft.title}
                      onChange={(event) =>
                        updateItemDraft({ ...itemDraft, title: event.target.value })
                      }
                    />
                  </label>
                  <label className="block space-y-1 text-xs text-text-muted">
                    <span>{t("prototype.plan.summaryLabel")}</span>
                    <Textarea
                      rows={3}
                      value={itemDraft.summary}
                      onChange={(event) =>
                        updateItemDraft({ ...itemDraft, summary: event.target.value })
                      }
                    />
                  </label>
                  <label className="block space-y-1 text-xs text-text-muted">
                    <span>{t("prototype.plan.briefLabel")}</span>
                    <Textarea
                      rows={7}
                      value={itemDraft.brief}
                      onChange={(event) =>
                        updateItemDraft({ ...itemDraft, brief: event.target.value })
                      }
                    />
                  </label>
                  <label className="block space-y-1 text-xs text-text-muted">
                    <span>{t("prototype.plan.statesLabel")}</span>
                    <Textarea
                      rows={4}
                      value={itemDraft.states.join("\n")}
                      onChange={(event) =>
                        updateItemDraft({
                          ...itemDraft,
                          states: event.target.value.split("\n"),
                        })
                      }
                    />
                  </label>
                  {itemDraft.action === "unsupported" && (
                    <div className="text-xs text-status-failed">
                      {t("prototype.plan.unsupportedReason")}
                    </div>
                  )}
                  {itemDraft.confidence === "low" && (
                    <div className="text-xs text-status-awaiting">
                      {t("prototype.plan.partialReason")}
                    </div>
                  )}
                  <Button
                    className="min-h-11"
                    size="sm"
                    onClick={() => void saveItem()}
                    disabled={saveState === "saving" || plan.status === "analyzing"}
                  >
                    <Check size={14} />
                    {saveState === "saving" ? t("prototype.plan.saving") : t("prototype.plan.save")}
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-text-muted">{t("prototype.plan.noItems")}</p>
              )}
            </section>
          </div>
        </>
      )}
      {!plan && !loadError && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="animate-spin" size={16} />
          {t("prototype.plan.analyzing")}
        </div>
      )}
      <Dialog open={confirmGenerate} onOpenChange={setConfirmGenerate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("prototype.plan.generateConfirmTitle")}</DialogTitle>
            <DialogDescription>
              {t("prototype.plan.generateConfirmDescription", { count: selectedCount })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button className="min-h-11" variant="ghost" onClick={() => setConfirmGenerate(false)}>
              {t("prototype.createCancel")}
            </Button>
            <Button
              className="min-h-11"
              onClick={() => void startGeneration()}
              disabled={generationStarting || selectionSaving || saveState === "saving"}
            >
              {generationStarting ? (
                <Loader2 className="animate-spin" size={14} />
              ) : (
                <Sparkles size={14} />
              )}
              {t("prototype.plan.generateConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
