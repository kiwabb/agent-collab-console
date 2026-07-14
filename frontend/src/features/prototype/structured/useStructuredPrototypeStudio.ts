"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyStructuredPrototypeCommands,
  applyStructuredPrototypeRuntimeEvents,
  checkpointStructuredPrototypeRuntimeSession,
  createStructuredPrototypeRuntimeSession,
  getCurrentStructuredPrototypeDraft,
  getStructuredPrototypePublication,
  publishStructuredPrototypeDraft,
  recoverStructuredPrototypeRuntimeSession,
  StructuredPrototypeApiError,
} from "@/lib/api/prototypes";

import {
  parsePrototypeRuntimeStateJson,
  parseRuntimeViewModelJson,
  RuntimeStateCodecError,
} from "../runtime/runtimeStateCodec";
import type { PrototypeRuntimeState, RuntimeEvent, RuntimeViewModel } from "../runtime/types";
import { deriveProcurementRuntimeBindings } from "./structuredPrototypeDerived";
import type {
  StructuredPrototypeCommandBatch,
  StructuredPrototypeDraft,
  StructuredPrototypePublication,
  StructuredPrototypeRuntimeSession,
} from "./types";

interface RuntimeSnapshot {
  session: StructuredPrototypeRuntimeSession;
  state: PrototypeRuntimeState;
  viewModel: RuntimeViewModel;
}

interface StudioState {
  draft: StructuredPrototypeDraft | null;
  runtime: RuntimeSnapshot | null;
  publication: StructuredPrototypePublication | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
}

interface StructuredPrototypeStudioController extends StudioState {
  applyCommands: (batch: StructuredPrototypeCommandBatch) => Promise<boolean>;
  sendRuntimeEvents: (events: RuntimeEvent[]) => Promise<boolean>;
  checkpointRuntime: () => Promise<boolean>;
  publish: () => Promise<boolean>;
  adoptAiDraft: (draft: StructuredPrototypeDraft) => Promise<void>;
  retry: () => Promise<void>;
}

function storageKey(projectId: string, suffix: string): string {
  return `structured-prototype:${projectId}:${suffix}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function decodeRuntime(session: StructuredPrototypeRuntimeSession): RuntimeSnapshot {
  const state = parsePrototypeRuntimeStateJson(session.stateJson);
  const viewModel = parseRuntimeViewModelJson(session.viewModelJson);
  if (
    state.sessionId !== session.sessionId ||
    state.sequenceNo !== session.headSequenceNo ||
    state.runtimeCoreVersion !== session.runtimeCoreVersion ||
    state.stateMachineKernelVersion !== session.stateMachineKernelVersion
  ) {
    throw new RuntimeStateCodecError("runtime response metadata does not match its state JSON");
  }
  return { session, state, viewModel };
}

function requestIdentity(projectId: string, key: string): string {
  const name = storageKey(projectId, key);
  const current = window.localStorage.getItem(name);
  if (current) return current;
  const created = crypto.randomUUID();
  window.localStorage.setItem(name, created);
  return created;
}

function finishRequestIdentity(projectId: string, key: string): void {
  window.localStorage.removeItem(storageKey(projectId, key));
}

export function useStructuredPrototypeStudio(
  projectId: string,
): StructuredPrototypeStudioController {
  const [studio, setStudio] = useState<StudioState>({
    draft: null,
    runtime: null,
    publication: null,
    loading: true,
    saving: false,
    error: null,
  });
  const mountedRef = useRef(true);
  const bootstrapInFlightRef = useRef<Promise<void> | null>(null);

  const updateError = useCallback((context: string, error: unknown) => {
    console.error(`${context}:`, error);
    if (!mountedRef.current) return;
    setStudio((current) => ({ ...current, error: errorMessage(error) }));
  }, []);

  const createRuntime = useCallback(
    async (draft: StructuredPrototypeDraft): Promise<RuntimeSnapshot> => {
      const bindings = deriveProcurementRuntimeBindings(draft.document);
      if (!bindings) {
        throw new Error("structured prototype does not satisfy the procurement runtime contract");
      }
      const requestKey = `runtime-create-request:${draft.draftId}`;
      const clientRequestId = requestIdentity(projectId, requestKey);
      const session = await createStructuredPrototypeRuntimeSession(draft.draftId, {
        contractVersion: 1,
        clientRequestId,
        scenarioId: bindings.scenarioId,
        recordingKind: "studio_preview",
        actorSubjectId: null,
      });
      const decoded = decodeRuntime(session);
      window.localStorage.setItem(storageKey(projectId, "runtime-session-id"), session.sessionId);
      finishRequestIdentity(projectId, requestKey);
      return decoded;
    },
    [projectId],
  );

  const load = useCallback(async () => {
    if (bootstrapInFlightRef.current) return bootstrapInFlightRef.current;
    const inFlight = (async () => {
      if (mountedRef.current) {
        setStudio((current) => ({ ...current, loading: true, error: null }));
      }
      try {
        const draft = await getCurrentStructuredPrototypeDraft(projectId, crypto.randomUUID());
        if (!draft) {
          if (!mountedRef.current) return;
          setStudio({
            draft: null,
            runtime: null,
            publication: null,
            loading: false,
            saving: false,
            error: null,
          });
          return;
        }

        const storedSessionId = window.localStorage.getItem(
          storageKey(projectId, "runtime-session-id"),
        );
        let runtime: RuntimeSnapshot;
        if (storedSessionId) {
          try {
            const recovered = await recoverStructuredPrototypeRuntimeSession(
              storedSessionId,
              crypto.randomUUID(),
            );
            if (recovered.documentId !== draft.documentId || recovered.sourceId !== draft.draftId) {
              window.localStorage.removeItem(storageKey(projectId, "runtime-session-id"));
              runtime = await createRuntime(draft);
            } else {
              runtime = decodeRuntime(recovered);
            }
          } catch (error) {
            if (!(error instanceof StructuredPrototypeApiError) || error.status !== 404)
              throw error;
            window.localStorage.removeItem(storageKey(projectId, "runtime-session-id"));
            runtime = await createRuntime(draft);
          }
        } else {
          runtime = await createRuntime(draft);
        }
        const publication = await getStructuredPrototypePublication(draft.documentId);
        if (!mountedRef.current) return;
        setStudio({
          draft,
          runtime,
          publication,
          loading: false,
          saving: false,
          error: null,
        });
      } catch (error) {
        updateError("structured prototype studio recovery failed", error);
        if (mountedRef.current) {
          setStudio((current) => ({ ...current, loading: false, saving: false }));
        }
      }
    })().finally(() => {
      bootstrapInFlightRef.current = null;
    });
    bootstrapInFlightRef.current = inFlight;
    return inFlight;
  }, [createRuntime, projectId, updateError]);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    return () => {
      mountedRef.current = false;
    };
  }, [load]);

  const applyCommands = useCallback(
    async (batch: StructuredPrototypeCommandBatch): Promise<boolean> => {
      const currentDraft = studio.draft;
      if (!currentDraft || studio.saving) return false;
      setStudio((current) => ({ ...current, saving: true, error: null }));
      try {
        const applied = await applyStructuredPrototypeCommands(currentDraft.draftId, {
          contractVersion: 1,
          clientRequestId: crypto.randomUUID(),
          expectedHeadSequenceNo: currentDraft.headSequenceNo,
          expectedDocumentHash: currentDraft.documentHash,
          batch,
        });
        window.localStorage.removeItem(storageKey(projectId, "runtime-session-id"));
        const runtime = await createRuntime(applied);
        if (!mountedRef.current) return false;
        setStudio((current) => ({
          draft: applied,
          runtime,
          publication: current.publication,
          loading: false,
          saving: false,
          error: null,
        }));
        return true;
      } catch (error) {
        updateError("structured prototype command apply failed", error);
        if (mountedRef.current) {
          setStudio((current) => ({ ...current, saving: false }));
        }
        return false;
      }
    },
    [createRuntime, projectId, studio.draft, studio.saving, updateError],
  );

  const sendRuntimeEvents = useCallback(
    async (events: RuntimeEvent[]): Promise<boolean> => {
      const current = studio.runtime;
      if (!current || studio.saving || events.length === 0) return false;
      setStudio((value) => ({ ...value, saving: true, error: null }));
      const clientRequestId = crypto.randomUUID();
      try {
        const applied = await applyStructuredPrototypeRuntimeEvents(current.session.sessionId, {
          contractVersion: 1,
          clientRequestId,
          expectedHeadSequenceNo: current.session.headSequenceNo,
          expectedStateHash: current.session.stateHash,
          batch: {
            clientEventId: clientRequestId,
            expectedSequenceNo: current.session.headSequenceNo,
            events,
          },
        });
        const runtime = decodeRuntime(applied);
        if (!mountedRef.current) return false;
        setStudio((value) => ({ ...value, runtime, saving: false, error: null }));
        return true;
      } catch (error) {
        updateError("structured prototype runtime event failed", error);
        if (mountedRef.current) {
          setStudio((value) => ({ ...value, saving: false }));
        }
        return false;
      }
    },
    [studio.runtime, studio.saving, updateError],
  );

  const checkpointRuntime = useCallback(async (): Promise<boolean> => {
    const current = studio.runtime;
    if (!current || studio.saving) return false;
    setStudio((value) => ({ ...value, saving: true, error: null }));
    try {
      const checkpointed = await checkpointStructuredPrototypeRuntimeSession(
        current.session.sessionId,
        { contractVersion: 1, clientRequestId: crypto.randomUUID() },
      );
      const runtime = decodeRuntime(checkpointed);
      if (!mountedRef.current) return false;
      setStudio((value) => ({ ...value, runtime, saving: false, error: null }));
      return true;
    } catch (error) {
      updateError("structured prototype runtime checkpoint failed", error);
      if (mountedRef.current) {
        setStudio((value) => ({ ...value, saving: false }));
      }
      return false;
    }
  }, [studio.runtime, studio.saving, updateError]);

  const publish = useCallback(async (): Promise<boolean> => {
    const currentDraft = studio.draft;
    if (!currentDraft || studio.saving) return false;
    setStudio((current) => ({ ...current, saving: true, error: null }));
    const requestKey = `publish-request:${currentDraft.draftId}:${currentDraft.headSequenceNo}:${currentDraft.documentHash}`;
    const clientRequestId = requestIdentity(projectId, requestKey);
    try {
      const published = await publishStructuredPrototypeDraft(currentDraft.draftId, {
        contractVersion: 1,
        clientRequestId,
        expectedHeadSequenceNo: currentDraft.headSequenceNo,
        expectedDocumentHash: currentDraft.documentHash,
      });
      const activeDraft = published.activeDraft;
      window.localStorage.removeItem(storageKey(projectId, "runtime-session-id"));
      finishRequestIdentity(projectId, requestKey);
      const runtime = await createRuntime(activeDraft);
      if (!mountedRef.current) return false;
      const publication: StructuredPrototypePublication = published;
      setStudio({
        draft: activeDraft,
        runtime,
        publication,
        loading: false,
        saving: false,
        error: null,
      });
      return true;
    } catch (error) {
      updateError("structured prototype publication failed", error);
      if (mountedRef.current) {
        setStudio((current) => ({ ...current, saving: false }));
      }
      return false;
    }
  }, [createRuntime, projectId, studio.draft, studio.saving, updateError]);

  const adoptAiDraft = useCallback(
    async (draft: StructuredPrototypeDraft): Promise<void> => {
      window.localStorage.removeItem(storageKey(projectId, "runtime-session-id"));
      const runtime = await createRuntime(draft);
      if (!mountedRef.current) return;
      setStudio((current) => ({
        ...current,
        draft,
        runtime,
        saving: false,
        error: null,
      }));
    },
    [createRuntime, projectId],
  );

  return {
    ...studio,
    applyCommands,
    sendRuntimeEvents,
    checkpointRuntime,
    publish,
    adoptAiDraft,
    retry: load,
  };
}
