"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

function normalizeCatalog(catalog: RuntimeCatalog): RuntimeCatalog {
  return {
    ...catalog,
    executors: catalog.executors.map((executor) => ({
      ...executor,
      api_endpoint: executor.api_endpoint ?? null,
      api_key: executor.api_key ?? null,
      default_model: executor.default_model ?? null,
    })),
  };
}

export function RuntimeCatalogEditor({
  catalog,
  onChange,
  className,
}: RuntimeCatalogEditorProps) {
  const { t } = useI18n();
  const [localCatalog, setLocalCatalog] = useState<RuntimeCatalog>(() => normalizeCatalog(catalog));
  const [addingNew, setAddingNew] = useState(false);
  const [newExecutorLabel, setNewExecutorLabel] = useState("");
  const [newExecutorType, setNewExecutorType] = useState<"claude" | "codex">("claude");
  const [newApiEndpoint, setNewApiEndpoint] = useState("");
  const [newApiKey, setNewApiKey] = useState("");
  const [newDefaultModel, setNewDefaultModel] = useState("");

  useEffect(() => {
    setLocalCatalog(normalizeCatalog(catalog));
  }, [catalog]);

  const handleChange = async (updatedCatalog: RuntimeCatalog) => {
    setLocalCatalog(updatedCatalog);
    if (onChange) {
      await onChange(updatedCatalog);
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
    if (!newExecutorLabel.trim()) return;

    const newExecutor: RuntimeExecutorConfig = {
      id: crypto.randomUUID(),
      label: newExecutorLabel.trim(),
      enabled: true,
      executor_type: newExecutorType,
      api_endpoint: newApiEndpoint.trim() || null,
      api_key: newApiKey.trim() || null,
      default_model: newDefaultModel.trim() || null,
      providers: [],
      default_provider_id: null,
    };

    const updatedCatalog = {
      ...localCatalog,
      executors: [...localCatalog.executors, newExecutor],
    };
    handleChange(updatedCatalog);

    // Reset form
    setNewExecutorLabel("");
    setNewExecutorType("claude");
    setNewApiEndpoint("");
    setNewApiKey("");
    setNewDefaultModel("");
    setAddingNew(false);
  };

  const cancelAddExecutor = () => {
    setNewExecutorLabel("");
    setNewExecutorType("claude");
    setNewApiEndpoint("");
    setNewApiKey("");
    setNewDefaultModel("");
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
                alert("Catalog is valid.");
              } else {
                alert("Validation failed: " + (result.error ?? "Unknown error"));
              }
            } catch (err) {
              alert("Validation failed: " + (err instanceof Error ? err.message : String(err)));
            }
          }}
          className="text-xs font-bold uppercase tracking-widest text-text-muted hover:text-foreground border border-border-subtle rounded-md px-3 py-1.5"
        >
          Validate
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
                api_key: exec.api_key,
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
                        onChange={() => setNewExecutorType("claude")}
                      />
                      {t("runtime.executor.claudeCli")}
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="newExecutorType"
                        value="codex"
                        checked={newExecutorType === "codex"}
                        onChange={() => setNewExecutorType("codex")}
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
    </div>
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
  const [testResult, setTestResult] = useState<{ success: boolean; latency_ms?: number; error?: string } | null>(null);

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
                "Test"
              )}
            </Button>
            {testResult && (
              <span className={cn("text-xs", testResult.success ? "text-green-500" : "text-destructive")}>
                {testResult.success
                  ? `${testResult.latency_ms}ms`
                  : testResult.error?.slice(0, 50)}
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
      </CardHeader>
      <CardContent className="space-y-4">
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
              placeholder={t("runtime.executor.keyPlaceholder")}
            />
          </div>
        </div>

        <div className="min-w-0 space-y-1">
          <label className="text-xs text-muted-foreground">{t("runtime.executor.defaultModel")}</label>
          <Input
            value={executor.default_model || ""}
            onChange={(e) => onUpdate({ default_model: e.target.value || null })}
            placeholder={t("runtime.executor.modelPlaceholder")}
          />
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
