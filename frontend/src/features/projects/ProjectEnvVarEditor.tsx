"use client";

import { KeyRound, Plus, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/providers/I18nProvider";

import type { ProjectEnvVarDraft } from "./useProjectStartupConfig";

interface Props {
  envVars: ProjectEnvVarDraft[];
  savingEnvId: string | null;
  onAdd: () => void;
  onChange: (
    id: string,
    patch: Partial<Pick<ProjectEnvVarDraft, "name" | "value" | "secret">>,
  ) => void;
  onSave: (envVar: ProjectEnvVarDraft) => void;
  onDelete: (envVar: ProjectEnvVarDraft) => void;
}

export function ProjectEnvVarEditor({
  envVars,
  savingEnvId,
  onAdd,
  onChange,
  onSave,
  onDelete,
}: Props) {
  const { t } = useI18n();

  const sourceLabel = (source: string): string => {
    if (!source || source === "user") return t("envConfig.sourceUser");
    if (source === "agent") return t("envConfig.sourceAgent");
    if (source === "compose") return t("envConfig.sourceCompose");
    return source;
  };

  return (
    <section
      aria-labelledby="startup-env-heading"
      className="border-y border-border-subtle bg-surface"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
        <div>
          <h3 id="startup-env-heading" className="text-base font-semibold">
            {t("startupConfig.envTitle")}
          </h3>
          <p className="mt-1 text-sm text-text-muted">{t("envConfig.subtitle")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={onAdd} className="min-h-11 gap-2">
          <Plus size={15} />
          {t("envConfig.addVar")}
        </Button>
      </div>

      {envVars.length === 0 ? (
        <div className="px-5 py-10 text-center">
          <p className="text-sm text-text-muted">{t("startupConfig.envEmpty")}</p>
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {envVars.map((envVar) => {
            const saving = savingEnvId === envVar.id;
            const canRename = envVar.isNew || envVar.source === "user";
            return (
              <div
                key={envVar.id}
                className="grid gap-4 px-5 py-4 xl:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1fr)_140px_minmax(180px,1fr)_auto] xl:items-center"
              >
                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-text-muted xl:sr-only">
                    {t("envConfig.name")}
                  </span>
                  {canRename ? (
                    <Input
                      value={envVar.name}
                      onChange={(event) =>
                        onChange(envVar.id, {
                          name: event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_"),
                        })
                      }
                      placeholder="VAR_NAME"
                      className="min-h-11 font-mono text-sm"
                    />
                  ) : (
                    <code className="block break-all text-sm font-semibold">{envVar.name}</code>
                  )}
                </label>

                <label className="space-y-1.5">
                  <span className="text-xs font-medium text-text-muted xl:sr-only">
                    {t("envConfig.value")}
                  </span>
                  <Input
                    type={envVar.secret ? "password" : "text"}
                    value={envVar.value}
                    onChange={(event) => onChange(envVar.id, { value: event.target.value })}
                    placeholder={
                      envVar.secret && envVar.is_set
                        ? "••••••••"
                        : envVar.is_set
                          ? envVar.value
                          : t("envConfig.notSet")
                    }
                    className="min-h-11 font-mono text-sm"
                  />
                </label>

                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={envVar.secret}
                    onChange={(event) => onChange(envVar.id, { secret: event.target.checked })}
                    className="size-4 accent-current"
                  />
                  <KeyRound size={15} className="text-text-muted" />
                  {t("envConfig.secret")}
                </label>

                <div className="min-w-0">
                  <span className="text-xs font-medium text-text-muted xl:sr-only">
                    {t("envConfig.source")}
                  </span>
                  <p className="mt-1 break-words text-xs leading-5 text-text-muted xl:mt-0">
                    {sourceLabel(envVar.source)}
                  </p>
                </div>

                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onSave(envVar)}
                    disabled={saving || !envVar.dirty || !envVar.name.trim()}
                    className="min-h-11 gap-2"
                  >
                    <Save size={14} />
                    {saving ? t("projects.savingSetup") : t("envConfig.saveVar")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onDelete(envVar)}
                    disabled={saving}
                    aria-label={t("envConfig.deleteVar")}
                    title={t("envConfig.deleteVar")}
                    className="min-h-11 min-w-11 text-status-failed"
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
