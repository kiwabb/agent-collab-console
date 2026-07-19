"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  ExternalLink,
  LoaderCircle,
  Play,
  RotateCcw,
  Square,
  WandSparkles,
} from "lucide-react";

import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { ProjectEnvVarEditor } from "./ProjectEnvVarEditor";
import { ProjectRunStatusPanel } from "./ProjectRunStatusPanel";
import { ProjectStartupServicePanel } from "./ProjectStartupServicePanel";
import type { StartupStepStatus } from "./projectStartupConfig";
import { useProjectStartupConfig } from "./useProjectStartupConfig";

interface Props {
  projectId: string;
  initialProject: Project;
}

interface StepProps {
  label: string;
  description: string;
  status: StartupStepStatus;
}

function StartupStep({ label, description, status }: StepProps) {
  const Icon =
    status === "complete"
      ? CheckCircle2
      : status === "error"
        ? AlertTriangle
        : status === "active"
          ? LoaderCircle
          : Circle;
  return (
    <li
      className={cn(
        "flex min-w-0 flex-1 items-start gap-3 rounded-xl border px-4 py-3",
        status === "error"
          ? "border-status-failed/40 bg-status-failed/5"
          : status === "active"
            ? "border-status-tool/40 bg-status-tool/5"
            : status === "complete" || status === "ready"
              ? "border-status-done/35 bg-status-done/5"
              : "border-border-subtle bg-surface",
      )}
    >
      <Icon
        size={18}
        aria-hidden
        className={cn(
          "mt-0.5 shrink-0",
          status === "error"
            ? "text-status-failed"
            : status === "active"
              ? "animate-spin text-status-tool"
              : status === "complete" || status === "ready"
                ? "text-status-done"
                : "text-text-muted",
        )}
      />
      <div className="min-w-0">
        <p className="text-sm font-semibold">{label}</p>
        <p className="mt-0.5 text-xs leading-5 text-text-muted">{description}</p>
      </div>
    </li>
  );
}

export function ProjectStartupConfigPage({ projectId, initialProject }: Props) {
  const { t } = useI18n();
  const config = useProjectStartupConfig(projectId, initialProject);
  const hasAnalysis =
    config.analysis !== null ||
    Boolean(config.startupConfig?.services.length) ||
    Boolean(config.project.setup_script?.trim() || config.project.run_command?.trim());
  const running = config.runStatus?.running === true;
  const externalReady = config.startupState.readinessState === "ready" && !running;
  const occupiedUnknown =
    config.startupState.serviceState === "reachable" &&
    config.startupState.readinessState !== "ready" &&
    !running;
  const serviceStarting =
    running &&
    (config.startupState.readinessState === "unreachable" ||
      config.startupState.readinessState === "occupied_unknown");
  const serviceUnhealthy = config.startupState.readinessState === "identified_unready";
  const runFailed = config.startupState.runOutcome === "failed";
  const runCompleted = config.startupState.runOutcome === "completed";
  const analysisStepDescription =
    config.startupState.analysis === "active"
      ? t("startupConfig.stepAnalyze.active")
      : config.startupState.analysis === "complete"
        ? t("startupConfig.stepAnalyze.complete")
        : config.startupState.analysis === "error"
          ? t("startupConfig.stepAnalyze.error")
          : t("startupConfig.stepAnalyze.pending");
  const runStepDescription = config.hasInvalidStartupService
    ? t("startupConfig.stepRun.invalidConfig")
    : externalReady
      ? t("startupConfig.stepRun.external")
      : occupiedUnknown
        ? t("startupConfig.stepRun.occupiedUnknown")
        : serviceUnhealthy
          ? t("startupConfig.stepRun.unhealthy")
          : serviceStarting
            ? t("startupConfig.stepRun.starting")
            : runFailed
            ? t("startupConfig.stepRun.failed", { code: config.runStatus?.exit_code ?? "" })
            : running
              ? t("startupConfig.stepRun.running")
              : runCompleted
                ? t("startupConfig.stepRun.completed")
                : config.startupState.run === "ready"
                  ? t("startupConfig.stepRun.ready")
                  : t("startupConfig.stepRun.pending");
  const serviceStateLabel = config.hasInvalidStartupService
    ? t("startupConfig.serviceState.invalidConfig")
    : externalReady
      ? t("startupConfig.serviceState.ready")
      : occupiedUnknown
        ? t("startupConfig.serviceState.occupiedUnknown")
        : serviceUnhealthy
          ? t("startupConfig.serviceState.unhealthy")
          : serviceStarting
            ? t("startupConfig.serviceState.starting")
            : config.startupState.serviceState === "unreachable"
            ? t("startupConfig.serviceState.offline")
            : t("startupConfig.serviceState.unknown");
  const serviceUrl =
    (externalReady ? config.runStatus?.readiness.url : null) ?? config.analysis?.accessUrl ?? null;
  const configureStepDescription =
    config.startupState.unsavedCount > 0
      ? t("startupConfig.stepConfigure.unsaved", { count: config.startupState.unsavedCount })
      : t("startupConfig.stepConfigure.detail", {
          count: config.startupState.envCount,
          missing: config.startupState.missingCount,
        });

  if (config.loading) {
    return (
      <div
        data-density="startup-config-loading"
        className="motion-essential flex min-h-[280px] items-center justify-center gap-3 rounded-2xl border border-status-tool/25 bg-status-tool/5 text-sm font-semibold text-text-muted"
      >
        <AgentThinkingIndicator phase="tool" size={18} />
        {t("startupConfig.loading")}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1080px] space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand">
            {t("startupConfig.eyebrow")}
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight">{t("startupConfig.title")}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
            {t("startupConfig.subtitle")}
          </p>
        </div>
        <Button
          variant={hasAnalysis ? "outline" : "default"}
          onClick={config.startAnalysis}
          disabled={config.isAnalyzing}
          className="min-h-11 shrink-0 gap-2"
        >
          {config.isAnalyzing ? (
            <AgentThinkingIndicator phase="thinking" size={16} />
          ) : hasAnalysis ? (
            <RotateCcw size={16} />
          ) : (
            <WandSparkles size={16} />
          )}
          {config.isAnalyzing
            ? t("startupConfig.analyzing")
            : hasAnalysis
              ? t("startupConfig.reanalyze")
              : t("startupConfig.analyze")}
        </Button>
      </header>

      {config.loadError && (
        <div
          role="alert"
          className="rounded-xl border border-status-failed/40 bg-status-failed/5 p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-status-failed">{config.loadError}</p>
            <Button variant="outline" size="sm" onClick={config.refresh} className="gap-2">
              <RotateCcw size={14} />
              {t("startupConfig.retry")}
            </Button>
          </div>
        </div>
      )}

      {config.hasInvalidStartupService && (
        <div
          role="alert"
          className="rounded-xl border border-status-failed/40 bg-status-failed/5 p-4"
        >
          <p className="text-sm font-semibold text-status-failed">
            {t("startupConfig.invalidReadinessTitle")}
          </p>
          <p className="mt-1 text-sm text-text-muted">
            {t("startupConfig.invalidReadinessDetail")}
          </p>
          <Button variant="outline" size="sm" onClick={config.startAnalysis} className="mt-3 gap-2">
            <RotateCcw size={14} />
            {t("startupConfig.reanalyze")}
          </Button>
        </div>
      )}

      {config.analysisFeedback && (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "rounded-xl border p-4 text-sm",
            config.analysisFeedback === "failed"
              ? "border-status-failed/40 bg-status-failed/5 text-status-failed"
              : "border-status-awaiting/40 bg-status-awaiting/5 text-foreground",
          )}
        >
          {config.analysisFeedback === "failed"
            ? t("startupConfig.analysisFailedDetail")
            : t("startupConfig.analysisStillRunning")}
        </div>
      )}

      <ol className="grid gap-3 md:grid-cols-3" aria-label={t("startupConfig.progressLabel")}>
        <StartupStep
          label={t("startupConfig.stepAnalyze")}
          description={analysisStepDescription}
          status={config.startupState.analysis}
        />
        <StartupStep
          label={t("startupConfig.stepConfigure")}
          description={configureStepDescription}
          status={config.startupState.configure}
        />
        <StartupStep
          label={t("startupConfig.stepRun")}
          description={runStepDescription}
          status={config.startupState.run}
        />
      </ol>

      <section
        aria-labelledby="startup-summary-heading"
        className="border-y border-border-subtle bg-surface py-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="startup-summary-heading" className="text-base font-semibold">
              {t("startupConfig.summaryTitle")}
            </h3>
            <p className="mt-1 text-sm text-text-muted">
              {config.analysis?.updatedAt
                ? t("startupConfig.lastAnalyzed", {
                    time: new Date(config.analysis.updatedAt).toLocaleString(),
                  })
                : t("startupConfig.notAnalyzed")}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span
              aria-live="polite"
              className={cn(
                "inline-flex min-h-8 items-center gap-2 rounded-full border px-3 text-xs font-semibold",
                config.startupState.readinessState === "ready"
                  ? "border-status-done/40 bg-status-done/10 text-status-done"
                  : serviceStarting
                    ? "border-status-awaiting/40 bg-status-awaiting/10 text-status-awaiting"
                    : "border-border-subtle bg-surface text-text-muted",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "size-2 rounded-full",
                  config.startupState.readinessState === "ready"
                    ? "bg-status-done"
                    : serviceStarting
                      ? "animate-pulse bg-status-awaiting"
                      : "bg-text-muted",
                )}
              />
              {serviceStateLabel}
            </span>
            {serviceUrl && (
              <a
                href={serviceUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border-subtle px-3 text-sm font-semibold text-brand hover:bg-surface-hover"
              >
                <ExternalLink size={15} />
                {serviceUrl}
              </a>
            )}
          </div>
        </div>

        {config.startupConfig && config.startupConfig.services.length > 0 ? (
          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm font-semibold">
                {t("startupConfig.servicesTitle", {
                  count: config.startupConfig.services.length,
                })}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={() => void config.startAllServices()}
                  disabled={config.runBusy || config.isAnalyzing || !config.startupState.canStart}
                  className="gap-2"
                >
                  <Play size={14} />
                  {t("startupConfig.startAll")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void config.stopAllServices()}
                  disabled={config.runBusy}
                  className="gap-2"
                >
                  <Square size={14} />
                  {t("startupConfig.stopAll")}
                </Button>
              </div>
            </div>
            <div className="mt-3 space-y-3">
              {config.startupConfig.services.map((service) => (
                <ProjectStartupServicePanel
                  key={service.service_id}
                  projectId={projectId}
                  service={service}
                  disabled={config.runBusy || config.isAnalyzing}
                  onStatusChange={config.updateServiceStatus}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-border-subtle bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                {t("projects.setupScript")}
              </p>
              <pre className="mt-3 whitespace-pre-wrap break-words font-mono text-sm leading-6">
                {config.project.setup_script?.trim() || t("startupConfig.notConfigured")}
              </pre>
            </div>
            <div className="rounded-lg border border-border-subtle bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                {t("projects.runCommandLabel")}
              </p>
              <pre className="mt-3 whitespace-pre-wrap break-words font-mono text-sm leading-6">
                {config.project.run_command?.trim() || t("startupConfig.notConfigured")}
              </pre>
            </div>
          </div>
        )}

        {(config.startupConfig?.notes.length || config.analysis?.notes.length) && (
          <div className="mt-4 rounded-xl border border-border-subtle bg-surface px-4 py-3">
            <p className="text-sm font-semibold">{t("startupConfig.notes")}</p>
            <ul className="mt-2 space-y-1 text-sm leading-6 text-text-muted">
              {(config.startupConfig?.notes.length
                ? config.startupConfig.notes
                : (config.analysis?.notes ?? [])
              ).map((note, index) => (
                <li key={`${config.analysis?.taskId}:${index}`} className="flex gap-2">
                  <span aria-hidden className="text-brand">
                    •
                  </span>
                  <span>{note}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <ProjectEnvVarEditor
        envVars={config.envVars}
        savingEnvId={config.savingEnvId}
        onAdd={config.addEnvVar}
        onChange={config.updateEnvVar}
        onSave={(envVar) => void config.saveEnvVar(envVar)}
        onDelete={(envVar) => void config.deleteEnvVar(envVar)}
      />

      {(!config.startupConfig || config.startupConfig.services.length === 0) && (
        <ProjectRunStatusPanel
          runStatus={config.runStatus}
          runLogs={config.runLogs}
          startupState={config.startupState}
          runBusy={config.runBusy}
          isAnalyzing={config.isAnalyzing}
          onStart={config.startRun}
          onStop={config.stopRun}
        />
      )}
    </div>
  );
}
