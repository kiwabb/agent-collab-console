"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyPrototypeAiProposal,
  createPrototypeAiThread,
  getCurrentStructuredPrototypeDraft,
  getPrototypeAiThread,
  listPrototypeAiThreads,
  rejectPrototypeAiProposal,
  sendPrototypeAiMessage,
  StructuredPrototypeAiApiError,
} from "@/lib/api/prototypes";
import { useI18n } from "@/providers/I18nProvider";

import {
  reconcilePendingPrototypeAiOperation,
  type ReconciledPrototypeAiOperation,
} from "./structuredPrototypeAsyncRecovery";
import {
  beginStructuredPrototypePendingOperation,
  finishStructuredPrototypePendingOperation,
  isStructuredPrototypeAiPendingOperation,
  loadStructuredPrototypePendingOperation,
  readStructuredPrototypePendingLockState,
  structuredPrototypeAiApplyRequestKey,
  structuredPrototypeAiMessageRequestKey,
  structuredPrototypeAiRejectRequestKey,
  type StructuredPrototypePendingOperation,
} from "./structuredPrototypeStorage";
import type {
  PrototypeAiEditRun,
  PrototypeAiThreadSnapshot,
  StructuredPrototypeDraft,
} from "./types";

const ACTIVE_STATUSES = new Set<PrototypeAiEditRun["status"]>([
  "queued",
  "building_context",
  "generating",
  "validating",
  "rendering_preview",
]);
const MAX_POLL_ATTEMPTS = 80;
const POLL_INTERVAL_MS = 1_500;

interface Options {
  projectId: string;
  draft: StructuredPrototypeDraft;
  pageId: string;
  selectedNodeIds: readonly string[];
  viewport: "desktop" | "tablet" | "mobile";
  onApplyStart: () => number | null;
  onDraftApplied: (draft: StructuredPrototypeDraft, sessionId: number) => Promise<boolean>;
  onApplyEnd: (sessionId: number) => void;
}

interface StructuredPrototypeAiController {
  snapshot: PrototypeAiThreadSnapshot | null;
  loading: boolean;
  mutating: boolean;
  error: string | null;
  send: (content: string) => Promise<boolean>;
  apply: () => Promise<boolean>;
  reject: () => Promise<boolean>;
  retry: () => Promise<void>;
}

function storageKey(projectId: string): string {
  return `structured-prototype:${projectId}:ai-thread-id`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useStructuredPrototypeAi({
  projectId,
  draft,
  pageId,
  selectedNodeIds,
  viewport,
  onApplyStart,
  onDraftApplied,
  onApplyEnd,
}: Options): StructuredPrototypeAiController {
  const [snapshot, setSnapshot] = useState<PrototypeAiThreadSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const mountedRef = useRef(true);
  const initializeRef = useRef<Promise<void> | null>(null);
  const pollAttemptsRef = useRef<{ runId: string; count: number } | null>(null);

  const recordError = useCallback((context: string, cause: unknown) => {
    console.error(`${context}:`, cause);
    if (mountedRef.current) setError(errorMessage(cause));
  }, []);

  const reportAiFailure = useCallback(
    (context: string, cause: unknown): false => {
      const pending = readStructuredPrototypePendingLockState(
        projectId,
        isStructuredPrototypeAiPendingOperation,
      );
      const reported = pending.storageError ?? cause;
      recordError(context, reported);
      if (mountedRef.current) {
        setLoading(false);
        setMutating(pending.locked);
      }
      return false;
    },
    [projectId, recordError],
  );

  const initialize = useCallback(async () => {
    if (initializeRef.current) return initializeRef.current;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setLoading(true);
        setError(null);
      }
      try {
        const pending = loadStructuredPrototypePendingOperation(projectId);
        if (pending !== null && isStructuredPrototypeAiPendingOperation(pending)) {
          if (mountedRef.current) setMutating(true);
          const reconciled = await reconcilePendingPrototypeAiOperation(pending);
          if (reconciled.kind === "apply") {
            const sessionId = onApplyStart();
            if (sessionId === null) {
              throw new Error("AI apply recovery could not acquire the editor mutation lock");
            }
            try {
              if (!(await onDraftApplied(reconciled.draft, sessionId))) {
                throw new Error("AI applied draft runtime recovery failed");
              }
            } finally {
              onApplyEnd(sessionId);
            }
          }
          if (!mountedRef.current) return;
          setSnapshot(reconciled.snapshot);
          setMutating(false);
          setLoading(false);
          setError(null);
          return;
        }
        const storedThreadId = window.localStorage.getItem(storageKey(projectId));
        let next: PrototypeAiThreadSnapshot | null = null;
        if (storedThreadId) {
          try {
            const recovered = await getPrototypeAiThread(storedThreadId);
            if (recovered.thread.documentId === draft.documentId) next = recovered;
          } catch (cause) {
            if (!(cause instanceof StructuredPrototypeAiApiError) || cause.status !== 404) {
              throw cause;
            }
            window.localStorage.removeItem(storageKey(projectId));
          }
        }
        if (!next) {
          const threads = await listPrototypeAiThreads(draft.documentId);
          const active = threads.find((thread) => thread.status === "active");
          const thread =
            active ??
            (await createPrototypeAiThread(draft.documentId, {
              contractVersion: 1,
              clientRequestId: crypto.randomUUID(),
              title: t("prototype.structured.ai.threadTitle"),
            }));
          window.localStorage.setItem(storageKey(projectId), thread.id);
          next = await getPrototypeAiThread(thread.id);
        }
        if (!mountedRef.current) return;
        setSnapshot(next);
        setLoading(false);
        setError(null);
      } catch (cause) {
        reportAiFailure("structured prototype AI recovery failed", cause);
      }
    })().finally(() => {
      initializeRef.current = null;
    });
    initializeRef.current = inFlight;
    return inFlight;
  }, [draft.documentId, onApplyEnd, onApplyStart, onDraftApplied, projectId, reportAiFailure, t]);

  useEffect(() => {
    mountedRef.current = true;
    void initialize();
    return () => {
      mountedRef.current = false;
    };
  }, [initialize]);

  useEffect(() => {
    const run = snapshot?.latestRun;
    if (!run || !ACTIVE_STATUSES.has(run.status)) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    if (pollAttemptsRef.current?.runId !== run.id) {
      pollAttemptsRef.current = { runId: run.id, count: 0 };
    }

    const poll = async () => {
      const attempts = pollAttemptsRef.current;
      if (!attempts || attempts.runId !== run.id) return;
      attempts.count += 1;
      try {
        const next = await getPrototypeAiThread(run.threadId);
        if (cancelled) return;
        setSnapshot(next);
        setError(null);
        if (next.latestRun && ACTIVE_STATUSES.has(next.latestRun.status)) {
          if (attempts.count >= MAX_POLL_ATTEMPTS) {
            setError(t("prototype.structured.ai.pollExhausted"));
            return;
          }
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        recordError("structured prototype AI polling failed", cause);
        if (attempts.count < MAX_POLL_ATTEMPTS) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      }
    };

    timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [recordError, snapshot?.latestRun, t]);

  const send = useCallback(
    async (content: string): Promise<boolean> => {
      const thread = snapshot?.thread;
      const active = snapshot?.latestRun;
      const trimmed = content.trim();
      if (!thread || !trimmed || mutating || (active && ACTIVE_STATUSES.has(active.status))) {
        return false;
      }
      setMutating(true);
      setError(null);
      const requestKey = structuredPrototypeAiMessageRequestKey(
        thread.id,
        draft.draftId,
        draft.headSequenceNo,
        draft.documentHash,
      );
      let descriptor: StructuredPrototypePendingOperation;
      try {
        descriptor = beginStructuredPrototypePendingOperation(projectId, {
          operationKind: "ai_edit",
          resourceKind: "ai_thread",
          resourceId: thread.id,
          requestKey,
        });
      } catch (cause) {
        return reportAiFailure("structured prototype AI message persistence failed", cause);
      }
      let next: PrototypeAiThreadSnapshot;
      try {
        const run = await sendPrototypeAiMessage(thread.id, {
          contractVersion: 1,
          clientMessageId: descriptor.clientRequestId,
          draftId: draft.draftId,
          expectedHeadSequenceNo: draft.headSequenceNo,
          expectedDocumentHash: draft.documentHash,
          content: trimmed,
          selection: {
            scope: selectedNodeIds.length > 0 ? "selection" : "page",
            pageId,
            selectedNodeIds: [...selectedNodeIds],
            flowId: null,
            viewport,
          },
        });
        next = await getPrototypeAiThread(thread.id);
        if (next.latestRun?.id !== run.id) {
          throw new Error("AI thread did not expose the submitted edit run");
        }
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
      } catch (cause) {
        let reconciled: ReconciledPrototypeAiOperation;
        try {
          reconciled = await reconcilePendingPrototypeAiOperation(descriptor);
        } catch (recoveryError) {
          return reportAiFailure("structured prototype AI message recovery failed", recoveryError);
        }
        if (reconciled.kind !== "message") {
          return reportAiFailure(
            "structured prototype AI message recovery failed",
            new Error("AI message recovered an incompatible operation"),
          );
        }
        next = reconciled.snapshot;
      }
      if (!mountedRef.current) return false;
      setSnapshot(next);
      setMutating(false);
      return true;
    },
    [draft, mutating, pageId, projectId, reportAiFailure, selectedNodeIds, snapshot, viewport],
  );

  const apply = useCallback(async (): Promise<boolean> => {
    const run = snapshot?.latestRun;
    if (!run?.canApply || mutating) return false;
    const sessionId = onApplyStart();
    if (sessionId === null) return false;
    setMutating(true);
    setError(null);
    const requestKey = structuredPrototypeAiApplyRequestKey(
      run.id,
      draft.draftId,
      draft.headSequenceNo,
      draft.documentHash,
    );
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "apply_command_batch",
        resourceKind: "draft",
        resourceId: draft.draftId,
        contextId: run.id,
        requestKey,
      });
    } catch (cause) {
      onApplyEnd(sessionId);
      return reportAiFailure("structured prototype AI apply persistence failed", cause);
    }
    let appliedDraft: StructuredPrototypeDraft;
    let next: PrototypeAiThreadSnapshot;
    try {
      const applied = await applyPrototypeAiProposal(run.id, {
        contractVersion: 1,
        clientRequestId: descriptor.clientRequestId,
        expectedHeadSequenceNo: draft.headSequenceNo,
        expectedDocumentHash: draft.documentHash,
      });
      const currentDraft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
      if (currentDraft === null || currentDraft.draftId !== applied.draft.draftId) {
        throw new Error("AI applied draft does not match the project current draft");
      }
      appliedDraft = currentDraft;
      next = await getPrototypeAiThread(run.threadId);
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (cause) {
      let reconciled: ReconciledPrototypeAiOperation;
      try {
        reconciled = await reconcilePendingPrototypeAiOperation(descriptor);
      } catch (recoveryError) {
        onApplyEnd(sessionId);
        return reportAiFailure("structured prototype AI apply recovery failed", recoveryError);
      }
      if (reconciled.kind !== "apply") {
        onApplyEnd(sessionId);
        return reportAiFailure(
          "structured prototype AI apply recovery failed",
          new Error("AI apply recovered an incompatible operation"),
        );
      }
      appliedDraft = reconciled.draft;
      next = reconciled.snapshot;
    }
    let adopted: boolean;
    try {
      adopted = await onDraftApplied(appliedDraft, sessionId);
    } catch (cause) {
      return reportAiFailure("structured prototype AI apply runtime recovery failed", cause);
    } finally {
      onApplyEnd(sessionId);
    }
    if (!adopted) {
      return reportAiFailure(
        "structured prototype AI apply runtime recovery failed",
        new Error("AI applied draft runtime recovery failed"),
      );
    }
    if (!mountedRef.current) return false;
    setSnapshot(next);
    setMutating(false);
    return true;
  }, [
    draft,
    mutating,
    onApplyEnd,
    onApplyStart,
    onDraftApplied,
    projectId,
    reportAiFailure,
    snapshot?.latestRun,
  ]);

  const reject = useCallback(async (): Promise<boolean> => {
    const run = snapshot?.latestRun;
    if (!run?.canReject || mutating) return false;
    setMutating(true);
    setError(null);
    const requestKey = structuredPrototypeAiRejectRequestKey(run.id);
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "reject_ai_proposal",
        resourceKind: "ai_edit_run",
        resourceId: run.id,
        requestKey,
      });
    } catch (cause) {
      return reportAiFailure("structured prototype AI reject persistence failed", cause);
    }
    let next: PrototypeAiThreadSnapshot;
    try {
      const rejected = await rejectPrototypeAiProposal(run.id, {
        contractVersion: 1,
        clientRequestId: descriptor.clientRequestId,
      });
      if (rejected.status !== "rejected") throw new Error("AI edit run is not rejected");
      next = await getPrototypeAiThread(run.threadId);
      if (next.latestRun?.id !== run.id || next.latestRun.status !== "rejected") {
        throw new Error("AI thread does not expose the rejected edit run");
      }
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (cause) {
      let reconciled: ReconciledPrototypeAiOperation;
      try {
        reconciled = await reconcilePendingPrototypeAiOperation(descriptor);
      } catch (recoveryError) {
        return reportAiFailure("structured prototype AI reject recovery failed", recoveryError);
      }
      if (reconciled.kind !== "reject") {
        return reportAiFailure(
          "structured prototype AI reject recovery failed",
          new Error("AI reject recovered an incompatible operation"),
        );
      }
      next = reconciled.snapshot;
    }
    if (!mountedRef.current) return false;
    setSnapshot(next);
    setMutating(false);
    return true;
  }, [mutating, projectId, reportAiFailure, snapshot?.latestRun]);

  return { snapshot, loading, mutating, error, send, apply, reject, retry: initialize };
}
