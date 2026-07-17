"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  acceptStructuredPrototypeGenerationCandidate,
  confirmStructuredPrototypeGenerationBlueprint,
  createStructuredPrototypeGenerationJob,
  deleteProjectStructuredPrototype,
  getCurrentStructuredPrototypeDraft,
  getCurrentStructuredPrototypeGenerationJob,
  getStructuredPrototypeGenerationJob,
} from "@/lib/api/prototypes";
import { useI18n } from "@/providers/I18nProvider";

import {
  isStructuredPrototypeGenerationActive,
  nextStructuredPrototypeGenerationPollFailureCount,
  structuredPrototypeGenerationBrief,
} from "./structuredPrototypeGenerationState";
import {
  reconcilePendingPrototypeGenerationOperation,
  type ReconciledPrototypeGenerationOperation,
} from "./structuredPrototypeAsyncRecovery";
import {
  beginStructuredPrototypePendingOperation,
  clearStructuredPrototypeProjectStorage,
  finishStructuredPrototypePendingOperation,
  isStructuredPrototypeGenerationPendingOperation,
  loadStructuredPrototypePendingOperation,
  readStructuredPrototypePendingLockState,
  STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY,
  STRUCTURED_PROTOTYPE_GENERATION_START_REQUEST_KEY,
  structuredPrototypeGenerationAcceptRequestKey,
  structuredPrototypeGenerationConfirmRequestKey,
  type StructuredPrototypePendingOperation,
} from "./structuredPrototypeStorage";
import type { StructuredPrototypeDraft, StructuredPrototypeGenerationJob } from "./types";

const POLL_INTERVAL_MS = 2_000;
const MAX_CONSECUTIVE_POLL_FAILURES = 300;

interface Options {
  projectId: string;
  onAccepted: (draft: StructuredPrototypeDraft) => Promise<boolean>;
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
  deleteAll: () => Promise<boolean>;
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
  const pollFailuresRef = useRef<{ jobId: string; failures: number } | null>(null);

  const recordError = useCallback((context: string, cause: unknown) => {
    console.error(`${context}:`, cause);
    if (mountedRef.current) setError(errorMessage(cause));
  }, []);

  const reportGenerationFailure = useCallback(
    (context: string, cause: unknown): false => {
      const pending = readStructuredPrototypePendingLockState(
        projectId,
        isStructuredPrototypeGenerationPendingOperation,
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

  const retry = useCallback(async () => {
    if (refreshRef.current) return refreshRef.current;
    pollFailuresRef.current = null;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setLoading(true);
        setError(null);
      }
      try {
        const pending = loadStructuredPrototypePendingOperation(projectId);
        if (pending !== null && isStructuredPrototypeGenerationPendingOperation(pending)) {
          if (mountedRef.current) setMutating(true);
          const reconciled = await reconcilePendingPrototypeGenerationOperation(pending);
          switch (reconciled.kind) {
            case "start":
            case "confirm":
              if (mountedRef.current) setJob(reconciled.job);
              break;
            case "accept":
              if (!(await onAccepted(reconciled.draft))) {
                throw new Error("accepted generation runtime recovery failed");
              }
              if (mountedRef.current) setJob(reconciled.job);
              break;
            case "delete":
              clearStructuredPrototypeProjectStorage(projectId);
              pollFailuresRef.current = null;
              if (mountedRef.current) setJob(null);
              break;
          }
          if (!mountedRef.current) return;
          setMutating(false);
          setLoading(false);
          setError(null);
          return;
        }
        const current = await getCurrentStructuredPrototypeGenerationJob(projectId);
        if (!mountedRef.current) return;
        setJob(current);
        setLoading(false);
      } catch (cause) {
        reportGenerationFailure("structured prototype generation recovery failed", cause);
      }
    })().finally(() => {
      refreshRef.current = null;
    });
    refreshRef.current = inFlight;
    return inFlight;
  }, [onAccepted, projectId, reportGenerationFailure]);

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
    if (pollFailuresRef.current?.jobId !== job.id) {
      pollFailuresRef.current = { jobId: job.id, failures: 0 };
    }
    const poll = async () => {
      const pollState = pollFailuresRef.current;
      if (!pollState || pollState.jobId !== job.id) return;
      try {
        const next = await getStructuredPrototypeGenerationJob(job.id);
        if (cancelled) return;
        pollState.failures = nextStructuredPrototypeGenerationPollFailureCount(
          pollState.failures,
          "success",
        );
        setJob(next);
        setError(null);
        if (isStructuredPrototypeGenerationActive(next.status)) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        pollState.failures = nextStructuredPrototypeGenerationPollFailureCount(
          pollState.failures,
          "failure",
        );
        recordError("structured prototype generation polling failed", cause);
        if (pollState.failures < MAX_CONSECUTIVE_POLL_FAILURES) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        } else {
          setError(t("prototype.structured.generation.pollExhausted"));
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
      let descriptor: StructuredPrototypePendingOperation;
      try {
        descriptor = beginStructuredPrototypePendingOperation(projectId, {
          operationKind: "generation_job",
          resourceKind: "project",
          resourceId: projectId,
          requestKey: STRUCTURED_PROTOTYPE_GENERATION_START_REQUEST_KEY,
        });
      } catch (cause) {
        return reportGenerationFailure(
          "structured prototype generation start persistence failed",
          cause,
        );
      }
      let created: StructuredPrototypeGenerationJob;
      try {
        const response = await createStructuredPrototypeGenerationJob(projectId, {
          contractVersion: 1,
          clientRequestId: descriptor.clientRequestId,
          mode: "requirements",
          brief: structuredPrototypeGenerationBrief(brief),
        });
        const current = await getCurrentStructuredPrototypeGenerationJob(projectId);
        if (current === null || current.id !== response.id) {
          throw new Error("created generation job is not the project current job");
        }
        finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
        created = current;
      } catch (cause) {
        let reconciled: ReconciledPrototypeGenerationOperation;
        try {
          reconciled = await reconcilePendingPrototypeGenerationOperation(descriptor);
        } catch (recoveryError) {
          return reportGenerationFailure(
            "structured prototype generation start recovery failed",
            recoveryError,
          );
        }
        if (reconciled.kind !== "start") {
          return reportGenerationFailure(
            "structured prototype generation start recovery failed",
            new Error("generation start recovered an incompatible operation"),
          );
        }
        created = reconciled.job;
      }
      if (!mountedRef.current) return false;
      setJob(created);
      setMutating(false);
      return true;
    },
    [mutating, projectId, reportGenerationFailure],
  );

  const confirm = useCallback(async (): Promise<boolean> => {
    if (!job?.canConfirm || !job.blueprintHash || mutating) return false;
    const requestKey = structuredPrototypeGenerationConfirmRequestKey(
      job.id,
      job.blueprintVersion,
      job.blueprintHash,
    );
    setMutating(true);
    setError(null);
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "generation_job",
        resourceKind: "generation_job",
        resourceId: job.id,
        requestKey,
      });
    } catch (cause) {
      return reportGenerationFailure(
        "structured prototype blueprint confirmation persistence failed",
        cause,
      );
    }
    let confirmed: StructuredPrototypeGenerationJob;
    try {
      await confirmStructuredPrototypeGenerationBlueprint(job.id, {
        contractVersion: 1,
        clientRequestId: descriptor.clientRequestId,
        expectedBlueprintVersion: job.blueprintVersion,
        expectedBlueprintHash: job.blueprintHash,
      });
      confirmed = await getStructuredPrototypeGenerationJob(job.id);
      if (confirmed.status === "awaiting_confirmation" || confirmed.canConfirm) {
        throw new Error("generation blueprint confirmation is not reflected in the job");
      }
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (cause) {
      let reconciled: ReconciledPrototypeGenerationOperation;
      try {
        reconciled = await reconcilePendingPrototypeGenerationOperation(descriptor);
      } catch (recoveryError) {
        return reportGenerationFailure(
          "structured prototype blueprint confirmation recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "confirm") {
        return reportGenerationFailure(
          "structured prototype blueprint confirmation recovery failed",
          new Error("generation confirmation recovered an incompatible operation"),
        );
      }
      confirmed = reconciled.job;
    }
    if (!mountedRef.current) return false;
    setJob(confirmed);
    setMutating(false);
    return true;
  }, [job, mutating, projectId, reportGenerationFailure]);

  const enterAccepted = useCallback(async (): Promise<boolean> => {
    if (mutating) return false;
    setMutating(true);
    setError(null);
    try {
      const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
      if (!draft) throw new Error("accepted generation has no current project draft");
      if (!(await onAccepted(draft))) {
        throw new Error("accepted generation runtime recovery failed");
      }
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
    if (
      !job?.canAccept ||
      !job.candidateObjectHash ||
      !job.previewOutputHash ||
      !job.sourceFingerprint ||
      mutating
    ) {
      return false;
    }
    const requestKey = structuredPrototypeGenerationAcceptRequestKey(
      job.id,
      job.candidateObjectHash,
      job.previewOutputHash,
      job.sourceFingerprint,
    );
    setMutating(true);
    setError(null);
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "create_document",
        resourceKind: "generation_job",
        resourceId: job.id,
        requestKey,
      });
    } catch (cause) {
      return reportGenerationFailure(
        "structured prototype generation acceptance persistence failed",
        cause,
      );
    }
    let acceptedJob: StructuredPrototypeGenerationJob;
    let draft: StructuredPrototypeDraft;
    try {
      const accepted = await acceptStructuredPrototypeGenerationCandidate(job.id, {
        contractVersion: 1,
        clientRequestId: descriptor.clientRequestId,
        expectedCandidateObjectHash: job.candidateObjectHash,
        expectedPreviewOutputHash: job.previewOutputHash,
        expectedSourceFingerprint: job.sourceFingerprint,
      });
      const [currentDraft, currentJob] = await Promise.all([
        getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID()),
        getStructuredPrototypeGenerationJob(job.id),
      ]);
      if (
        !currentDraft ||
        currentDraft.draftId !== accepted.draftId ||
        currentJob.status !== "accepted" ||
        currentJob.documentId !== currentDraft.documentId
      ) {
        throw new Error("accepted generation draft does not match the project current draft");
      }
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
      acceptedJob = currentJob;
      draft = currentDraft;
    } catch (cause) {
      let reconciled: ReconciledPrototypeGenerationOperation;
      try {
        reconciled = await reconcilePendingPrototypeGenerationOperation(descriptor);
      } catch (recoveryError) {
        return reportGenerationFailure(
          "structured prototype generation acceptance recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "accept") {
        return reportGenerationFailure(
          "structured prototype generation acceptance recovery failed",
          new Error("generation acceptance recovered an incompatible operation"),
        );
      }
      acceptedJob = reconciled.job;
      draft = reconciled.draft;
    }
    try {
      if (!(await onAccepted(draft))) {
        throw new Error("accepted generation runtime recovery failed");
      }
    } catch (cause) {
      return reportGenerationFailure(
        "structured prototype generation accepted draft recovery failed",
        cause,
      );
    }
    if (!mountedRef.current) return false;
    setJob(acceptedJob);
    setMutating(false);
    return true;
  }, [job, mutating, onAccepted, projectId, reportGenerationFailure]);

  const deleteAll = useCallback(async (): Promise<boolean> => {
    if (mutating || (job && isStructuredPrototypeGenerationActive(job.status))) return false;
    setMutating(true);
    setError(null);
    let descriptor: StructuredPrototypePendingOperation;
    try {
      descriptor = beginStructuredPrototypePendingOperation(projectId, {
        operationKind: "delete_project_prototype",
        resourceKind: "project_prototype",
        resourceId: projectId,
        contextId: "generation",
        requestKey: STRUCTURED_PROTOTYPE_DELETE_REQUEST_KEY,
      });
    } catch (cause) {
      return reportGenerationFailure("structured prototype deletion persistence failed", cause);
    }
    try {
      await deleteProjectStructuredPrototype(projectId, descriptor.clientRequestId);
      const [draft, currentJob] = await Promise.all([
        getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID()),
        getCurrentStructuredPrototypeGenerationJob(projectId),
      ]);
      if (draft !== null || currentJob !== null) {
        throw new Error("deleted prototype still has a current draft or generation job");
      }
      finishStructuredPrototypePendingOperation(projectId, descriptor.clientRequestId);
    } catch (cause) {
      let reconciled: ReconciledPrototypeGenerationOperation;
      try {
        reconciled = await reconcilePendingPrototypeGenerationOperation(descriptor);
      } catch (recoveryError) {
        return reportGenerationFailure(
          "structured prototype deletion recovery failed",
          recoveryError,
        );
      }
      if (reconciled.kind !== "delete") {
        return reportGenerationFailure(
          "structured prototype deletion recovery failed",
          new Error("generation deletion recovered an incompatible operation"),
        );
      }
    }
    clearStructuredPrototypeProjectStorage(projectId);
    if (!mountedRef.current) return false;
    pollFailuresRef.current = null;
    setJob(null);
    setMutating(false);
    return true;
  }, [job, mutating, projectId, reportGenerationFailure]);

  return {
    job,
    loading,
    mutating,
    error,
    start,
    confirm,
    accept,
    enterAccepted,
    deleteAll,
    retry,
  };
}
