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

interface RuntimeCatalogEditorProps {
  catalog: RuntimeCatalog;
  onSave: (catalog: RuntimeCatalog) => Promise<void>;
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
  onSave,
  className,
}: RuntimeCatalogEditorProps) {
  const { t } = useI18n();
  const [localCatalog, setLocalCatalog] = useState<RuntimeCatalog>(() => normalizeCatalog(catalog));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingNew, setAddingNew] = useState(false);
  const [newExecutorLabel, setNewExecutorLabel] = useState("");
  const [newExecutorType, setNewExecutorType] = useState<"claude" | "codex">("claude");
  const [newApiEndpoint, setNewApiEndpoint] = useState("");
  const [newApiKey, setNewApiKey] = useState("");
  const [newDefaultModel, setNewDefaultModel] = useState("");

  useEffect(() => {
    setLocalCatalog(normalizeCatalog(catalog));
  }, [catalog]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(localCatalog);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const updateExecutor = (index: number, updates: Partial<RuntimeExecutorConfig>) => {
    setLocalCatalog((prev) => ({
      ...prev,
      executors: prev.executors.map((executor, executorIndex) =>
        executorIndex === index ? { ...executor, ...updates } : executor
      ),
    }));
  };

  const removeExecutor = (index: number) => {
    setLocalCatalog((prev) => ({
      ...prev,
      executors: prev.executors.filter((_, executorIndex) => executorIndex !== index),
    }));
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

    setLocalCatalog((prev) => ({
      ...prev,
      executors: [...prev.executors, newExecutor],
    }));

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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t("runtime.configure.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t("runtime.configure.desc")}
          </p>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? t("runtime.configure.saving") : t("runtime.configure.save")}
        </Button>
      </div>

      {error && (
        <div className="rounded-lg bg-destructive/10 text-destructive p-3 text-sm">{t("runtime.configure.error")}</div>
      )}

      <div className="space-y-4">
        {localCatalog.executors.map((executor, executorIndex) => (
          <ExecutorCard
            key={executor.id}
            executor={executor}
            executorIndex={executorIndex}
            onUpdate={(updates) => updateExecutor(executorIndex, updates)}
            onRemove={() => removeExecutor(executorIndex)}
            onToggleEnabled={() => toggleExecutorEnabled(executorIndex)}
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
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

function ExecutorCard({
  executor,
  onUpdate,
  onRemove,
  onToggleEnabled,
  t,
}: ExecutorCardProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

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

        <details>
          <summary
            className="text-xs text-muted-foreground cursor-pointer hover:text-foreground"
            onClick={(e) => {
              e.preventDefault();
              setShowAdvanced(!showAdvanced);
            }}
          >
            {showAdvanced ? "▼" : "▶"} {t("runtime.executor.advanced")}
          </summary>
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
        </details>
      </CardContent>
    </Card>
  );
}
