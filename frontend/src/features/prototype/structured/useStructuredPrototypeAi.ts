"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyPrototypeAiProposal,
  createPrototypeAiThread,
  getPrototypeAiThread,
  listPrototypeAiThreads,
  rejectPrototypeAiProposal,
  sendPrototypeAiMessage,
  StructuredPrototypeAiApiError,
} from "@/lib/api/prototypes";
import { useI18n } from "@/providers/I18nProvider";

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
  selectedNodeId: string | null;
  viewport: "desktop" | "tablet" | "mobile";
  onDraftApplied: (draft: StructuredPrototypeDraft) => Promise<void>;
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
  selectedNodeId,
  viewport,
  onDraftApplied,
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

  const initialize = useCallback(async () => {
    if (initializeRef.current) return initializeRef.current;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setLoading(true);
        setError(null);
      }
      try {
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
              title: "原型调整",
            }));
          window.localStorage.setItem(storageKey(projectId), thread.id);
          next = await getPrototypeAiThread(thread.id);
        }
        if (!mountedRef.current) return;
        setSnapshot(next);
        setLoading(false);
        setError(null);
      } catch (cause) {
        recordError("structured prototype AI recovery failed", cause);
        if (mountedRef.current) setLoading(false);
      }
    })().finally(() => {
      initializeRef.current = null;
    });
    initializeRef.current = inFlight;
    return inFlight;
  }, [draft.documentId, projectId, recordError]);

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
      try {
        await sendPrototypeAiMessage(thread.id, {
          contractVersion: 1,
          clientMessageId: crypto.randomUUID(),
          draftId: draft.draftId,
          expectedHeadSequenceNo: draft.headSequenceNo,
          expectedDocumentHash: draft.documentHash,
          content: trimmed,
          selection: {
            scope: selectedNodeId ? "selection" : "page",
            pageId,
            selectedNodeIds: selectedNodeId ? [selectedNodeId] : [],
            flowId: null,
            viewport,
          },
        });
        const next = await getPrototypeAiThread(thread.id);
        if (!mountedRef.current) return false;
        setSnapshot(next);
        setMutating(false);
        return true;
      } catch (cause) {
        recordError("structured prototype AI message failed", cause);
        if (mountedRef.current) setMutating(false);
        return false;
      }
    },
    [draft, mutating, pageId, recordError, selectedNodeId, snapshot, viewport],
  );

  const apply = useCallback(async (): Promise<boolean> => {
    const run = snapshot?.latestRun;
    if (!run?.canApply || mutating) return false;
    setMutating(true);
    setError(null);
    try {
      const applied = await applyPrototypeAiProposal(run.id, {
        contractVersion: 1,
        clientRequestId: crypto.randomUUID(),
        expectedHeadSequenceNo: draft.headSequenceNo,
        expectedDocumentHash: draft.documentHash,
      });
      await onDraftApplied(applied.draft);
      const next = await getPrototypeAiThread(run.threadId);
      if (!mountedRef.current) return false;
      setSnapshot(next);
      setMutating(false);
      return true;
    } catch (cause) {
      recordError("structured prototype AI apply failed", cause);
      if (mountedRef.current) setMutating(false);
      return false;
    }
  }, [draft, mutating, onDraftApplied, recordError, snapshot?.latestRun]);

  const reject = useCallback(async (): Promise<boolean> => {
    const run = snapshot?.latestRun;
    if (!run?.canReject || mutating) return false;
    setMutating(true);
    setError(null);
    try {
      await rejectPrototypeAiProposal(run.id, {
        contractVersion: 1,
        clientRequestId: crypto.randomUUID(),
      });
      const next = await getPrototypeAiThread(run.threadId);
      if (!mountedRef.current) return false;
      setSnapshot(next);
      setMutating(false);
      return true;
    } catch (cause) {
      recordError("structured prototype AI reject failed", cause);
      if (mountedRef.current) setMutating(false);
      return false;
    }
  }, [mutating, recordError, snapshot?.latestRun]);

  return { snapshot, loading, mutating, error, send, apply, reject, retry: initialize };
}
