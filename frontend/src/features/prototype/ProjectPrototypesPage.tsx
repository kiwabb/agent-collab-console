"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Boxes,
  Check,
  FilePlus2,
  ListChecks,
  Loader2,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";

import {
  createPrototype,
  createPrototypePlan,
  getLatestPrototypePlan,
  getPrototype,
  getPrototypePlanFeatureConfig,
  getRegenerateAllStreamUrl,
  listPrototypes,
} from "@/lib/api/prototypes";
import type { Project, Prototype, PrototypeDetail } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { Loader } from "@/components/ui/loader";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { PrototypeCanvas } from "./PrototypeCanvas";
import { PrototypePageRail } from "./PrototypePageRail";
import {
  buildPrototypeRouteTargets,
  matchPrototypeRoute,
  readPrototypeRoutePatterns,
} from "./prototypeNavigation";
import {
  parseSseRecord,
  readFailedPrototypeItems,
  readSseErrorMessage,
  readSseNumber,
  readSseString,
  readSseStringArray,
} from "./prototypeStreamEvents";

interface Props {
  projectId: string;
  project: Project | null;
}

type RegenItemStatus = "pending" | "streaming" | "done" | "error";

interface RegenItem {
  prototypeId: string;
  title: string;
  status: RegenItemStatus;
  versionNo?: number | undefined;
  message?: string | undefined;
}

interface RegenState {
  total: number;
  items: Record<string, RegenItem>;
  done: boolean;
  okCount: number;
  failedCount: number;
}

const INITIAL_REGEN: RegenState = {
  total: 0,
  items: {},
  done: false,
  okCount: 0,
  failedCount: 0,
};

/**
 * Project-level prototype design tool page (PRD 06-23).
 *
 * Layout: thin wrapper that hosts the sidebar (prototype list) and the
 * canvas (PrototypeCanvas). State is local — there's no real-time
 * collaboration channel for this surface, so a single fetch on mount
 * plus imperative refetches after mutations is plenty.
 *
 * Refresh strategy: after `createPrototype` we eagerly insert the new
 * prototype so the sidebar updates without a full refetch, then refetch
 * the list to pick up any server-side derived fields (timestamps).
 *
 * Batch regenerate (PRD 06-23-batch): the header exposes a "Regenerate
 * all" button that opens a confirmation, then opens an SSE stream against
 * `/projects/{id}/prototypes/regenerate-all/stream`. A progress dialog
 * surfaces per-prototype status while the stream is in flight, and a
 * summary toast fires on `all_done`. The list is refetched at the end so
 * the `current_version` chips pick up the new versions.
 */
export function ProjectPrototypesPage({ projectId, project }: Props) {
  const { locale, t } = useI18n();
  const { addToast } = useToast();

  const [prototypes, setPrototypes] = useState<Prototype[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeRoutePattern, setActiveRoutePattern] = useState<string | null>(null);
  const [detail, setDetail] = useState<PrototypeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBrief, setDraftBrief] = useState("");
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [planInstruction, setPlanInstruction] = useState("");
  const [planCreating, setPlanCreating] = useState(false);
  const [latestPlanOpening, setLatestPlanOpening] = useState(false);
  const [planFeatureEnabled, setPlanFeatureEnabled] = useState<boolean | null>(null);
  const [planFeatureError, setPlanFeatureError] = useState<string | null>(null);
  const [planFeatureLoading, setPlanFeatureLoading] = useState(false);

  // Batch-regen state. The confirmation dialog and the progress dialog
  // share the same lifecycle — confirm → start stream → open progress →
  // stream ends → toast + auto-close (user can close manually too).
  const [confirmRegenOpen, setConfirmRegenOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [regen, setRegen] = useState<RegenState>(INITIAL_REGEN);
  const sourceRef = useRef<EventSource | null>(null);
  const planFeatureRequestIdRef = useRef(0);
  const planCreateInFlightRef = useRef(false);

  const loadPlanFeatureConfig = useCallback(async () => {
    const requestId = planFeatureRequestIdRef.current + 1;
    planFeatureRequestIdRef.current = requestId;
    setPlanFeatureLoading(true);
    try {
      const config = await getPrototypePlanFeatureConfig();
      if (planFeatureRequestIdRef.current !== requestId) return;
      setPlanFeatureEnabled(config.enabled);
      setPlanFeatureError(null);
    } catch (err) {
      console.error("prototype plan feature config load failed:", err);
      if (planFeatureRequestIdRef.current !== requestId) return;
      setPlanFeatureError(err instanceof Error ? err.message : String(err));
    } finally {
      if (planFeatureRequestIdRef.current === requestId) setPlanFeatureLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPlanFeatureConfig();
    return () => {
      planFeatureRequestIdRef.current += 1;
    };
  }, [loadPlanFeatureConfig]);

  const refetchList = useCallback(async () => {
    try {
      const list = await listPrototypes(projectId);
      setPrototypes(list);
      setListError(null);
      return list;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("prototype list load failed:", err);
      setListError(message);
      addToast({
        type: "error",
        title: t("prototype.listLoadFailed"),
        message,
      });
      return null;
    }
  }, [projectId, addToast, t]);

  // Initial list load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await refetchList();
      if (cancelled || !list) return;
      const firstPrototype = list[0];
      if (firstPrototype && !activeId) {
        setActiveId(firstPrototype.id);
        setActiveRoutePattern(readPrototypeRoutePatterns(firstPrototype)[0] ?? null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refetchList, activeId]);

  // Load detail (prototype + versions) whenever the active selection changes.
  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getPrototype(activeId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) {
          addToast({
            type: "error",
            title: t("prototype.toast.createFailed"),
            message: err instanceof Error ? err.message : String(err),
          });
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, addToast, t]);

  const handleCreate = useCallback(async () => {
    const title = draftTitle.trim();
    const brief = draftBrief.trim();
    if (!title || !brief) return;
    try {
      const created = await createPrototype(projectId, { title, brief });
      addToast({ type: "success", title: t("prototype.toast.created") });
      setCreating(false);
      setDraftTitle("");
      setDraftBrief("");
      // Optimistic insert so the new prototype appears immediately.
      setPrototypes((prev) => [created, ...(prev ?? [])]);
      setActiveId(created.id);
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.toast.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [draftTitle, draftBrief, projectId, addToast, t]);

  const handleCreatePlan = useCallback(async () => {
    if (planCreateInFlightRef.current) return;
    planCreateInFlightRef.current = true;
    setPlanCreating(true);
    try {
      const result = await createPrototypePlan(projectId, planInstruction, locale);
      window.location.assign(`/projects/${projectId}/prototypes/plans/${result.plan_id}`);
    } catch (err) {
      planCreateInFlightRef.current = false;
      setPlanCreating(false);
      addToast({
        type: "error",
        title: t("prototype.plan.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [projectId, planInstruction, locale, addToast, t]);

  const openPlanDialog = useCallback(async () => {
    try {
      const latest = await getLatestPrototypePlan(projectId);
      setPlanInstruction(latest?.global_instruction ?? "");
      setPlanDialogOpen(true);
    } catch (err) {
      console.error("latest prototype plan load failed:", err);
      addToast({
        type: "error",
        title: t("prototype.plan.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [projectId, addToast, t]);

  const openLatestPlan = useCallback(async () => {
    setLatestPlanOpening(true);
    try {
      const latest = await getLatestPrototypePlan(projectId);
      if (!latest) {
        addToast({ type: "info", title: t("prototype.plan.latestMissing") });
        return;
      }
      window.location.assign(`/projects/${projectId}/prototypes/plans/${latest.id}`);
    } catch (err) {
      console.error("latest prototype plan open failed:", err);
      addToast({
        type: "error",
        title: t("prototype.plan.latestOpenFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLatestPlanOpening(false);
    }
  }, [projectId, addToast, t]);

  const handleVersionsChanged = useCallback(async () => {
    // Re-fetch both list (for current_version chip) and detail (new version row).
    const list = await refetchList();
    if (activeId) {
      try {
        const nextDetail = await getPrototype(activeId);
        setDetail(nextDetail);
      } catch (err) {
        console.error("prototype detail refresh failed:", err);
        addToast({
          type: "error",
          title: t("prototype.toast.versionLoadFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
    if (list?.length === 0) setActiveId(null);
  }, [refetchList, activeId, addToast, t]);

  const handlePrototypeDeleted = useCallback(async () => {
    const list = await refetchList();
    if (!list) return;
    const firstPrototype = list[0];
    if (firstPrototype) {
      setActiveId(firstPrototype.id);
      setActiveRoutePattern(readPrototypeRoutePatterns(firstPrototype)[0] ?? null);
    } else {
      setActiveId(null);
      setActiveRoutePattern(null);
    }
    setDetail(null);
  }, [refetchList]);

  // Tear down the SSE connection on unmount; an in-flight batch must not
  // outlive this component (matters when the user navigates away mid-batch).
  useEffect(() => {
    return () => {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    };
  }, []);

  // Close the progress dialog automatically after `all_done` so the user
  // isn't forced to dismiss it manually. We keep it open for a beat so the
  // final status row is visible before the close animation runs.
  useEffect(() => {
    if (!regen.done || !progressOpen) return;
    const handle = window.setTimeout(() => setProgressOpen(false), 1200);
    return () => window.clearTimeout(handle);
  }, [regen.done, progressOpen]);

  const startBatch = useCallback(() => {
    setConfirmRegenOpen(false);
    setRegen(INITIAL_REGEN);
    setProgressOpen(true);

    // Make sure any previous stream is closed before opening a new one.
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    const url = getRegenerateAllStreamUrl(projectId);
    const source = new EventSource(url);
    sourceRef.current = source;

    source.addEventListener("batch_meta", (ev) => {
      const data = parseSseRecord(ev);
      const count = data ? readSseNumber(data, "count") : null;
      if (count === null) return;
      setRegen((s) => ({ ...s, total: count }));
    });

    source.addEventListener("prototype_start", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const prototypeId = readSseString(data, "prototype_id");
      const title = readSseString(data, "title");
      if (!prototypeId || !title) return;
      setRegen((s) => ({
        ...s,
        items: {
          ...s.items,
          [prototypeId]: {
            prototypeId,
            title,
            status: "streaming",
          },
        },
      }));
    });

    source.addEventListener("prototype_done", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const prototypeId = readSseString(data, "prototype_id");
      const versionNo = readSseNumber(data, "version_no");
      if (!prototypeId || versionNo === null) return;
      setRegen((s) => {
        const cur = s.items[prototypeId];
        if (!cur) return s;
        return {
          ...s,
          okCount: s.okCount + 1,
          items: {
            ...s.items,
            [prototypeId]: { ...cur, status: "done", versionNo },
          },
        };
      });
    });

    source.addEventListener("prototype_error", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const prototypeId = readSseString(data, "prototype_id");
      const message = readSseString(data, "message");
      if (!prototypeId || !message) return;
      setRegen((s) => {
        const cur = s.items[prototypeId];
        if (!cur) return s;
        return {
          ...s,
          failedCount: s.failedCount + 1,
          items: {
            ...s.items,
            [prototypeId]: { ...cur, status: "error", message },
          },
        };
      });
    });

    source.addEventListener("all_done", (ev) => {
      const data = parseSseRecord(ev);
      const ok = data ? readSseStringArray(data, "ok") : null;
      const failed = data ? readFailedPrototypeItems(data, "failed") : null;
      if (ok && failed) {
        // Reconcile any prototypes the server reported but that we
        // somehow missed `prototype_start` for (defensive — shouldn't
        // happen, but the server is the source of truth).
        setRegen((s) => {
          const items = { ...s.items };
          for (const id of ok) {
            if (!items[id]) {
              items[id] = {
                prototypeId: id,
                title: "",
                status: "done",
                versionNo: undefined,
              };
            }
          }
          for (const f of failed) {
            if (!items[f.prototype_id]) {
              items[f.prototype_id] = {
                prototypeId: f.prototype_id,
                title: "",
                status: "error",
                message: f.message,
              };
            }
          }
          return {
            ...s,
            items,
            done: true,
            okCount: ok.length,
            failedCount: failed.length,
          };
        });
        source.close();
        if (sourceRef.current === source) sourceRef.current = null;
        addToast({
          type: failed.length > 0 ? "warning" : "success",
          title: t("prototype.regenerateAll.dialogTitle"),
          message:
            failed.length > 0
              ? t("prototype.regenerateAll.summaryWithFailures", {
                  ok: ok.length,
                  failed: failed.length,
                })
              : t("prototype.regenerateAll.summary", {
                  ok: ok.length,
                  failed: failed.length,
                }),
        });
        // Refresh list so the version chip and per-prototype details
        // pick up the new versions.
        refetchList();
      } else {
        // If we can't parse all_done we still want to stop the stream.
        source.close();
        if (sourceRef.current === source) sourceRef.current = null;
        setRegen((s) => ({ ...s, done: true }));
      }
    });

    source.addEventListener("error", (ev) => {
      // EventSource fires `error` for both transport failures and custom
      // server `event: error` frames. If the server sent us a payload,
      // surface it; otherwise let the browser handle reconnection (but
      // we still want to abort on close since this endpoint is one-shot).
      try {
        const message = readSseErrorMessage(ev);
        if (message) {
          source.close();
          if (sourceRef.current === source) sourceRef.current = null;
          setRegen((s) => ({ ...s, done: true }));
          addToast({
            type: "error",
            title: t("prototype.regenerateAll.dialogTitle"),
            message,
          });
        } else if (!regen.done) {
          // Transport-level disconnect before all_done: treat as fatal
          // and surface. The endpoint is one-shot so we don't want the
          // browser to keep retrying on its own.
          source.close();
          if (sourceRef.current === source) sourceRef.current = null;
          setRegen((s) => ({ ...s, done: true }));
          addToast({
            type: "error",
            title: t("prototype.regenerateAll.dialogTitle"),
            message: t("prototype.toast.iterateFailed"),
          });
        }
      } catch {
        // Defensive: ignore.
      }
    });
  }, [projectId, addToast, t, refetchList, regen.done]);

  // Cleanup if the progress dialog is closed mid-stream. The user can
  // dismiss it once `all_done` has fired (regen.done); otherwise we abort.
  const handleProgressOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !regen.done) {
        // Don't let the user silently drop a running batch — keep the
        // dialog open. They'll see the stream continue.
        return;
      }
      setProgressOpen(open);
    },
    [regen.done],
  );

  const hasPrototypes = prototypes !== null && prototypes.length > 0;
  const batchRunning = progressOpen && !regen.done;
  const sortedItems = useMemo(() => {
    return Object.values(regen.items).sort((a, b) => a.title.localeCompare(b.title));
  }, [regen.items]);
  const regenProcessed = regen.okCount + regen.failedCount;
  const regenPercent =
    regen.total > 0 ? Math.min(100, Math.round((regenProcessed / regen.total) * 100)) : 0;
  const routeTargets = useMemo(() => buildPrototypeRouteTargets(prototypes ?? []), [prototypes]);
  const handlePrototypeSelect = useCallback((prototype: Prototype) => {
    setActiveId(prototype.id);
    setActiveRoutePattern(readPrototypeRoutePatterns(prototype)[0] ?? null);
  }, []);
  const handlePrototypeNavigate = useCallback(
    (route: string) => {
      const target = matchPrototypeRoute(route, routeTargets);
      if (!target) {
        addToast({
          type: "error",
          title: t("prototype.routeNotFoundTitle"),
          message: t("prototype.routeNotFoundMessage", { route }),
        });
        return;
      }
      setActiveId(target.prototypeId);
      setActiveRoutePattern(target.routePattern);
    },
    [routeTargets, addToast, t],
  );

  return (
    <section
      className="flex min-h-0 min-w-0 flex-col gap-3 overflow-x-hidden"
      data-density="compact"
    >
      <header className="flex flex-col gap-3 border-b border-border-subtle pb-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{t("prototype.title")}</h1>
            {prototypes && (
              <Badge variant="outline">
                {t("prototype.pageCount", { count: prototypes.length })}
              </Badge>
            )}
          </div>
          <p className="mt-1 truncate text-sm text-text-muted">
            {project?.name ?? t("workspace.projectPage.titleFallback")}
          </p>
        </div>
        <div className="flex items-center gap-2 self-stretch sm:self-auto">
          <Button
            className="min-h-11 min-w-0 flex-1 sm:min-h-0 sm:flex-none"
            size="sm"
            onClick={planFeatureEnabled ? () => void openPlanDialog() : () => setCreating(true)}
            disabled={planCreating}
          >
            {planFeatureEnabled ? <Sparkles size={14} /> : <Plus size={14} />}
            {planFeatureEnabled ? t("prototype.plan.fromProject") : t("prototype.newTitle")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-border bg-background text-foreground outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring sm:min-h-7 sm:min-w-7"
              aria-label={t("prototype.moreActions")}
              title={t("prototype.moreActions")}
            >
              <MoreHorizontal size={16} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-52">
              {planFeatureEnabled && (
                <DropdownMenuItem
                  onClick={() => void openLatestPlan()}
                  disabled={latestPlanOpening}
                >
                  {latestPlanOpening ? (
                    <Loader2 className="animate-spin" size={14} />
                  ) : (
                    <ListChecks size={14} />
                  )}
                  {t("prototype.plan.viewLatest")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => setCreating(true)}>
                <FilePlus2 size={14} />
                {t("prototype.newTitle")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => window.location.assign(`/projects/${projectId}/prototypes/studio`)}
              >
                <Boxes size={14} />
                {t("prototype.structured.open")}
              </DropdownMenuItem>
              {hasPrototypes && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => setConfirmRegenOpen(true)}
                    disabled={batchRunning}
                  >
                    <RefreshCw size={14} className={cn(batchRunning && "animate-spin")} />
                    {t("prototype.regenerateAll.button")}
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {planFeatureError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-status-failed/40 bg-status-failed/10 px-3 py-2 text-xs text-status-failed"
        >
          <span className="min-w-0 break-words">
            {t("prototype.plan.featureConfigLoadFailed", { message: planFeatureError })}
          </span>
          <Button
            className="min-h-11"
            size="sm"
            variant="outline"
            onClick={() => void loadPlanFeatureConfig()}
            disabled={planFeatureLoading}
          >
            <RefreshCw className={cn(planFeatureLoading && "animate-spin")} size={14} />
            {t("prototype.plan.featureConfigRetry")}
          </Button>
        </div>
      )}

      {listError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 border-l-2 border-status-failed px-3 py-2 text-xs text-status-failed"
        >
          <span className="min-w-0 break-words">
            {t("prototype.listLoadFailedDetail", { message: listError })}
          </span>
          <Button
            className="min-h-11 sm:min-h-0"
            size="sm"
            variant="outline"
            onClick={() => void refetchList()}
          >
            <RefreshCw size={14} />
            {t("prototype.retry")}
          </Button>
        </div>
      )}

      <Dialog open={planDialogOpen} onOpenChange={setPlanDialogOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("prototype.plan.dialogTitle")}</DialogTitle>
            <DialogDescription>{t("prototype.plan.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <Textarea
            rows={4}
            value={planInstruction}
            onChange={(event) => setPlanInstruction(event.target.value)}
            placeholder={t("prototype.plan.instructionPlaceholder")}
            aria-label={t("prototype.plan.instructionLabel")}
          />
          <DialogFooter>
            <Button
              className="min-h-11 sm:min-h-0"
              variant="ghost"
              onClick={() => setPlanDialogOpen(false)}
              disabled={planCreating}
            >
              {t("prototype.createCancel")}
            </Button>
            <Button
              className="min-h-11 sm:min-h-0"
              onClick={() => void handleCreatePlan()}
              disabled={planCreating}
            >
              {planCreating ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {t("prototype.plan.start")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("prototype.newTitle")}</DialogTitle>
            <DialogDescription>{t("prototype.manualCreateDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              className="min-h-11 sm:min-h-0"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              placeholder={t("prototype.titlePlaceholder")}
              aria-label={t("prototype.titleLabel")}
            />
            <Textarea
              rows={5}
              value={draftBrief}
              onChange={(event) => setDraftBrief(event.target.value)}
              placeholder={t("prototype.briefPlaceholder")}
              aria-label={t("prototype.briefLabel")}
            />
          </div>
          <DialogFooter>
            <Button
              className="min-h-11 sm:min-h-0"
              variant="ghost"
              onClick={() => {
                setCreating(false);
                setDraftTitle("");
                setDraftBrief("");
              }}
            >
              {t("prototype.createCancel")}
            </Button>
            <Button
              className="min-h-11 sm:min-h-0"
              onClick={() => void handleCreate()}
              disabled={!draftTitle.trim() || !draftBrief.trim()}
            >
              <Plus size={14} />
              {t("prototype.createButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <PrototypePageRail
          prototypes={prototypes}
          activeId={activeId}
          onSelect={handlePrototypeSelect}
          onCreate={() => setCreating(true)}
        />

        <main className="flex min-h-0 min-w-0 flex-col" id="prototype-workbench-main">
          {!activeId ? (
            <EmptyState title={t("prototype.empty")} />
          ) : detailLoading || !detail ? (
            <div className="flex min-h-[32rem] items-center justify-center">
              <Loader variant="card" label={t("prototype.loading")} />
            </div>
          ) : (
            <PrototypeCanvas
              key={detail.prototype.id}
              prototype={detail.prototype}
              versions={detail.versions}
              routeTargets={routeTargets}
              activeRoutePattern={activeRoutePattern}
              onNavigate={handlePrototypeNavigate}
              onVersionsChanged={handleVersionsChanged}
              onPrototypeDeleted={handlePrototypeDeleted}
            />
          )}
        </main>
      </div>

      <ConfirmDialog
        open={confirmRegenOpen}
        onOpenChange={setConfirmRegenOpen}
        title={t("prototype.regenerateAll.confirmTitle")}
        description={t("prototype.regenerateAll.confirmDescription")}
        confirmText={t("prototype.regenerateAll.confirmButton")}
        variant="warning"
        onConfirm={startBatch}
      />

      <Dialog open={progressOpen} onOpenChange={handleProgressOpenChange}>
        <DialogContent className="sm:max-w-lg" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("prototype.regenerateAll.dialogTitle")}</DialogTitle>
            <DialogDescription>
              <span role="status" aria-live="polite" aria-atomic="true">
                {regen.total > 0 ? `${regenProcessed}/${regen.total}` : ""}
              </span>
            </DialogDescription>
          </DialogHeader>
          <div
            className="h-2 overflow-hidden rounded-sm bg-surface-base"
            role="progressbar"
            aria-label={t("prototype.regenerateAll.dialogTitle")}
            aria-valuemin={0}
            aria-valuemax={Math.max(regen.total, 1)}
            aria-valuenow={regenProcessed}
            aria-valuetext={
              regen.total > 0
                ? `${regenProcessed}/${regen.total}`
                : t("prototype.regenerateAll.statusPending")
            }
          >
            <div className="h-full bg-brand" style={{ width: `${regenPercent}%` }} />
          </div>
          <div className="max-h-[60vh] overflow-auto">
            {sortedItems.length === 0 ? (
              <div className="flex items-center gap-2 py-6 text-sm text-text-muted">
                <Loader2 size={14} className="animate-spin" />
                {t("prototype.regenerateAll.statusPending")}
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-border-subtle">
                {sortedItems.map((item) => (
                  <li key={item.prototypeId} className="flex items-center gap-3 py-2 text-sm">
                    <StatusGlyph status={item.status} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{item.title || item.prototypeId}</div>
                      <div className="text-xs text-text-muted">{statusLabel(item, t)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <DialogFooter showCloseButton={regen.done}>
            {regen.done && (
              <Button className="min-h-11 sm:min-h-0" onClick={() => setProgressOpen(false)}>
                {t("issue.close")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function StatusGlyph({ status }: { status: RegenItemStatus }) {
  if (status === "done") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-status-success/15 text-status-success">
        <Check size={12} />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-status-failed/15 text-status-failed">
        <X size={12} />
      </span>
    );
  }
  if (status === "streaming") {
    return (
      <span className="flex size-5 items-center justify-center text-brand">
        <Loader2 size={14} className="animate-spin" />
      </span>
    );
  }
  return (
    <span className="flex size-5 items-center justify-center rounded-full border border-border-subtle text-text-muted/60">
      <span className="size-1.5 rounded-full bg-current" />
    </span>
  );
}

function statusLabel(
  item: RegenItem,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (item.status === "done" && item.versionNo !== undefined) {
    return t("prototype.regenerateAll.statusDone", { version: item.versionNo });
  }
  if (item.status === "error") {
    return t("prototype.regenerateAll.statusError", {
      message: item.message ?? "",
    });
  }
  if (item.status === "streaming") {
    return t("prototype.regenerateAll.statusStreaming");
  }
  return t("prototype.regenerateAll.statusPending");
}
