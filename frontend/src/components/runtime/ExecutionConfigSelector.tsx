"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RuntimeCatalog, RuntimeExecutorConfig } from "@/lib/types";

export interface ExecutionConfigValue {
  executor: string;
  provider: string | null;
  model: string | null;
}

interface ExecutionConfigSelectorProps {
  value: ExecutionConfigValue;
  onChange: (value: ExecutionConfigValue) => void;
  catalog: RuntimeCatalog | null;
  className?: string;
  disabled?: boolean;
}

function getFirstEnabledExecutor(catalog: RuntimeCatalog | null): RuntimeExecutorConfig | null {
  return catalog?.executors.find((executor) => executor.enabled) ?? null;
}

/**
 * Human-readable option text for an executor picker: the user-given name plus a
 * disambiguating suffix (the API host, or `localLabel` when it runs the local
 * CLI). Two executors that share a name (e.g. a local "Claude" and a hosted
 * "Claude") stay tellable apart. Falls back to the id when unnamed.
 */
export function describeExecutorOption(
  executor: { id: string; label?: string | null; api_endpoint?: string | null },
  localLabel: string,
): string {
  const name = (executor.label ?? "").trim() || executor.id;
  let where = localLabel;
  if (executor.api_endpoint) {
    try {
      where = new URL(executor.api_endpoint).host || executor.api_endpoint;
    } catch {
      where = executor.api_endpoint;
    }
  }
  return `${name} · ${where}`;
}

export function normalizeExecutionConfig(
  catalog: RuntimeCatalog | null,
  executor: string,
  provider: string | null,
  model: string | null,
): ExecutionConfigValue {
  if (!catalog) {
    return { executor, provider, model };
  }

  const resolvedExecutor = catalog.executors.find((candidate) => candidate.id === executor && candidate.enabled)
    ?? getFirstEnabledExecutor(catalog)
    ?? catalog.executors.find((candidate) => candidate.id === executor)
    ?? null;

  if (!resolvedExecutor) {
    return { executor, provider, model };
  }

  // Use executor's default_model if model is empty
  const resolvedModel = model || resolvedExecutor.default_model || null;

  return {
    executor: resolvedExecutor.id,
    provider: null,
    model: resolvedModel,
  };
}

export function ExecutionConfigSelector({
  value,
  onChange,
  catalog,
  className,
  disabled = false,
}: ExecutionConfigSelectorProps) {
  const { t } = useI18n();
  const localLabel = t("runtime.executor.localCliBadge");
  const normalizedValue = useMemo(
    () => normalizeExecutionConfig(catalog, value.executor, value.provider, value.model),
    [catalog, value.executor, value.provider, value.model],
  );

  const currentExecutor = catalog?.executors.find((executor) => executor.id === normalizedValue.executor && executor.enabled) ?? null;
  const enabledExecutors = catalog?.executors.filter((executor) => executor.enabled) ?? [];

  const handleExecutorChange = (executorId: string | null) => {
    if (!executorId) return;
    const executor = catalog?.executors.find((e) => e.id === executorId);
    const nextValue: ExecutionConfigValue = {
      executor: executorId,
      provider: null,
      model: executor?.default_model || null,
    };
    if (
      nextValue.executor !== value.executor ||
      nextValue.provider !== value.provider ||
      nextValue.model !== value.model
    ) {
      onChange(nextValue);
    }
  };

  const handleModelChange = (modelValue: string) => {
    const nextValue: ExecutionConfigValue = {
      ...normalizedValue,
      model: modelValue || null,
    };
    if (
      nextValue.executor !== value.executor ||
      nextValue.provider !== value.provider ||
      nextValue.model !== value.model
    ) {
      onChange(nextValue);
    }
  };

  if (!catalog) {
    return (
      <div
        data-density="execution-config-tool-loading"
        className={cn("motion-essential relative flex min-h-[40px] items-center justify-center gap-2 overflow-hidden rounded-lg border border-status-tool/25 bg-status-tool/5 px-3 text-xs font-semibold text-text-muted", className)}
      >
        <span
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool/70 to-transparent"
        />
        <AgentThinkingIndicator phase="tool" size={14} />
        {t("settings.loadingCatalog")}
      </div>
    );
  }

  return (
    <div className={cn("grid grid-cols-1 gap-2 sm:grid-cols-2", className)}>
      <Select
        value={normalizedValue.executor}
        onValueChange={handleExecutorChange}
        disabled={disabled || enabledExecutors.length === 0}
      >
        <SelectTrigger className="w-full min-w-0">
          <SelectValue placeholder="Executor">
            {(value) => {
              const match = enabledExecutors.find((e) => e.id === value);
              return match ? describeExecutorOption(match, localLabel) : "Executor";
            }}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Executor</SelectLabel>
            {enabledExecutors.map((executor) => (
              <SelectItem key={executor.id} value={executor.id}>
                {describeExecutorOption(executor, localLabel)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      <Input
        value={normalizedValue.model || ""}
        onChange={(e) => handleModelChange(e.target.value)}
        placeholder={currentExecutor?.default_model || "Model"}
        disabled={disabled || !currentExecutor}
      />
    </div>
  );
}

export function getFallbackConfig(
  catalog: RuntimeCatalog | null,
  executor: string,
  provider: string | null,
  model: string | null
): ExecutionConfigValue {
  return normalizeExecutionConfig(catalog, executor, provider, model);
}
