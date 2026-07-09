"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getProjectEnvVars,
  putProjectEnvVars,
  deleteProjectEnvVar,
} from "@/lib/api/projects";
import type { ProjectEnvVarDisplay } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type UIVar = {
  name: string;
  value: string;
  secret: boolean;
  source: string;
  is_set: boolean;
  is_new: boolean;
};

export function ProjectEnvConfigPage({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [vars, setVars] = useState<UIVar[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getProjectEnvVars(projectId);
      const uiVars: UIVar[] = (data.env_vars || []).map((v: ProjectEnvVarDisplay) => ({
        name: v.name,
        value: v.value ?? "",
        secret: v.secret,
        source: v.source,
        is_set: v.is_set,
        is_new: false,
      }));
      setVars(uiVars);
    } catch (err) {
      addToast({
        type: "error",
        title: t("workspace.toast.loadFailed"),
        message: String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = () => {
    setVars((prev) => [
      ...prev,
      { name: "", value: "", secret: false, source: "user", is_set: false, is_new: true },
    ]);
  };

  const handleSave = async (v: UIVar) => {
    if (!v.name.trim()) return;
    setSaving(v.name);
    try {
      await putProjectEnvVars(projectId, {
        name: v.name.trim(),
        value: v.value,
        secret: v.secret,
        source: v.source || "user",
      });
      addToast({ type: "success", title: t("envConfig.saveSuccess") });
      // Reload to get updated is_set status
      await load();
    } catch (err) {
      addToast({ type: "error", title: String(err) });
    } finally {
      setSaving(null);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await deleteProjectEnvVar(projectId, name);
      addToast({ type: "success", title: t("envConfig.deleteSuccess") });
      setVars((prev) => prev.filter((v) => v.name !== name));
    } catch (err) {
      addToast({ type: "error", title: String(err) });
    }
  };

  const sourceLabel = (source: string): string => {
    if (!source || source === "user") return t("envConfig.sourceUser");
    if (source === "agent") return t("envConfig.sourceAgent");
    if (source === "compose") return t("envConfig.sourceCompose");
    return source;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        {t("workspace.loading")}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[960px] px-8 py-8">
      <div className="mb-8">
        <h2 className="text-xl font-bold tracking-tight">{t("envConfig.title")}</h2>
        <p className="mt-1 text-sm text-text-muted">{t("envConfig.subtitle")}</p>
      </div>

      {vars.length === 0 ? (
        <div className="rounded-lg border border-border-subtle bg-surface p-12 text-center">
          <p className="text-sm text-text-muted">{t("envConfig.emptyState")}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Table */}
          <div className="overflow-hidden rounded-lg border border-border-subtle">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-subtle bg-surface-secondary text-left text-xs font-medium text-text-muted uppercase tracking-wider">
                  <th className="px-4 py-3">{t("envConfig.name")}</th>
                  <th className="px-4 py-3">{t("envConfig.value")}</th>
                  <th className="px-4 py-3">{t("envConfig.secret")}</th>
                  <th className="px-4 py-3">{t("envConfig.source")}</th>
                  <th className="px-4 py-3 w-[80px]">{/* actions */}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {vars.map((v) => (
                  <tr key={v.name || v.is_new ? `new-${Math.random()}` : v.name} className="bg-surface">
                    <td className="px-4 py-3">
                      {v.is_new || v.source === "user" ? (
                        <Input
                          value={v.name}
                          onChange={(e) => {
                            setVars((prev) =>
                              prev.map((pv) =>
                                pv.name === v.name || (pv.is_new && pv === v)
                                  ? { ...pv, name: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") }
                                  : pv,
                              ),
                            );
                          }}
                          placeholder="VAR_NAME"
                          className="font-mono text-sm"
                        />
                      ) : (
                        <code className="text-sm font-semibold">{v.name}</code>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {v.secret ? (
                        <Input
                          type="password"
                          value={v.value}
                          onChange={(e) => {
                            setVars((prev) =>
                              prev.map((pv) =>
                                pv.name === v.name ? { ...pv, value: e.target.value } : pv,
                              ),
                            );
                          }}
                          placeholder={v.is_set ? "••••••••" : t("envConfig.notSet")}
                          className="font-mono text-sm"
                        />
                      ) : (
                        <Input
                          value={v.value}
                          onChange={(e) => {
                            setVars((prev) =>
                              prev.map((pv) =>
                                pv.name === v.name ? { ...pv, value: e.target.value } : pv,
                              ),
                            );
                          }}
                          placeholder={v.is_set ? v.value || "" : t("envConfig.notSet")}
                          className="font-mono text-sm"
                        />
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {v.secret ? (
                        <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-400">
                          🔒 {t("envConfig.secret")}
                        </span>
                      ) : (
                        <span className="text-xs text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-muted">
                      {sourceLabel(v.source)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleSave(v)}
                          disabled={saving === v.name || !v.name.trim()}
                        >
                          {saving === v.name ? "…" : t("envConfig.saveVar")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(v.name)}
                          disabled={!v.name.trim() || v.is_new}
                        >
                          {t("envConfig.deleteVar")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Add new var button */}
          <Button variant="outline" size="sm" onClick={handleAdd}>
            + {t("envConfig.addVar")}
          </Button>
        </div>
      )}
    </div>
  );
}