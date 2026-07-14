"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getCodexTask, getProjectTasks } from "@/lib/api/tasks";
import {
  deleteProjectEnvVar,
  getProject,
  getProjectEnvVars,
  getProjectRunLogs,
  getProjectRunStatus,
  getProjectStartupConfig,
  isProjectRunStartError,
  putProjectEnvVars,
  startProjectRun,
  startProjectScriptTask,
  startAllProjectServices,
  stopProjectRun,
  stopAllProjectServices,
} from "@/lib/api/projects";
import type {
  Project,
  ProjectEnvVarDisplay,
  ProjectRunLogLine,
  ProjectRunStatus,
  ProjectStartupConfig,
} from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";

import {
  deriveProjectStartupState,
  readProjectStartupAnalysis,
  selectProjectRunRefreshError,
  selectLatestProjectStartupTask,
  shouldPollProjectServiceStatus,
  updateProjectRunRefreshError,
} from "./projectStartupConfig";
import type { ProjectRunRefreshErrors } from "./projectStartupConfig";
import { describeScriptTaskTerminalStatus } from "./scriptTaskStatus";

const ANALYSIS_POLL_MS = 5_000;
const ANALYSIS_POLL_LIMIT_MS = 3 * 60_000;
const RUN_LOG_POLL_MS = 2_000;
const SERVICE_STATUS_POLL_MS = 5_000;

export interface ProjectEnvVarDraft extends ProjectEnvVarDisplay {
  id: string;
  value: string;
  isNew: boolean;
  dirty: boolean;
}

type EnvVarPatch = Partial<Pick<ProjectEnvVarDraft, "name" | "value" | "secret">>;
type AnalysisFeedback = "failed" | "still_running" | null;

function toDrafts(envVars: ProjectEnvVarDisplay[]): ProjectEnvVarDraft[] {
  return envVars.map((envVar) => ({
    ...envVar,
    id: `stored:${envVar.name}`,
    value: envVar.value ?? "",
    isNew: false,
    dirty: false,
  }));
}

export function useProjectStartupConfig(projectId: string, initialProject: Project) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [project, setProject] = useState(initialProject);
  const [envVars, setEnvVars] = useState<ProjectEnvVarDraft[]>([]);
  const [latestTask, setLatestTask] = useState<Awaited<ReturnType<typeof getCodexTask>> | null>(
    null,
  );
  const [runStatus, setRunStatus] = useState<ProjectRunStatus | null>(null);
  const [runLogs, setRunLogs] = useState<ProjectRunLogLine[]>([]);
  const [startupConfig, setStartupConfig] = useState<ProjectStartupConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runRefreshErrors, setRunRefreshErrors] = useState<ProjectRunRefreshErrors>({
    status: null,
    logs: null,
  });
  const [analysisTaskId, setAnalysisTaskId] = useState<string | null>(null);
  const [analysisStarting, setAnalysisStarting] = useState(false);
  const [analysisFeedback, setAnalysisFeedback] = useState<AnalysisFeedback>(null);
  const [savingEnvId, setSavingEnvId] = useState<string | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const newEnvIdRef = useRef(0);
  const lastRunLogSeqRef = useRef(0);

  const refresh = useCallback(async () => {
    setLoadError(null);
    try {
      const [nextProject, envResponse, tasks, nextRunStatus, nextRunLogs, nextStartupConfig] =
        await Promise.all([
          getProject(projectId),
          getProjectEnvVars(projectId),
          getProjectTasks(projectId),
          getProjectRunStatus(projectId),
          getProjectRunLogs(projectId),
          getProjectStartupConfig(projectId),
        ]);
      const nextTask = selectLatestProjectStartupTask(tasks);
      setProject(nextProject);
      setEnvVars(toDrafts(envResponse.env_vars));
      setLatestTask(nextTask);
      setRunStatus(nextRunStatus);
      setRunLogs(nextRunLogs.lines);
      setRunRefreshErrors({ status: null, logs: null });
      setStartupConfig(nextStartupConfig);
      lastRunLogSeqRef.current = nextRunLogs.last_seq;
      if (nextTask && !describeScriptTaskTerminalStatus(nextTask.status).terminal) {
        setAnalysisTaskId(nextTask.id);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : t("startupConfig.loadFailed");
      console.error("startup config refresh failed:", err);
      setLoadError(message);
    } finally {
      setLoading(false);
    }
  }, [projectId, t]);

  const refreshEnvVars = useCallback(async () => {
    const response = await getProjectEnvVars(projectId);
    setEnvVars(toDrafts(response.env_vars));
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!analysisTaskId) return;
    let cancelled = false;
    const startedAt = Date.now();

    const poll = async () => {
      if (cancelled) return;
      if (Date.now() - startedAt > ANALYSIS_POLL_LIMIT_MS) {
        setAnalysisFeedback("still_running");
        setAnalysisTaskId(null);
        return;
      }
      try {
        const task = await getCodexTask(analysisTaskId);
        if (cancelled) return;
        setLoadError(null);
        setLatestTask(task);
        const terminal = describeScriptTaskTerminalStatus(task.status);
        if (!terminal.terminal) return;
        setAnalysisTaskId(null);
        if (terminal.success) {
          setAnalysisFeedback(null);
          await refresh();
          addToast({ type: "success", title: t("startupConfig.analysisCompleted") });
        } else {
          setAnalysisFeedback("failed");
          addToast({ type: "error", title: t("startupConfig.analysisFailed") });
        }
      } catch (err) {
        console.error("startup analysis poll failed:", err);
        setLoadError(err instanceof Error ? err.message : t("startupConfig.loadFailed"));
      }
    };

    void poll();
    const timer = window.setInterval(poll, ANALYSIS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [analysisTaskId, addToast, refresh, t]);

  const pollServiceStatus = shouldPollProjectServiceStatus(runStatus);
  useEffect(() => {
    if (!pollServiceStatus) return;
    let cancelled = false;
    const pollStatus = async () => {
      try {
        const nextStatus = await getProjectRunStatus(projectId);
        if (cancelled) return;
        setRunStatus(nextStatus);
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", null));
      } catch (err) {
        if (cancelled) return;
        console.error("startup run status poll failed:", err);
        const message = err instanceof Error ? err.message : t("startupConfig.loadFailed");
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", message));
      }
    };
    const timer = window.setInterval(pollStatus, SERVICE_STATUS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pollServiceStatus, projectId, t]);

  const managedRunActive = runStatus?.running === true;
  useEffect(() => {
    if (!managedRunActive) return;
    let cancelled = false;
    const pollLogs = async () => {
      try {
        const response = await getProjectRunLogs(projectId, lastRunLogSeqRef.current);
        if (cancelled) return;
        if (response.lines.length > 0) {
          lastRunLogSeqRef.current = response.last_seq;
          setRunLogs((current) => [...current, ...response.lines]);
        }
        setRunStatus((current) =>
          current
            ? { ...current, running: response.running, exit_code: response.exit_code }
            : current,
        );
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "logs", null));
      } catch (err) {
        if (cancelled) return;
        console.error("startup run logs poll failed:", err);
        const message = err instanceof Error ? err.message : t("startupConfig.loadFailed");
        setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "logs", message));
      }
    };
    const timer = window.setInterval(pollLogs, RUN_LOG_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [managedRunActive, projectId, t]);

  const startAnalysis = useCallback(async () => {
    if (analysisStarting || analysisTaskId) return;
    setAnalysisStarting(true);
    setAnalysisFeedback(null);
    try {
      const response = await startProjectScriptTask(projectId, {
        setup_script: project.setup_script,
        run_command: project.run_command,
      });
      setAnalysisTaskId(response.task_id);
      const task = await getCodexTask(response.task_id);
      setLatestTask(task);
      addToast({
        type: "success",
        title: response.reused
          ? t("projects.scriptSuggestionAlreadyRunning")
          : t("startupConfig.analysisStarted"),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : t("startupConfig.analysisFailed");
      setAnalysisFeedback("failed");
      addToast({ type: "error", title: message });
    } finally {
      setAnalysisStarting(false);
    }
  }, [analysisStarting, analysisTaskId, project, projectId, addToast, t]);

  const addEnvVar = useCallback(() => {
    newEnvIdRef.current += 1;
    setEnvVars((current) => [
      ...current,
      {
        id: `new:${newEnvIdRef.current}`,
        name: "",
        value: "",
        secret: false,
        source: "user",
        is_set: false,
        isNew: true,
        dirty: true,
      },
    ]);
  }, []);

  const updateEnvVar = useCallback((id: string, patch: EnvVarPatch) => {
    setEnvVars((current) =>
      current.map((envVar) => (envVar.id === id ? { ...envVar, ...patch, dirty: true } : envVar)),
    );
  }, []);

  const saveEnvVar = useCallback(
    async (envVar: ProjectEnvVarDraft) => {
      const name = envVar.name.trim();
      if (!name || !envVar.dirty) return;
      setSavingEnvId(envVar.id);
      try {
        await putProjectEnvVars(projectId, {
          name,
          value: envVar.value,
          secret: envVar.secret,
          source: "user",
        });
        await refreshEnvVars();
        addToast({ type: "success", title: t("envConfig.saveSuccess") });
      } catch (err) {
        addToast({
          type: "error",
          title: t("envConfig.saveFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setSavingEnvId(null);
      }
    },
    [projectId, refreshEnvVars, addToast, t],
  );

  const deleteEnvVar = useCallback(
    async (envVar: ProjectEnvVarDraft) => {
      if (envVar.isNew) {
        setEnvVars((current) => current.filter((candidate) => candidate.id !== envVar.id));
        return;
      }
      try {
        await deleteProjectEnvVar(projectId, envVar.name);
        await refreshEnvVars();
        addToast({ type: "success", title: t("envConfig.deleteSuccess") });
      } catch (err) {
        addToast({
          type: "error",
          title: t("envConfig.deleteFailed"),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [projectId, refreshEnvVars, addToast, t],
  );

  const startRun = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      const result = await startProjectRun(projectId);
      if (isProjectRunStartError(result)) {
        if (result.error === "already_running" || result.error === "service_already_reachable") {
          addToast({
            type: "info",
            title:
              result.error === "service_already_reachable"
                ? t("startupConfig.serviceAlreadyReachable")
                : t("projects.runAlreadyRunning"),
            ...(result.error === "service_already_reachable" && result.url
              ? { message: result.url }
              : {}),
          });
          try {
            setRunStatus(await getProjectRunStatus(projectId));
            setRunRefreshErrors((current) => updateProjectRunRefreshError(current, "status", null));
          } catch (err) {
            console.error("startup run status resync failed:", err);
            const message = err instanceof Error ? err.message : t("startupConfig.loadFailed");
            setRunRefreshErrors((current) =>
              updateProjectRunRefreshError(current, "status", message),
            );
          }
        } else if (result.error === "no_run_command") {
          addToast({ type: "error", title: t("projects.runNoCommand") });
        } else if (result.error === "env_incomplete") {
          const names = result.errors?.map((error) => error.name).join(", ") ?? "";
          addToast({
            type: "error",
            title: t("startupConfig.envIncomplete"),
            message: names || result.message,
          });
          await refreshEnvVars();
        } else {
          addToast({
            type: "error",
            title: t("projects.runRefused"),
            message: result.pattern,
          });
        }
        return;
      }
      lastRunLogSeqRef.current = 0;
      setRunLogs([]);
      setRunStatus(result);
      setRunRefreshErrors({ status: null, logs: null });
      addToast({ type: "info", title: t("startupConfig.runSubmitted") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("projects.runStartFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, refreshEnvVars, runBusy, addToast, t]);

  const stopRun = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      setRunStatus(await stopProjectRun(projectId));
      setRunRefreshErrors({ status: null, logs: null });
      addToast({ type: "success", title: t("projects.runStopped") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("projects.runStopFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, runBusy, addToast, t]);

  const startAllServices = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      await startAllProjectServices(projectId);
      addToast({ type: "info", title: t("startupConfig.allServicesStarted") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("projects.runStartFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, runBusy, addToast, t]);

  const stopAllServices = useCallback(async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      await stopAllProjectServices(projectId);
      addToast({ type: "success", title: t("startupConfig.allServicesStopped") });
    } catch (err) {
      addToast({
        type: "error",
        title: t("projects.runStopFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRunBusy(false);
    }
  }, [projectId, runBusy, addToast, t]);

  const isAnalyzing = analysisStarting || analysisTaskId !== null;
  const startupState = useMemo(
    () =>
      deriveProjectStartupState({
        project: {
          ...project,
          run_command: startupConfig?.services[0]?.run_command ?? project.run_command,
        },
        envVars,
        latestTask,
        runStatus: startupConfig?.services.length ? null : runStatus,
        isAnalysisActive: isAnalyzing,
        unsavedCount: envVars.filter((envVar) => envVar.dirty).length,
      }),
    [project, startupConfig, envVars, latestTask, runStatus, isAnalyzing],
  );

  return {
    project,
    startupConfig,
    envVars,
    latestTask,
    analysis: readProjectStartupAnalysis(latestTask),
    runStatus,
    runLogs,
    startupState,
    loading,
    loadError: loadError ?? selectProjectRunRefreshError(runRefreshErrors),
    analysisFeedback,
    isAnalyzing,
    savingEnvId,
    runBusy,
    refresh,
    startAnalysis,
    addEnvVar,
    updateEnvVar,
    saveEnvVar,
    deleteEnvVar,
    startRun,
    stopRun,
    startAllServices,
    stopAllServices,
  };
}
