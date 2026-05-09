"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
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
    provider: resolvedExecutor.id, // provider now stores the executor id
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
      provider: executorId,
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
      <div className={cn("grid grid-cols-1 gap-2 sm:grid-cols-2", className)}>
        <div className="h-8 rounded-lg bg-surface-hover animate-pulse" />
        <div className="h-8 rounded-lg bg-surface-hover animate-pulse" />
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
          <SelectValue placeholder="Executor" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Executor</SelectLabel>
            {enabledExecutors.map((executor) => (
              <SelectItem key={executor.id} value={executor.id}>
                {executor.label}
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
