"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Code2, Loader2, Plus, RefreshCw, X } from "lucide-react";

import {
  createPrototype,
  getGenerateFromCodeStreamUrl,
  getPrototype,
  getRegenerateAllStreamUrl,
  listPrototypeCodeCandidates,
  listPrototypes,
  MAX_CANDIDATE_QUERY_TEXT_CHARS,
} from "@/lib/api/prototypes";
import type { Project, Prototype, PrototypeCodeCandidate, PrototypeDetail } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
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
  buildCodeCandidateBriefOverrides,
  buildSelectedCodeCandidateInstructions,
  countModifiedCodeCandidateBriefs,
  isCodeCandidateBriefModified,
} from "./codeCandidateBriefs";
import { PrototypeCanvas } from "./PrototypeCanvas";
import {
  parseSseRecord,
  readCodeCandidateAction,
  readCodeGenerationSummary,
  readFailedPrototypeItems,
  readPrototypeCodeCandidates,
  readSseErrorMessage,
  readSseNullableString,
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

type CodeItemStatus =
  | "pending"
  | "capturing"
  | "capture_failed"
  | "skipped"
  | "generating"
  | "done"
  | "failed"
  | "unsupported";

interface CodeGenItem {
  candidateId: string;
  title: string;
  route: string;
  sourcePath: string;
  action: PrototypeCodeCandidate["action"];
  status: CodeItemStatus;
  prototypeId?: string | null | undefined;
  versionNo?: number | undefined;
  message?: string | undefined;
}

interface CodeGenState {
  total: number;
  items: Record<string, CodeGenItem>;
  done: boolean;
  created: number;
  regenerated: number;
  skipped: number;
  failed: number;
  unsupported: number;
}

const INITIAL_REGEN: RegenState = {
  total: 0,
  items: {},
  done: false,
  okCount: 0,
  failedCount: 0,
};

const INITIAL_CODE_GEN: CodeGenState = {
  total: 0,
  items: {},
  done: false,
  created: 0,
  regenerated: 0,
  skipped: 0,
  failed: 0,
  unsupported: 0,
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
  const { t } = useI18n();
  const { addToast } = useToast();

  const [prototypes, setPrototypes] = useState<Prototype[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PrototypeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBrief, setDraftBrief] = useState("");

  // Batch-regen state. The confirmation dialog and the progress dialog
  // share the same lifecycle — confirm → start stream → open progress →
  // stream ends → toast + auto-close (user can close manually too).
  const [confirmRegenOpen, setConfirmRegenOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [regen, setRegen] = useState<RegenState>(INITIAL_REGEN);
  const sourceRef = useRef<EventSource | null>(null);
  const [codeScanOpen, setCodeScanOpen] = useState(false);
  const [codeCandidates, setCodeCandidates] = useState<PrototypeCodeCandidate[] | null>(null);
  const [codeScanLoading, setCodeScanLoading] = useState(false);
  const [codeProgressOpen, setCodeProgressOpen] = useState(false);
  const [codeGen, setCodeGen] = useState<CodeGenState>(INITIAL_CODE_GEN);
  const [selectedCodeCandidateIds, setSelectedCodeCandidateIds] = useState<string[]>([]);
  const [codeInstruction, setCodeInstruction] = useState("");
  const [codeCandidateInstructions, setCodeCandidateInstructions] = useState<
    Record<string, string>
  >({});
  const [codeCandidateBriefs, setCodeCandidateBriefs] = useState<Record<string, string>>({});
  const [expandedCodeBriefIds, setExpandedCodeBriefIds] = useState<string[]>([]);
  const [useRuntimeEvidence, setUseRuntimeEvidence] = useState(false);
  const [runtimeBaseUrl, setRuntimeBaseUrl] = useState("http://localhost:4000");
  const codeSourceRef = useRef<EventSource | null>(null);

  const refetchList = useCallback(async () => {
    try {
      const list = await listPrototypes(projectId);
      setPrototypes(list);
      return list;
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.toast.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
      return [];
    }
  }, [projectId, addToast, t]);

  // Initial list load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await refetchList();
      if (cancelled) return;
      const firstPrototype = list[0];
      if (firstPrototype && !activeId) {
        setActiveId(firstPrototype.id);
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
          setDetail(null);
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

  const handleVersionsChanged = useCallback(async () => {
    // Re-fetch both list (for current_version chip) and detail (new version row).
    const list = await refetchList();
    if (activeId) {
      try {
        const d = await getPrototype(activeId);
        setDetail(d);
      } catch {
        // The detail fetch may race with the user navigating away;
        // a stale detail is preferable to a noisy toast here.
      }
    }
    if (list.length === 0) setActiveId(null);
  }, [refetchList, activeId]);

  const handlePrototypeDeleted = useCallback(async () => {
    const list = await refetchList();
    const firstPrototype = list[0];
    if (firstPrototype) setActiveId(firstPrototype.id);
    else setActiveId(null);
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
      if (codeSourceRef.current) {
        codeSourceRef.current.close();
        codeSourceRef.current = null;
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

  useEffect(() => {
    if (!codeGen.done || !codeProgressOpen) return;
    const handle = window.setTimeout(() => setCodeProgressOpen(false), 1400);
    return () => window.clearTimeout(handle);
  }, [codeGen.done, codeProgressOpen]);

  const openCodeScan = useCallback(async () => {
    setCodeScanOpen(true);
    setCodeScanLoading(true);
    setCodeCandidates(null);
    try {
      const result = await listPrototypeCodeCandidates(projectId);
      setCodeCandidates(result.candidates);
      setSelectedCodeCandidateIds(
        result.candidates
          .filter((candidate) => candidate.action === "create" || candidate.action === "regenerate")
          .map((candidate) => candidate.id),
      );
      setCodeCandidateInstructions({});
      setCodeCandidateBriefs(
        Object.fromEntries(
          result.candidates.map((candidate) => [candidate.id, candidate.editable_brief]),
        ),
      );
      setExpandedCodeBriefIds([]);
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.generateFromCode.scanFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
      setCodeCandidates([]);
      setSelectedCodeCandidateIds([]);
      setCodeCandidateInstructions({});
      setCodeCandidateBriefs({});
      setExpandedCodeBriefIds([]);
    } finally {
      setCodeScanLoading(false);
    }
  }, [projectId, addToast, t]);

  const startCodeGeneration = useCallback(() => {
    setCodeScanOpen(false);
    setCodeGen(INITIAL_CODE_GEN);
    setCodeProgressOpen(true);

    if (codeSourceRef.current) {
      codeSourceRef.current.close();
      codeSourceRef.current = null;
    }
    const candidateBriefOverrides = buildCodeCandidateBriefOverrides(
      codeCandidates ?? [],
      selectedCodeCandidateIds,
      codeCandidateBriefs,
    );
    const selectedCandidateInstructions = buildSelectedCodeCandidateInstructions(
      selectedCodeCandidateIds,
      codeCandidateInstructions,
    );
    const source = new EventSource(
      getGenerateFromCodeStreamUrl(projectId, {
        candidateIds: selectedCodeCandidateIds,
        instruction: codeInstruction,
        candidateInstructions: selectedCandidateInstructions,
        candidateBriefOverrides,
        useRuntimeEvidence,
        runtimeBaseUrl,
      }),
    );
    codeSourceRef.current = source;

    source.addEventListener("scan_meta", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const count = readSseNumber(data, "count");
      const candidates = readPrototypeCodeCandidates(data, "candidates");
      if (count === null || !candidates) return;
      const items: Record<string, CodeGenItem> = {};
      for (const candidate of candidates) {
        items[candidate.id] = {
          candidateId: candidate.id,
          title: candidate.title,
          route: candidate.route,
          sourcePath: candidate.primary_source_path,
          action: candidate.action,
          status: candidate.action === "unsupported" ? "unsupported" : "pending",
          prototypeId: candidate.prototype_id,
          message: candidate.unsupported_reason ?? undefined,
        };
      }
      setCodeGen((s) => ({ ...s, total: count, items }));
    });

    source.addEventListener("candidate_start", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const title = readSseString(data, "title");
      const route = readSseString(data, "route");
      const action = readCodeCandidateAction(data, "action");
      if (!candidateId || !title || !route || !action) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: {
              candidateId,
              title: cur?.title ?? title,
              route: cur?.route ?? route,
              sourcePath: cur?.sourcePath ?? "",
              action,
              status: action === "unsupported" ? "unsupported" : "generating",
              prototypeId: cur?.prototypeId,
              message: cur?.message,
            },
          },
        };
      });
    });

    source.addEventListener("candidate_capture", (ev) => {
      const data = parseSseRecord(ev);
      const candidateId = data ? readSseString(data, "candidate_id") : null;
      if (!candidateId) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: { ...cur, status: "capturing" },
          },
        };
      });
    });

    source.addEventListener("candidate_capture_done", (ev) => {
      const data = parseSseRecord(ev);
      const candidateId = data ? readSseString(data, "candidate_id") : null;
      if (!candidateId) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: { ...cur, status: "generating" },
          },
        };
      });
    });

    source.addEventListener("candidate_capture_failed", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const message = readSseString(data, "message");
      if (!candidateId || !message) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: {
              ...cur,
              status: "capture_failed",
              message,
            },
          },
        };
      });
    });

    source.addEventListener("candidate_skip", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const prototypeId = readSseNullableString(data, "prototype_id");
      if (!candidateId || prototypeId === undefined) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          skipped: s.skipped + 1,
          items: {
            ...s.items,
            [candidateId]: { ...cur, status: "skipped", prototypeId },
          },
        };
      });
    });

    source.addEventListener("prototype_created", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const prototypeId = readSseString(data, "prototype_id");
      if (!candidateId || !prototypeId) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: { ...cur, prototypeId },
          },
        };
      });
    });

    source.addEventListener("prototype_done", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const prototypeId = readSseString(data, "prototype_id");
      const versionNo = readSseNumber(data, "version_no");
      if (!candidateId || !prototypeId || versionNo === null) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: {
              ...cur,
              status: "done",
              prototypeId,
              versionNo,
            },
          },
        };
      });
    });

    source.addEventListener("prototype_error", (ev) => {
      const data = parseSseRecord(ev);
      if (!data) return;
      const candidateId = readSseString(data, "candidate_id");
      const prototypeId = readSseNullableString(data, "prototype_id");
      const message = readSseString(data, "message");
      if (!candidateId || prototypeId === undefined || !message) return;
      setCodeGen((s) => {
        const cur = s.items[candidateId];
        if (!cur) return s;
        return {
          ...s,
          items: {
            ...s.items,
            [candidateId]: {
              ...cur,
              status: cur.status === "unsupported" ? "unsupported" : "failed",
              prototypeId: prototypeId ?? cur.prototypeId,
              message,
            },
          },
        };
      });
    });

    source.addEventListener("all_done", (ev) => {
      const data = parseSseRecord(ev);
      const summary = data ? readCodeGenerationSummary(data) : null;
      if (summary) {
        setCodeGen((s) => ({ ...s, ...summary, done: true }));
        source.close();
        if (codeSourceRef.current === source) codeSourceRef.current = null;
        addToast({
          type: summary.failed > 0 ? "warning" : "success",
          title: t("prototype.generateFromCode.dialogTitle"),
          message: t("prototype.generateFromCode.summary", {
            created: summary.created,
            regenerated: summary.regenerated,
            skipped: summary.skipped,
            failed: summary.failed,
          }),
        });
        void refetchList().then((list) => {
          const firstPrototype = list[0];
          if (!activeId && firstPrototype) setActiveId(firstPrototype.id);
          if (activeId)
            void getPrototype(activeId)
              .then(setDetail)
              .catch(() => {});
        });
      } else {
        source.close();
        if (codeSourceRef.current === source) codeSourceRef.current = null;
        setCodeGen((s) => ({ ...s, done: true }));
      }
    });

    source.addEventListener("error", () => {
      if (codeSourceRef.current !== source) return;
      source.close();
      codeSourceRef.current = null;
      setCodeGen((s) => ({ ...s, done: true }));
      addToast({
        type: "error",
        title: t("prototype.generateFromCode.dialogTitle"),
        message: t("prototype.toast.iterateFailed"),
      });
    });
  }, [
    projectId,
    selectedCodeCandidateIds,
    codeInstruction,
    codeCandidateInstructions,
    codeCandidateBriefs,
    codeCandidates,
    useRuntimeEvidence,
    runtimeBaseUrl,
    addToast,
    t,
    refetchList,
    activeId,
  ]);

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
  const codeRunning = codeProgressOpen && !codeGen.done;
  const sortedItems = useMemo(() => {
    return Object.values(regen.items).sort((a, b) => a.title.localeCompare(b.title));
  }, [regen.items]);
  const sortedCodeItems = useMemo(() => {
    return Object.values(codeGen.items).sort((a, b) => a.route.localeCompare(b.route));
  }, [codeGen.items]);
  const codeCandidateCounts = useMemo(() => {
    const counts = { create: 0, regenerate: 0, skip: 0, unsupported: 0 };
    for (const candidate of codeCandidates ?? []) counts[candidate.action] += 1;
    return counts;
  }, [codeCandidates]);
  const selectedCodeCandidateSet = useMemo(
    () => new Set(selectedCodeCandidateIds),
    [selectedCodeCandidateIds],
  );
  const selectedCodeCandidateCount = selectedCodeCandidateIds.length;
  const selectableCodeCandidateIds = useMemo(
    () =>
      (codeCandidates ?? [])
        .filter((candidate) => candidate.action !== "unsupported")
        .map((candidate) => candidate.id),
    [codeCandidates],
  );
  const modifiedCodeCandidateBriefCount = useMemo(() => {
    return countModifiedCodeCandidateBriefs(
      codeCandidates ?? [],
      selectedCodeCandidateIds,
      codeCandidateBriefs,
    );
  }, [codeCandidates, codeCandidateBriefs, selectedCodeCandidateIds]);

  return (
    <section className="flex h-full flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">{t("prototype.title")}</h1>
          <p className="text-sm text-text-muted">{t("prototype.subtitle")}</p>
          {project?.repo_path && (
            <p className="font-mono text-[11px] text-text-muted/70">{project.repo_path}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={openCodeScan}
            disabled={codeScanLoading || codeRunning || batchRunning}
          >
            <Code2 size={14} className={cn(codeScanLoading && "animate-pulse")} />
            {t("prototype.generateFromCode.button")}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setConfirmRegenOpen(true)}
            disabled={!hasPrototypes || batchRunning || codeRunning}
            title={!hasPrototypes ? t("prototype.regenerateAll.disabledHint") : undefined}
          >
            <RefreshCw size={14} className={cn(batchRunning && "animate-spin")} />
            {t("prototype.regenerateAll.button")}
          </Button>
        </div>
      </header>

      <div className="grid min-h-[640px] flex-1 grid-cols-[280px_minmax(0,1fr)] gap-4">
        <aside className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface-raised/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              {t("prototype.title")}
            </span>
            <Button size="sm" variant="secondary" onClick={() => setCreating((v) => !v)}>
              <Plus size={14} />
              {t("prototype.newTitle")}
            </Button>
          </div>

          {creating && (
            <div className="flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface-base p-2">
              <Input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder={t("prototype.titlePlaceholder")}
              />
              <Textarea
                rows={3}
                value={draftBrief}
                onChange={(e) => setDraftBrief(e.target.value)}
                placeholder={t("prototype.briefPlaceholder")}
              />
              <div className="flex items-center justify-end gap-2">
                <Button
                  size="sm"
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
                  size="sm"
                  onClick={handleCreate}
                  disabled={!draftTitle.trim() || !draftBrief.trim()}
                >
                  {t("prototype.createButton")}
                </Button>
              </div>
            </div>
          )}

          <div className="flex-1 overflow-auto">
            {prototypes === null ? (
              <div className="flex h-32 items-center justify-center">
                <Loader variant="card" label="Loading…" />
              </div>
            ) : prototypes.length === 0 ? (
              <EmptyState title={t("prototype.empty")} />
            ) : (
              <ul className="flex flex-col gap-1">
                {prototypes.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setActiveId(p.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                        activeId === p.id
                          ? "border-brand bg-brand/15 text-foreground"
                          : "border-transparent bg-surface-base text-text-muted hover:text-foreground",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <div className="min-w-0 flex-1 truncate font-semibold">{p.title}</div>
                        <SourceBadge prototype={p} t={t} />
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-text-muted/80">
                        <span>
                          {p.current_version > 0
                            ? `v${p.current_version}`
                            : t("prototype.noVersionsYet")}
                        </span>
                        {p.source_kind === "code" && p.source_ref && (
                          <span className="min-w-0 truncate font-mono">{p.source_ref}</span>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col rounded-xl border border-border-subtle bg-surface-raised/40 p-3">
          {!activeId ? (
            <EmptyState title={t("prototype.empty")} />
          ) : detailLoading || !detail ? (
            <div className="flex h-full items-center justify-center">
              <Loader variant="card" label="Loading…" />
            </div>
          ) : (
            <PrototypeCanvas
              projectId={projectId}
              prototype={detail.prototype}
              versions={detail.versions}
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

      <Dialog open={codeScanOpen} onOpenChange={setCodeScanOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("prototype.generateFromCode.scanTitle")}</DialogTitle>
            <DialogDescription>
              {codeCandidates
                ? t("prototype.generateFromCode.scanSummary", {
                    count: codeCandidates.length,
                    create: codeCandidateCounts.create,
                    regenerate: codeCandidateCounts.regenerate,
                    skip: codeCandidateCounts.skip,
                  })
                : t("prototype.generateFromCode.scanSubtitle")}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[56vh] overflow-auto rounded-lg border border-border-subtle">
            {codeScanLoading ? (
              <div className="flex items-center gap-2 p-4 text-sm text-text-muted">
                <Loader2 size={14} className="animate-spin" />
                {t("prototype.generateFromCode.scanLoading")}
              </div>
            ) : !codeCandidates || codeCandidates.length === 0 ? (
              <div className="p-4 text-sm text-text-muted">
                {t("prototype.generateFromCode.noCandidates")}
              </div>
            ) : (
              <ul className="divide-y divide-border-subtle">
                {codeCandidates.map((candidate) => (
                  <li
                    key={candidate.id}
                    className="grid grid-cols-[auto_1fr_auto] gap-3 p-3 text-sm"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 size-4 rounded border-border-subtle bg-surface-input accent-brand"
                      checked={selectedCodeCandidateSet.has(candidate.id)}
                      disabled={candidate.action === "unsupported"}
                      aria-label={candidate.title}
                      onChange={(event) => {
                        setSelectedCodeCandidateIds((current) =>
                          event.target.checked
                            ? Array.from(new Set([...current, candidate.id]))
                            : current.filter((id) => id !== candidate.id),
                        );
                      }}
                    />
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium">{candidate.title}</span>
                        <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[10px] uppercase text-text-muted">
                          {t(`prototype.generateFromCode.action.${candidate.action}`)}
                        </span>
                        {isCodeCandidateBriefModified(candidate, codeCandidateBriefs) && (
                          <span
                            className="rounded-full border border-brand/40 bg-brand/10 px-2 py-0.5 text-[10px] uppercase text-brand"
                            title={t("prototype.generateFromCode.briefModified")}
                            aria-label={t("prototype.generateFromCode.briefModified")}
                          >
                            {t("prototype.generateFromCode.briefModified")}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 font-mono text-xs text-text-muted">
                        {candidate.route}
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-text-muted/70">
                        {candidate.primary_source_path}
                      </div>
                    </div>
                    <div className="font-mono text-[10px] text-text-muted/70">
                      {candidate.source_hash.slice(0, 18)}
                    </div>
                    <div className="col-span-3">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-[11px] text-text-muted/70">
                          {t("prototype.generateFromCode.editBriefHint")}
                        </p>
                        <div className="flex items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={candidate.action === "unsupported"}
                            onClick={() => {
                              setExpandedCodeBriefIds((current) =>
                                current.includes(candidate.id)
                                  ? current.filter((id) => id !== candidate.id)
                                  : [...current, candidate.id],
                              );
                            }}
                          >
                            {expandedCodeBriefIds.includes(candidate.id)
                              ? t("prototype.generateFromCode.hideBrief")
                              : t("prototype.generateFromCode.editBrief")}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={
                              candidate.action === "unsupported" ||
                              (codeCandidateBriefs[candidate.id] ?? "") === candidate.editable_brief
                            }
                            onClick={() => {
                              setCodeCandidateBriefs((current) => ({
                                ...current,
                                [candidate.id]: candidate.editable_brief,
                              }));
                            }}
                          >
                            {t("prototype.generateFromCode.resetBrief")}
                          </Button>
                        </div>
                      </div>
                      {expandedCodeBriefIds.includes(candidate.id) && (
                        <div className="mb-2 space-y-1">
                          <Textarea
                            rows={6}
                            className="font-mono text-xs"
                            maxLength={MAX_CANDIDATE_QUERY_TEXT_CHARS}
                            value={codeCandidateBriefs[candidate.id] ?? candidate.editable_brief}
                            aria-label={t("prototype.generateFromCode.editBriefAriaLabel")}
                            disabled={
                              candidate.action === "unsupported" ||
                              !selectedCodeCandidateSet.has(candidate.id)
                            }
                            onChange={(event) => {
                              const value = event.target.value;
                              setCodeCandidateBriefs((current) => ({
                                ...current,
                                [candidate.id]: value,
                              }));
                            }}
                            onInput={(event) => {
                              const value = event.currentTarget.value;
                              setCodeCandidateBriefs((current) => ({
                                ...current,
                                [candidate.id]: value,
                              }));
                            }}
                            placeholder={t("prototype.generateFromCode.editBriefPlaceholder")}
                          />
                          <p className="text-right font-mono text-[10px] text-text-muted/60">
                            {isCodeCandidateBriefModified(candidate, codeCandidateBriefs) && (
                              <span
                                className="mr-2 text-brand"
                                title={t("prototype.generateFromCode.briefModified")}
                                aria-label={t("prototype.generateFromCode.briefModified")}
                              >
                                {t("prototype.generateFromCode.briefModified")}
                              </span>
                            )}
                            {t("prototype.generateFromCode.editBriefLimit", {
                              current: (
                                codeCandidateBriefs[candidate.id] ?? candidate.editable_brief
                              ).length,
                              max: MAX_CANDIDATE_QUERY_TEXT_CHARS,
                            })}
                          </p>
                        </div>
                      )}
                      <div className="space-y-1">
                        <Textarea
                          rows={2}
                          maxLength={MAX_CANDIDATE_QUERY_TEXT_CHARS}
                          value={codeCandidateInstructions[candidate.id] ?? ""}
                          aria-label={t("prototype.generateFromCode.candidateInstructionAriaLabel")}
                          disabled={
                            candidate.action === "unsupported" ||
                            !selectedCodeCandidateSet.has(candidate.id)
                          }
                          onChange={(event) => {
                            const value = event.target.value;
                            setCodeCandidateInstructions((current) => ({
                              ...current,
                              [candidate.id]: value,
                            }));
                          }}
                          placeholder={t(
                            "prototype.generateFromCode.candidateInstructionPlaceholder",
                          )}
                        />
                        <p className="text-right font-mono text-[10px] text-text-muted/60">
                          {t("prototype.generateFromCode.candidateInstructionLimit", {
                            current: (codeCandidateInstructions[candidate.id] ?? "").length,
                            max: MAX_CANDIDATE_QUERY_TEXT_CHARS,
                          })}
                        </p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {codeCandidates && codeCandidates.length > 0 && (
            <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-base/70 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-text-muted">
                  {t("prototype.generateFromCode.selectedCount", {
                    selected: selectedCodeCandidateCount,
                    total: selectableCodeCandidateIds.length,
                  })}
                </span>
                {modifiedCodeCandidateBriefCount > 0 && (
                  <span
                    className="rounded-full border border-brand/40 bg-brand/10 px-2 py-0.5 text-[10px] uppercase text-brand"
                    title={t("prototype.generateFromCode.modifiedBriefCount", {
                      count: modifiedCodeCandidateBriefCount,
                    })}
                    aria-label={t("prototype.generateFromCode.modifiedBriefCount", {
                      count: modifiedCodeCandidateBriefCount,
                    })}
                  >
                    {t("prototype.generateFromCode.modifiedBriefCount", {
                      count: modifiedCodeCandidateBriefCount,
                    })}
                  </span>
                )}
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelectedCodeCandidateIds(selectableCodeCandidateIds)}
                  >
                    {t("prototype.generateFromCode.selectAll")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelectedCodeCandidateIds([])}
                  >
                    {t("prototype.generateFromCode.clearSelection")}
                  </Button>
                </div>
              </div>
              <Textarea
                rows={3}
                value={codeInstruction}
                onChange={(event) => setCodeInstruction(event.target.value)}
                placeholder={t("prototype.generateFromCode.instructionPlaceholder")}
              />
              <p className="text-[11px] text-text-muted/70">
                {t("prototype.generateFromCode.instructionHint")}
              </p>
              <label className="flex items-start gap-2 rounded-md border border-border-subtle bg-surface-raised/50 p-2 text-xs text-text-muted">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 rounded border-border-subtle bg-surface-input accent-brand"
                  checked={useRuntimeEvidence}
                  onChange={(event) => setUseRuntimeEvidence(event.target.checked)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-foreground">
                    {t("prototype.generateFromCode.runtimeToggle")}
                  </span>
                  <span>{t("prototype.generateFromCode.runtimeHint")}</span>
                </span>
              </label>
              {useRuntimeEvidence && (
                <Input
                  value={runtimeBaseUrl}
                  onChange={(event) => setRuntimeBaseUrl(event.target.value)}
                  placeholder={t("prototype.generateFromCode.runtimeBaseUrlPlaceholder")}
                />
              )}
            </div>
          )}
          <DialogFooter showCloseButton>
            <Button variant="secondary" onClick={() => setCodeScanOpen(false)}>
              {t("prototype.createCancel")}
            </Button>
            <Button
              onClick={startCodeGeneration}
              disabled={codeScanLoading || !codeCandidates || selectedCodeCandidateCount === 0}
            >
              {t("prototype.generateFromCode.startButton")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={codeProgressOpen}
        onOpenChange={(open) => codeGen.done && setCodeProgressOpen(open)}
      >
        <DialogContent className="sm:max-w-2xl" showCloseButton={codeGen.done}>
          <DialogHeader>
            <DialogTitle>{t("prototype.generateFromCode.dialogTitle")}</DialogTitle>
            <DialogDescription>
              {codeGen.total > 0
                ? t("prototype.generateFromCode.progressSummary", {
                    done:
                      codeGen.created +
                      codeGen.regenerated +
                      codeGen.skipped +
                      codeGen.failed +
                      codeGen.unsupported,
                    total: codeGen.total,
                  })
                : t("prototype.generateFromCode.scanLoading")}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-auto">
            {sortedCodeItems.length === 0 ? (
              <div className="flex items-center gap-2 py-6 text-sm text-text-muted">
                <Loader2 size={14} className="animate-spin" />
                {t("prototype.generateFromCode.status.pending")}
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-border-subtle">
                {sortedCodeItems.map((item) => (
                  <li
                    key={item.candidateId}
                    className="grid grid-cols-[auto_1fr] gap-3 py-2 text-sm"
                  >
                    <CodeStatusGlyph status={item.status} />
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium">{item.title || item.route}</span>
                        <span className="rounded-full border border-border-subtle px-2 py-0.5 text-[10px] uppercase text-text-muted">
                          {t(`prototype.generateFromCode.action.${item.action}`)}
                        </span>
                      </div>
                      <div className="font-mono text-xs text-text-muted">{item.route}</div>
                      <div className="truncate text-xs text-text-muted/80">
                        {codeStatusLabel(item, t)}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <DialogFooter showCloseButton={codeGen.done}>
            {codeGen.done && (
              <Button onClick={() => setCodeProgressOpen(false)}>{t("issue.close")}</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={progressOpen} onOpenChange={handleProgressOpenChange}>
        <DialogContent className="sm:max-w-lg" showCloseButton={regen.done}>
          <DialogHeader>
            <DialogTitle>{t("prototype.regenerateAll.dialogTitle")}</DialogTitle>
            <DialogDescription>
              {regen.total > 0 ? `${regen.okCount + regen.failedCount}/${regen.total}` : ""}
            </DialogDescription>
          </DialogHeader>
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
              <Button onClick={() => setProgressOpen(false)}>{t("issue.close")}</Button>
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

function SourceBadge({
  prototype,
  t,
}: {
  prototype: Prototype;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const isCode = prototype.source_kind === "code";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase",
        isCode
          ? "border-brand/40 bg-brand/10 text-brand"
          : "border-border-subtle bg-surface-raised text-text-muted",
      )}
    >
      {isCode ? t("prototype.source.code") : t("prototype.source.manual")}
    </span>
  );
}

function CodeStatusGlyph({ status }: { status: CodeItemStatus }) {
  if (status === "done" || status === "skipped") {
    return (
      <span className="mt-0.5 flex size-5 items-center justify-center rounded-full bg-status-success/15 text-status-success">
        <Check size={12} />
      </span>
    );
  }
  if (status === "failed" || status === "unsupported") {
    return (
      <span className="mt-0.5 flex size-5 items-center justify-center rounded-full bg-status-failed/15 text-status-failed">
        <X size={12} />
      </span>
    );
  }
  if (status === "generating" || status === "capturing") {
    return (
      <span className="mt-0.5 flex size-5 items-center justify-center text-brand">
        <Loader2 size={14} className="animate-spin" />
      </span>
    );
  }
  if (status === "capture_failed") {
    return (
      <span className="mt-0.5 flex size-5 items-center justify-center rounded-full border border-status-awaiting/40 text-status-awaiting">
        <span className="size-1.5 rounded-full bg-current" />
      </span>
    );
  }
  return (
    <span className="mt-0.5 flex size-5 items-center justify-center rounded-full border border-border-subtle text-text-muted/60">
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

function codeStatusLabel(
  item: CodeGenItem,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (item.status === "done") {
    return item.versionNo !== undefined
      ? t("prototype.generateFromCode.status.doneVersion", { version: item.versionNo })
      : t("prototype.generateFromCode.status.done");
  }
  if (item.status === "skipped") return t("prototype.generateFromCode.status.skipped");
  if (item.status === "failed") {
    return t("prototype.generateFromCode.status.failed", { message: item.message ?? "" });
  }
  if (item.status === "unsupported") {
    return t("prototype.generateFromCode.status.unsupported");
  }
  if (item.status === "capturing") return t("prototype.generateFromCode.status.capturing");
  if (item.status === "capture_failed") {
    return t("prototype.generateFromCode.status.captureFailed", {
      message: item.message ?? "",
    });
  }
  if (item.status === "generating") return t("prototype.generateFromCode.status.generating");
  return t("prototype.generateFromCode.status.pending");
}
