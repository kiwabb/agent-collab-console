"use client";

import { useState, useEffect } from "react";
import { useTheme, type ThemePreference } from "@/providers/ThemeProvider";
import { usePreferences, type FontSize } from "@/providers/PreferencesProvider";
import { useI18n } from "@/providers/I18nProvider";
import { getRuntimeCatalog, updateRuntimeCatalog } from "@/lib/api";
import { RuntimeCatalogEditor } from "@/components/runtime/RuntimeCatalogEditor";
import { AgentCatalogPanel } from "@/features/workflow/AgentCatalogPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AutoSaveIndicator } from "@/components/ui/auto-save-indicator";
import type { SaveStatus } from "@/hooks/useAutoSave";
import {
  Moon,
  Sun,
  Monitor,
  Languages,
  Settings,
  Database,
  Palette,
  Check,
  AlertCircle,
  Type,
  Zap,
  LayoutGrid,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Locale } from "@/lib/i18n";
import type { RuntimeCatalog } from "@/lib/types";
import { PageFrame } from "@/features/workbench/components/PageFrame";

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { fontSize, reducedMotion, compactMode, setFontSize, setReducedMotion, setCompactMode } = usePreferences();
  const { locale, setLocale, t } = useI18n();
  const [runtimeCatalog, setRuntimeCatalog] = useState<RuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    getRuntimeCatalog()
      .then(setRuntimeCatalog)
      .catch((err) => setError(err instanceof Error ? err.message : t("settings.runtimeLoadFailed")))
      .finally(() => setLoading(false));
  }, [t]);

  const themeOptions: { value: ThemePreference; label: string; icon: React.ReactNode }[] = [
    { value: "light", label: t("settings.theme.light"), icon: <Sun size={18} /> },
    { value: "dark", label: t("settings.theme.dark"), icon: <Moon size={18} /> },
    { value: "system", label: t("settings.theme.system"), icon: <Monitor size={18} /> },
  ];

  const localeOptions: { value: Locale; label: string }[] = [
    { value: "zh-CN", label: t("settings.language.zh") },
    { value: "en-US", label: t("settings.language.en") },
  ];

  const fontSizeOptions: { value: FontSize; label: string }[] = [
    { value: "small", label: t("settings.fontSize.small") },
    { value: "medium", label: t("settings.fontSize.medium") },
    { value: "large", label: t("settings.fontSize.large") },
  ];

  return (
    <PageFrame
      eyebrow={t("settings.preferences")}
      title={t("settings.title")}
      description={t("settings.preferences")}
      maxWidthClassName="max-w-[1280px]"
      actions={<AutoSaveIndicator status={saveStatus} error={saveError} />}
      contentClassName="flex overflow-hidden"
    >
      <div className="flex-1 flex overflow-hidden">
        <Tabs defaultValue="general" className="flex-1 flex overflow-hidden">
          {/* Sidebar */}
          <aside className="w-72 shrink-0 border-r border-border-subtle bg-surface/30 p-6 flex flex-col gap-8">
            <div>
              <h2 className="px-4 text-[10px] font-black uppercase tracking-[0.25em] text-text-muted mb-4">
                {t("settings.preferences")}
              </h2>
              <TabsList className="flex flex-col h-auto bg-transparent p-0 gap-1">
                <TabsTrigger
                  value="general"
                  className="w-full flex items-center justify-start gap-3 px-4 py-3 rounded-xl text-xs font-bold transition-all data-[state=active]:bg-brand/10 data-[state=active]:text-brand hover:bg-surface-hover hover:text-foreground text-text-secondary group border border-transparent data-[state=active]:border-brand/20"
                >
                  <div className="size-8 rounded-lg bg-surface-raised flex items-center justify-center group-data-[state=active]:bg-brand/20 group-data-[state=active]:shadow-inner transition-colors">
                    <Palette size={14} />
                  </div>
                  {t("settings.general")}
                </TabsTrigger>
                <TabsTrigger
                  value="runtime"
                  className="w-full flex items-center justify-start gap-3 px-4 py-3 rounded-xl text-xs font-bold transition-all data-[state=active]:bg-brand/10 data-[state=active]:text-brand hover:bg-surface-hover hover:text-foreground text-text-secondary group border border-transparent data-[state=active]:border-brand/20"
                >
                  <div className="size-8 rounded-lg bg-surface-raised flex items-center justify-center group-data-[state=active]:bg-brand/20 group-data-[state=active]:shadow-inner transition-colors">
                    <Database size={14} />
                  </div>
                  {t("settings.runtime")}
                </TabsTrigger>
                <TabsTrigger
                  value="agents"
                  className="w-full flex items-center justify-start gap-3 px-4 py-3 rounded-xl text-xs font-bold transition-all data-[state=active]:bg-brand/10 data-[state=active]:text-brand hover:bg-surface-hover hover:text-foreground text-text-secondary group border border-transparent data-[state=active]:border-brand/20"
                >
                  <div className="size-8 rounded-lg bg-surface-raised flex items-center justify-center group-data-[state=active]:bg-brand/20 group-data-[state=active]:shadow-inner transition-colors">
                    <Bot size={14} />
                  </div>
                  {t("settings.agents")}
                </TabsTrigger>
              </TabsList>
            </div>

            <div className="mt-auto">
              <div className="p-4 rounded-2xl bg-gradient-to-br from-brand/10 to-transparent border border-brand/10">
                <p className="text-[10px] font-bold text-brand uppercase tracking-widest mb-1">{t("settings.generalStatus")}</p>
                <p className="text-[9px] text-text-muted leading-relaxed">{t("settings.generalStatusDesc")}</p>
              </div>
            </div>
          </aside>

          {/* Tab Content */}
          <main className="flex-1 overflow-y-auto no-scrollbar scroll-smooth bg-surface/10">
            <div className="w-full min-h-full">
              <TabsContent value="general" className="w-full p-8 mt-0 outline-none animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="mb-6">
                  <h2 className="text-2xl font-black tracking-tight text-foreground mb-1 italic">
                    {t("settings.appearance")}
                  </h2>
                  <p className="text-xs text-text-muted">{t("settings.appearanceDesc")}</p>
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-2 2xl:grid-cols-3 gap-6">
                  <Card className="bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                        {t("settings.theme")}
                      </CardTitle>
                      <CardDescription className="text-xs font-medium">
                        {t("settings.themeDesc")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {themeOptions.map((option) => (
                        <button
                          key={option.value}
                          onClick={() => setTheme(option.value)}
                          className={cn(
                            "w-full flex items-center gap-4 p-3 rounded-xl border transition-all text-left group",
                            theme === option.value
                              ? "bg-brand/5 border-brand/30 text-brand ring-1 ring-brand/20"
                              : "bg-surface/50 hover:bg-surface border-border-subtle text-text-secondary"
                          )}
                        >
                          <div className={cn(
                            "size-10 rounded-lg flex items-center justify-center transition-all",
                            theme === option.value ? "bg-brand/10 scale-110" : "bg-surface-raised group-hover:bg-surface-hover"
                          )}>
                            {option.icon}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-bold">{option.label}</p>
                            <p className="text-[10px] opacity-60 truncate">
                              {option.value === 'system' ? t("settings.followDevice") : t("settings.useMode", { mode: option.value })}
                            </p>
                          </div>
                          {theme === option.value && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                            <Check size={12} className="text-background" />
                          </div>}
                        </button>
                      ))}
                    </CardContent>
                  </Card>

                  <Card className="bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                        {t("settings.language")}
                      </CardTitle>
                      <CardDescription className="text-xs font-medium">
                        {t("settings.languageDesc")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {localeOptions.map((option) => (
                        <button
                          key={option.value}
                          onClick={() => setLocale(option.value)}
                          className={cn(
                            "w-full flex items-center gap-4 p-3 rounded-xl border transition-all text-left group",
                            locale === option.value
                              ? "bg-brand/5 border-brand/30 text-brand ring-1 ring-brand/20"
                              : "bg-surface/50 hover:bg-surface border-border-subtle text-text-secondary"
                          )}
                        >
                          <div className={cn(
                            "size-10 rounded-lg flex items-center justify-center transition-all",
                            locale === option.value ? "bg-brand/10 scale-110" : "bg-surface-raised group-hover:bg-surface-hover"
                          )}>
                            <Languages size={18} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-bold">{option.label}</p>
                            <p className="text-[10px] opacity-60 truncate">
                              {locale === option.value ? t("settings.language.zh") : t("settings.language.en")}
                            </p>
                          </div>
                          {locale === option.value && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                            <Check size={12} className="text-background" />
                          </div>}
                        </button>
                      ))}
                    </CardContent>
                  </Card>

                  <Card className="bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                        {t("settings.fontSize")}
                      </CardTitle>
                      <CardDescription className="text-xs font-medium">
                        {t("settings.fontSize")} / {t("settings.fontSize.medium")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {fontSizeOptions.map((option) => (
                        <button
                          key={option.value}
                          onClick={() => setFontSize(option.value)}
                          className={cn(
                            "w-full flex items-center gap-4 p-3 rounded-xl border transition-all text-left group",
                            fontSize === option.value
                              ? "bg-brand/5 border-brand/30 text-brand ring-1 ring-brand/20"
                              : "bg-surface/50 hover:bg-surface border-border-subtle text-text-secondary"
                          )}
                        >
                          <div className={cn(
                            "size-10 rounded-lg flex items-center justify-center transition-all",
                            fontSize === option.value ? "bg-brand/10 scale-110" : "bg-surface-raised group-hover:bg-surface-hover"
                          )}>
                            <Type size={18} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-bold">{option.label}</p>
                            <p className="text-[10px] opacity-60">{t(`settings.fontSize.${option.value}`)}</p>
                          </div>
                          {fontSize === option.value && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                            <Check size={12} className="text-background" />
                          </div>}
                        </button>
                      ))}
                    </CardContent>
                  </Card>

                  <Card className="bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                        {t("settings.reducedMotion")}
                      </CardTitle>
                      <CardDescription className="text-xs font-medium">
                        {t("settings.reducedMotionDesc")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <button
                        onClick={() => setReducedMotion(!reducedMotion)}
                        className={cn(
                          "w-full flex items-center gap-4 p-3 rounded-xl border transition-all text-left group",
                          reducedMotion
                            ? "bg-brand/5 border-brand/30 text-brand ring-1 ring-brand/20"
                            : "bg-surface/50 hover:bg-surface border-border-subtle text-text-secondary"
                        )}
                      >
                        <div className={cn(
                          "size-10 rounded-lg flex items-center justify-center transition-all",
                          reducedMotion ? "bg-brand/10 scale-110" : "bg-surface-raised group-hover:bg-surface-hover"
                        )}>
                          <Zap size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-bold">{t("settings.reducedMotion")}</p>
                          <p className="text-[10px] opacity-60">{reducedMotion ? t("settings.state.on") : t("settings.state.off")}</p>
                        </div>
                        {reducedMotion && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                          <Check size={12} className="text-background" />
                        </div>}
                      </button>
                    </CardContent>
                  </Card>

                  <Card className="bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                    <CardHeader className="pb-4">
                      <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                        {t("settings.compactMode")}
                      </CardTitle>
                      <CardDescription className="text-xs font-medium">
                        {t("settings.compactModeDesc")}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <button
                        onClick={() => setCompactMode(!compactMode)}
                        className={cn(
                          "w-full flex items-center gap-4 p-3 rounded-xl border transition-all text-left group",
                          compactMode
                            ? "bg-brand/5 border-brand/30 text-brand ring-1 ring-brand/20"
                            : "bg-surface/50 hover:bg-surface border-border-subtle text-text-secondary"
                        )}
                      >
                        <div className={cn(
                          "size-10 rounded-lg flex items-center justify-center transition-all",
                          compactMode ? "bg-brand/10 scale-110" : "bg-surface-raised group-hover:bg-surface-hover"
                        )}>
                          <LayoutGrid size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-bold">{t("settings.compactMode")}</p>
                          <p className="text-[10px] opacity-60">{compactMode ? t("settings.state.on") : t("settings.state.off")}</p>
                        </div>
                        {compactMode && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                          <Check size={12} className="text-background" />
                        </div>}
                      </button>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              <TabsContent value="runtime" className="w-full p-8 mt-0 outline-none animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="mb-6">
                  <h2 className="text-2xl font-black tracking-tight text-foreground mb-1 italic">
                    {t("settings.runtimeConfig")}
                  </h2>
                  <p className="text-xs text-text-muted">{t("settings.runtimeConfigDesc")}</p>
                </div>

                <Card className="w-full bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
                  <CardHeader className="border-b border-border-subtle/50 pb-4 mb-4">
                    <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
                      {t("settings.advancedConfig")}
                    </CardTitle>
                    <CardDescription className="text-xs font-medium">
                      {t("settings.advancedConfigDesc")}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="px-6">
                      {loading ? (
                        <div className="flex flex-col items-center justify-center py-20 gap-4">
                          <div className="size-12 border-4 border-brand/10 border-t-brand rounded-full animate-spin" />
                          <p className="text-[10px] font-black uppercase tracking-[0.3em] text-brand animate-pulse">{t("settings.syncingCatalog")}</p>
                        </div>
                      ) : error ? (
                        <div className="p-6 rounded-2xl bg-error/5 border border-error/20 text-center">
                          <AlertCircle size={24} className="mx-auto text-error mb-4 opacity-50" />
                          <p className="text-sm font-bold text-error mb-4">{error}</p>
                          <Button
                            variant="outline"
                            className="rounded-xl border-error/20 hover:bg-error/10 hover:text-error"
                            onClick={() => window.location.reload()}
                          >
                            {t("settings.retryConnection")}
                          </Button>
                        </div>
                      ) : runtimeCatalog && (
                        <RuntimeCatalogEditor
                          catalog={runtimeCatalog}
                          onChange={async (cat) => {
                            setSaveStatus("saving");
                            try {
                              await updateRuntimeCatalog(cat);
                              setRuntimeCatalog(cat);
                              setSaveStatus("saved");
                            } catch (err) {
                              setSaveError(err instanceof Error ? err.message : t("settings.saveFailed"));
                              setSaveStatus("error");
                            }
                          }}
                          className="pb-8"
                        />
                      )}
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="agents" className="w-full p-8 mt-0 outline-none animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="mb-6">
                  <h2 className="text-2xl font-black tracking-tight text-foreground mb-1 italic">
                    {t("settings.agents")}
                  </h2>
                  <p className="text-xs text-text-muted">
                    {t("settings.agentsDesc")}
                  </p>
                </div>
                <AgentCatalogPanel />
              </TabsContent>
            </div>
          </main>
        </Tabs>
      </div>
    </PageFrame>
  );
}
