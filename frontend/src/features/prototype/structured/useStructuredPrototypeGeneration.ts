"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  acceptStructuredPrototypeGenerationCandidate,
  confirmStructuredPrototypeGenerationBlueprint,
  createStructuredPrototypeGenerationJob,
  getCurrentStructuredPrototypeDraft,
  getCurrentStructuredPrototypeGenerationJob,
  getStructuredPrototypeGenerationJob,
} from "@/lib/api/prototypes";
import { useI18n } from "@/providers/I18nProvider";

import {
  isStructuredPrototypeGenerationActive,
  structuredPrototypeGenerationBrief,
} from "./structuredPrototypeGenerationState";
import type { StructuredPrototypeDraft, StructuredPrototypeGenerationJob } from "./types";

const POLL_INTERVAL_MS = 2_000;
const MAX_POLL_ATTEMPTS = 300;

interface Options {
  projectId: string;
  onAccepted: (draft: StructuredPrototypeDraft) => Promise<void>;
}

interface StructuredPrototypeGenerationController {
  job: StructuredPrototypeGenerationJob | null;
  loading: boolean;
  mutating: boolean;
  error: string | null;
  start: (brief: string) => Promise<boolean>;
  confirm: () => Promise<boolean>;
  accept: () => Promise<boolean>;
  enterAccepted: () => Promise<boolean>;
  retry: () => Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useStructuredPrototypeGeneration({
  projectId,
  onAccepted,
}: Options): StructuredPrototypeGenerationController {
  const [job, setJob] = useState<StructuredPrototypeGenerationJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const mountedRef = useRef(true);
  const refreshRef = useRef<Promise<void> | null>(null);
  const pollAttemptsRef = useRef<{ jobId: string; count: number } | null>(null);

  const recordError = useCallback((context: string, cause: unknown) => {
    console.error(`${context}:`, cause);
    if (mountedRef.current) setError(errorMessage(cause));
  }, []);

  const retry = useCallback(async () => {
    if (refreshRef.current) return refreshRef.current;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setLoading(true);
        setError(null);
      }
      try {
        const current = await getCurrentStructuredPrototypeGenerationJob(projectId);
        if (!mountedRef.current) return;
        setJob(current);
        setLoading(false);
      } catch (cause) {
        recordError("structured prototype generation recovery failed", cause);
        if (mountedRef.current) setLoading(false);
      }
    })().finally(() => {
      refreshRef.current = null;
    });
    refreshRef.current = inFlight;
    return inFlight;
  }, [projectId, recordError]);

  useEffect(() => {
    mountedRef.current = true;
    void retry();
    return () => {
      mountedRef.current = false;
    };
  }, [retry]);

  useEffect(() => {
    if (!job || !isStructuredPrototypeGenerationActive(job.status)) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    if (pollAttemptsRef.current?.jobId !== job.id) {
      pollAttemptsRef.current = { jobId: job.id, count: 0 };
    }
    const poll = async () => {
      const attempts = pollAttemptsRef.current;
      if (!attempts || attempts.jobId !== job.id) return;
      attempts.count += 1;
      try {
        const next = await getStructuredPrototypeGenerationJob(job.id);
        if (cancelled) return;
        setJob(next);
        setError(null);
        if (isStructuredPrototypeGenerationActive(next.status)) {
          if (attempts.count >= MAX_POLL_ATTEMPTS) {
            setError(t("prototype.structured.generation.pollExhausted"));
            return;
          }
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        recordError("structured prototype generation polling failed", cause);
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
  }, [job, recordError, t]);

  const start = useCallback(
    async (brief: string): Promise<boolean> => {
      if (mutating) return false;
      setMutating(true);
      setError(null);
      try {
        const created = await createStructuredPrototypeGenerationJob(projectId, {
          contractVersion: 1,
          clientRequestId: crypto.randomUUID(),
          mode: "requirements",
          brief: structuredPrototypeGenerationBrief(brief),
        });
        if (!mountedRef.current) return false;
        setJob(created);
        setMutating(false);
        return true;
      } catch (cause) {
        recordError("structured prototype generation start failed", cause);
        if (mountedRef.current) setMutating(false);
        return false;
      }
    },
    [mutating, projectId, recordError],
  );

  const confirm = useCallback(async (): Promise<boolean> => {
    if (!job?.canConfirm || !job.blueprintHash || mutating) return false;
    setMutating(true);
    setError(null);
    try {
      const confirmed = await confirmStructuredPrototypeGenerationBlueprint(job.id, {
        contractVersion: 1,
        clientRequestId: crypto.randomUUID(),
        expectedBlueprintHash: job.blueprintHash,
      });
      if (!mountedRef.current) return false;
      setJob(confirmed);
      setMutating(false);
      return true;
    } catch (cause) {
      recordError("structured prototype blueprint confirmation failed", cause);
      if (mountedRef.current) setMutating(false);
      return false;
    }
  }, [job, mutating, recordError]);

  const enterAccepted = useCallback(async (): Promise<boolean> => {
    if (mutating) return false;
    setMutating(true);
    setError(null);
    try {
      const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
      if (!draft) throw new Error("accepted generation has no current project draft");
      await onAccepted(draft);
      if (!mountedRef.current) return false;
      setMutating(false);
      return true;
    } catch (cause) {
      recordError("structured prototype accepted draft recovery failed", cause);
      if (mountedRef.current) setMutating(false);
      return false;
    }
  }, [mutating, onAccepted, projectId, recordError]);

  const accept = useCallback(async (): Promise<boolean> => {
    if (!job?.canAccept || !job.candidateObjectHash || !job.previewOutputHash || mutating) {
      return false;
    }
    setMutating(true);
    setError(null);
    try {
      const accepted = await acceptStructuredPrototypeGenerationCandidate(job.id, {
        contractVersion: 1,
        clientRequestId: crypto.randomUUID(),
        expectedCandidateObjectHash: job.candidateObjectHash,
        expectedPreviewOutputHash: job.previewOutputHash,
      });
      const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
      if (!draft || draft.draftId !== accepted.draftId) {
        throw new Error("accepted generation draft does not match the project current draft");
      }
      await onAccepted(draft);
      if (!mountedRef.current) return false;
      setJob(accepted.job);
      setMutating(false);
      return true;
    } catch (cause) {
      recordError("structured prototype generation acceptance failed", cause);
      if (mountedRef.current) setMutating(false);
      return false;
    }
  }, [job, mutating, onAccepted, projectId, recordError]);

  return { job, loading, mutating, error, start, confirm, accept, enterAccepted, retry };
}
