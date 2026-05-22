"use client";

import { useEffect, useState } from "react";
import { getCodexTaskMessages } from "@/lib/api";
import { buildTaskConversationDetail } from "@/lib/taskConversationDetailUtils";
import type { CodexTaskMessage, ExecutionProcess } from "@/lib/types";

interface TaskConversationDetail {
  messages: CodexTaskMessage[];
  logs: unknown[];
  loading: boolean;
  error: string | null;
}

function createEmptyDetail(): TaskConversationDetail {
  return { messages: [], logs: [], loading: false, error: null };
}

interface UseTaskConversationDetailOptions {
  taskId: string | null;
  executionProcesses: ExecutionProcess[];
  activeProcessId?: string | null;
}

export function useTaskConversationDetail({
  taskId,
  executionProcesses,
  activeProcessId,
}: UseTaskConversationDetailOptions): TaskConversationDetail {
  const [detail, setDetail] = useState<TaskConversationDetail>(createEmptyDetail);
  const [taskMessages, setTaskMessages] = useState<CodexTaskMessage[]>([]);

  useEffect(() => {
    let cancelled = false;

    if (!taskId) {
      setTaskMessages([]);
      setDetail(createEmptyDetail());
      return;
    }

    setDetail((prev) => ({ ...prev, loading: true, error: null }));

    getCodexTaskMessages(taskId)
      .then((msgs) => {
        if (cancelled) return;
        setTaskMessages(msgs || []);
        setDetail((prev) => ({ ...prev, loading: false, error: null }));
      })
      .catch((err) => {
        if (cancelled) return;
        setDetail({
          messages: [],
          logs: [],
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load task conversation detail",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    const next = buildTaskConversationDetail(taskMessages, executionProcesses);
    setDetail((prev) => ({
      ...prev,
      messages: next.messages,
      logs: next.logs,
    }));
  }, [executionProcesses, taskId, taskMessages]);

  return detail;
}
