"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import type {
  RuntimeCatalog,
  RuntimeExecutorConfig,
} from "@/lib/types";
import type { TranslationKey } from "@/lib/i18n";
import { testRuntimeExecutor, validateRuntimeCatalog } from "@/lib/api";
import { Loader2, CheckCircle, XCircle } from "lucide-react";

interface RuntimeCatalogEditorProps {
  catalog: RuntimeCatalog;
  onChange?: (catalog: RuntimeCatalog) => Promise<void>;
  onSave?: (catalog: RuntimeCatalog) => Promise<void>;
  className?: string;
}

// api_endpoint defaults to empty so a freshly-added executor runs the local CLI
// (the backend treats "no endpoint + no key" as local-CLI mode). The user can
// still type a remote endpoint + key to target a hosted API.
const EXECUTOR_DEFAULTS: Record<"claude" | "codex", { label: string; api_endpoint: string; default_model: string; protocol: "anthropic" | "openai" }> = {
  claude: {
    label: "Claude",
    api_endpoint: "",
    default_model: "claude-sonnet-4-6",
    protocol: "anthropic",
  },
  codex: {
    label: "Codex",
    api_endpoint: "",
    default_model: "gpt-5-codex",
    protocol: "openai",
  },
};

function normalizeCatalog(catalog: RuntimeCatalog): RuntimeCatalog {
  return {
    ...catalog,
    executors: catalog.executors.map((executor) => ({
      ...executor,
      api_endpoint: executor.api_endpoint ?? null,
      api_key_configured: executor.api_key_configured ?? Boolean(executor.api_key),
      default_model: executor.default_model ?? null,
    })),
  };
}

function stripEmptyApiKeys(catalog: RuntimeCatalog): RuntimeCatalog {
  return {
    ...catalog,
    executors: catalog.executors.map(({ api_key, ...executor }) => ({
      ...executor,
      ...(api_key ? { api_key } : {}),
    })),
  };
}

export function RuntimeCatalogEditor({
  catalog,
  onChange,
  className,
}: RuntimeCatalogEditorProps) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [localCatalog, setLocalCatalog] = useState<RuntimeCatalog>(() => normalizeCatalog(catalog));
  const [addingNew, setAddingNew] = useState(false);
  const [newExecutorLabel, setNewExecutorLabel] = useState(EXECUTOR_DEFAULTS.claude.label);
  const [newExecutorType, setNewExecutorType] = useState<"claude" | "codex">("claude");
  const [newApiEndpoint, setNewApiEndpoint] = useState(EXECUTOR_DEFAULTS.claude.api_endpoint);
  const [newApiKey, setNewApiKey] = useState("");
  const [newDefaultModel, setNewDefaultModel] = useState(EXECUTOR_DEFAULTS.claude.default_model);

  const handleExecutorTypeChange = (nextType: "claude" | "codex") => {
    const prevDefaults = EXECUTOR_DEFAULTS[newExecutorType];
    const nextDefaults = EXECUTOR_DEFAULTS[nextType];
    setNewExecutorType(nextType);
    if (!newExecutorLabel.trim() || newExecutorLabel === prevDefaults.label) {
      setNewExecutorLabel(nextDefaults.label);
    }
    if (!newApiEndpoint.trim() || newApiEndpoint === prevDefaults.api_endpoint) {
      setNewApiEndpoint(nextDefaults.api_endpoint);
    }
    if (!newDefaultModel.trim() || newDefaultModel === prevDefaults.default_model) {
      setNewDefaultModel(nextDefaults.default_model);
    }
  };

  useEffect(() => {
    setLocalCatalog(normalizeCatalog(catalog));
  }, [catalog]);

  const handleChange = async (updatedCatalog: RuntimeCatalog) => {
    setLocalCatalog(updatedCatalog);
    if (onChange) {
      await onChange(stripEmptyApiKeys(updatedCatalog));
    }
  };

  const updateExecutor = (index: number, updates: Partial<RuntimeExecutorConfig>) => {
    const updatedCatalog = {
      ...localCatalog,
      executors: localCatalog.executors.map((executor, executorIndex) =>
        executorIndex === index ? { ...executor, ...updates } : executor
      ),
    };
    handleChange(updatedCatalog);
  };

  const updateConductorLLM = (updates: Partial<NonNullable<RuntimeCatalog["conductor_llm"]>>) => {
    handleChange({
      ...localCatalog,
      conductor_llm: { ...(localCatalog.conductor_llm ?? {}), ...updates },
    });
  };

  const removeExecutor = (index: number) => {
    const updatedCatalog = {
      ...localCatalog,
      executors: localCatalog.executors.filter((_, executorIndex) => executorIndex !== index),
    };
    handleChange(updatedCatalog);
  };

  const toggleExecutorEnabled = (index: number) => {
    const executor = localCatalog.executors[index];
    updateExecutor(index, { enabled: !executor.enabled });
  };

  const handleAddExecutor = () => {
    const label = newExecutorLabel.trim() || EXECUTOR_DEFAULTS[newExecutorType].label;

    const newExecutor: RuntimeExecutorConfig = {
      id: crypto.randomUUID(),
      label,
      enabled: true,
      executor_type: newExecutorType,
      api_endpoint: newApiEndpoint.trim() || null,
      api_key: newApiKey.trim() || null,
      default_model: newDefaultModel.trim() || null,
      protocol: EXECUTOR_DEFAULTS[newExecutorType].protocol,
      providers: [],
      default_provider_id: null,
    };

    const updatedCatalog = {
      ...localCatalog,
      executors: [...localCatalog.executors, newExecutor],
    };
    handleChange(updatedCatalog);

    // Reset form
    setNewExecutorLabel(EXECUTOR_DEFAULTS.claude.label);
    setNewExecutorType("claude");
    setNewApiEndpoint(EXECUTOR_DEFAULTS.claude.api_endpoint);
    setNewApiKey("");
    setNewDefaultModel(EXECUTOR_DEFAULTS.claude.default_model);
    setAddingNew(false);
  };

  const cancelAddExecutor = () => {
    setNewExecutorLabel(EXECUTOR_DEFAULTS.claude.label);
    setNewExecutorType("claude");
    setNewApiEndpoint(EXECUTOR_DEFAULTS.claude.api_endpoint);
    setNewApiKey("");
    setNewDefaultModel(EXECUTOR_DEFAULTS.claude.default_model);
    setAddingNew(false);
  };

  return (
    <div className={cn("space-y-6", className)}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("runtime.configure.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("runtime.configure.desc")}
          </p>
        </div>
        <button
          type="button"
          onClick={async () => {
            try {
              const result = await validateRuntimeCatalog(localCatalog);
              if (result.valid) {
                addToast({ type: "success", title: t("runtime.catalog.valid") });
              } else {
                addToast({
                  type: "error",
                  title: t("runtime.catalog.validationFailed"),
                  message: result.error ?? t("runtime.catalog.unknownError"),
                });
              }
            } catch (err) {
              addToast({
                type: "error",
                title: t("runtime.catalog.validationFailed"),
                message: err instanceof Error ? err.message : String(err),
              });
            }
          }}
          className="text-xs font-bold uppercase tracking-widest text-text-muted hover:text-foreground border border-border-subtle rounded-md px-3 py-1.5"
        >
          {t("runtime.catalog.validate")}
        </button>
      </div>

      <div className="space-y-4">
        {localCatalog.executors.map((executor, executorIndex) => (
          <ExecutorCard
            key={executor.id}
            executor={executor}
            executorIndex={executorIndex}
            onUpdate={(updates) => updateExecutor(executorIndex, updates)}
            onRemove={() => removeExecutor(executorIndex)}
            onToggleEnabled={() => toggleExecutorEnabled(executorIndex)}
            onTest={async (exec) => {
              const result = await testRuntimeExecutor({
                executor_id: exec.id,
                api_endpoint: exec.api_endpoint,
                ...(exec.api_key ? { api_key: exec.api_key } : {}),
              });
              return result;
            }}
            t={t}
          />
        ))}

        {addingNew ? (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{t("runtime.executor.addExecutor")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="min-w-0 space-y-1">
                  <label className="text-xs text-muted-foreground">{t("runtime.executor.label")}</label>
                  <Input
                    value={newExecutorLabel}
                    onChange={(e) => setNewExecutorLabel(e.target.value)}
                    placeholder={t("runtime.executor.label")}
                  />
                </div>
                <div className="min-w-0 space-y-1">
                  <label className="text-xs text-muted-foreground">{t("runtime.executor.type")}</label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="newExecutorType"
                        value="claude"
                        checked={newExecutorType === "claude"}
                        onChange={() => handleExecutorTypeChange("claude")}
                      />
                      {t("runtime.executor.claudeCli")}
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="newExecutorType"
                        value="codex"
                        checked={newExecutorType === "codex"}
                        onChange={() => handleExecutorTypeChange("codex")}
                      />
                      {t("runtime.executor.codexCli")}
                    </label>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="min-w-0 space-y-1">
                  <label className="text-xs text-muted-foreground">{t("runtime.executor.apiEndpoint")}</label>
                  <Input
                    value={newApiEndpoint}
                    onChange={(e) => setNewApiEndpoint(e.target.value)}
                    placeholder={t("runtime.executor.endpointPlaceholder")}
                  />
                </div>
                <div className="min-w-0 space-y-1">
                  <label className="text-xs text-muted-foreground">{t("runtime.executor.apiKey")}</label>
                  <Input
                    type="password"
                    value={newApiKey}
                    onChange={(e) => setNewApiKey(e.target.value)}
                    placeholder={t("runtime.executor.keyPlaceholder")}
                  />
                </div>
              </div>

              <div className="min-w-0 space-y-1">
                <label className="text-xs text-muted-foreground">{t("runtime.executor.defaultModel")}</label>
                <Input
                  value={newDefaultModel}
                  onChange={(e) => setNewDefaultModel(e.target.value)}
                  placeholder={t("runtime.executor.modelPlaceholder")}
                />
              </div>

              <div className="flex gap-2">
                <Button size="sm" onClick={handleAddExecutor}>
                  {t("runtime.executor.addExecutor")}
                </Button>
                <Button size="sm" variant="outline" onClick={cancelAddExecutor}>
                  {t("issue.cancel")}
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Button variant="outline" onClick={() => setAddingNew(true)}>
            + {t("runtime.executor.addExecutor")}
          </Button>
        )}
      </div>

      <ConductorLLMSection
        catalog={localCatalog}
        onUpdate={updateConductorLLM}
        t={t}
      />
    </div>
  );
}

interface ConductorLLMSectionProps {
  catalog: RuntimeCatalog;
  onUpdate: (updates: Partial<NonNullable<RuntimeCatalog["conductor_llm"]>>) => void;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

function ConductorLLMSection({ catalog, onUpdate, t }: ConductorLLMSectionProps) {
  const cfg = catalog.conductor_llm ?? {};
  const selected = catalog.executors.find((e) => e.id === cfg.executor_id) ?? null;
  const protocol = selected?.protocol ?? "anthropic";
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("runtime.conductor.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("runtime.conductor.desc")}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.conductor.executor")}</label>
            <select
              value={cfg.executor_id ?? ""}
              onChange={(e) => onUpdate({ executor_id: e.target.value || null })}
              className="h-9 w-full rounded-md border border-border-subtle bg-surface-input px-3 text-sm"
            >
              <option value="">{t("runtime.conductor.autoPick")}</option>
              {catalog.executors.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.label} ({e.protocol ?? "anthropic"})
                </option>
              ))}
            </select>
          </div>
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.conductor.model")}</label>
            <Input
              value={cfg.model ?? ""}
              onChange={(e) => onUpdate({ model: e.target.value || null })}
              placeholder={selected?.default_model || t("runtime.executor.modelPlaceholder")}
            />
          </div>
        </div>
        {selected && (
          <p className="text-[11px] text-muted-foreground">
            {t("runtime.conductor.resolvedProtocol", { protocol })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

interface ExecutorCardProps {
  executor: RuntimeExecutorConfig;
  executorIndex: number;
  onUpdate: (updates: Partial<RuntimeExecutorConfig>) => void;
  onRemove: () => void;
  onToggleEnabled: () => void;
  onTest: (executor: RuntimeExecutorConfig) => Promise<{ success: boolean; latency_ms?: number; error?: string }>;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

function ExecutorCard({
  executor,
  onUpdate,
  onRemove,
  onToggleEnabled,
  onTest,
  t,
}: ExecutorCardProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; latency_ms?: number; error?: string; mode?: string } | null>(null);

  // No key configured (neither freshly typed nor persisted on the backend) means
  // this executor runs the local CLI with its own default login.
  const isLocalMode = !executor.api_key && !executor.api_key_configured;

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await onTest(executor);
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, error: String(err) });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-medium">
              {executor.executor_type === "claude" ? t("runtime.executor.claudeCli") : t("runtime.executor.codexCli")}
            </span>
            <span className="text-sm text-muted-foreground">{executor.label}</span>
            <span className="text-xs text-muted-foreground">({executor.id})</span>
            {isLocalMode && (
              <span className="rounded-full border border-brand/40 bg-brand/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand">
                {t("runtime.executor.localCliBadge")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onToggleEnabled}
            >
              {executor.enabled ? t("runtime.executor.enabled") : t("runtime.executor.disabled")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleTest}
              disabled={testing}
            >
              {testing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : testResult ? (
                testResult.success ? (
                  <CheckCircle className="h-3 w-3 text-green-500" />
                ) : (
                  <XCircle className="h-3 w-3 text-destructive" />
                )
              ) : (
                t("runtime.catalog.test")
              )}
            </Button>
            {testResult?.success && (
              <span className="text-xs text-green-500">
                {testResult.mode === "local_cli"
                  ? t("runtime.catalog.testLocalOk")
                  : `${testResult.latency_ms}ms`}
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={onRemove}
              className="text-destructive hover:text-destructive"
            >
              {t("runtime.executor.delete")}
            </Button>
          </div>
        </div>
        {testResult && !testResult.success && (
          <p className="mt-2 break-words text-xs text-destructive" title={testResult.error}>
            {testResult.error}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="min-w-0 space-y-1">
          <label className="text-xs text-muted-foreground">{t("runtime.executor.label")}</label>
          <Input
            value={executor.label || ""}
            onChange={(e) => onUpdate({ label: e.target.value })}
            placeholder={t("runtime.executor.namePlaceholder")}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.executor.apiEndpoint")}</label>
            <Input
              value={executor.api_endpoint || ""}
              onChange={(e) => onUpdate({ api_endpoint: e.target.value || null })}
              placeholder={t("runtime.executor.endpointPlaceholder")}
            />
          </div>
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.executor.apiKey")}</label>
            <Input
              type="password"
              value={executor.api_key || ""}
              onChange={(e) => onUpdate({ api_key: e.target.value || null })}
              placeholder={
                executor.api_key_configured
                  ? t("runtime.executor.keyConfiguredPlaceholder")
                  : t("runtime.executor.keyPlaceholder")
              }
            />
            {executor.api_key_configured && !executor.api_key && (
              <p className="text-[11px] text-muted-foreground">
                {t("runtime.executor.keyHiddenHint")}
              </p>
            )}
            {isLocalMode && (
              <p className="text-[11px] text-brand/80">
                {t("runtime.executor.localCliHint")}
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.executor.defaultModel")}</label>
            <Input
              value={executor.default_model || ""}
              onChange={(e) => onUpdate({ default_model: e.target.value || null })}
              placeholder={t("runtime.executor.modelPlaceholder")}
            />
          </div>
          <div className="min-w-0 space-y-1">
            <label className="text-xs text-muted-foreground">{t("runtime.executor.protocol")}</label>
            <select
              value={executor.protocol ?? "anthropic"}
              onChange={(e) => onUpdate({ protocol: e.target.value as "anthropic" | "openai" })}
              className="h-9 w-full rounded-md border border-border-subtle bg-surface-input px-3 text-sm"
            >
              <option value="anthropic">{t("runtime.executor.protocolAnthropic")}</option>
              <option value="openai">{t("runtime.executor.protocolOpenai")}</option>
            </select>
            <p className="text-[11px] text-muted-foreground">{t("runtime.executor.protocolHint")}</p>
          </div>
        </div>

        <div className="border-t border-border-subtle/50 pt-4">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <span className="text-brand">{showAdvanced ? "▼" : "▶"}</span>
            {t("runtime.executor.advanced")}
          </button>
          {showAdvanced && (
            <div className="mt-3 space-y-3 pl-2">
              <div className="min-w-0 space-y-1">
                <label className="text-xs text-muted-foreground">
                  {t("runtime.provider.commandTemplate")} <span className="text-[10px]">(e.g., &quot;model=&#123;model&#125; provider=&#123;provider&#125;&quot;)</span>
                </label>
                {executor.providers.map((provider, providerIndex) => (
                  <div key={provider.id}>
                    <label className="text-xs text-muted-foreground">
                      {provider.label} - {t("runtime.provider.commandTemplate")}
                    </label>
                    <Input
                      value={provider.command_template || ""}
                      onChange={(e) => {
                        const newProviders = [...executor.providers];
                        newProviders[providerIndex] = {
                          ...newProviders[providerIndex],
                          command_template: e.target.value || null,
                        };
                        onUpdate({ providers: newProviders });
                      }}
                      placeholder={t("runtime.placeholder.command")}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
