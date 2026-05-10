"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTheme, type ThemePreference } from "@/providers/ThemeProvider";
import { useI18n } from "@/providers/I18nProvider";
import { getRuntimeCatalog, updateRuntimeCatalog } from "@/lib/api";
import { RuntimeCatalogEditor } from "@/components/runtime/RuntimeCatalogEditor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Kbd } from "@/components/ui/kbd";
import { AutoSaveIndicator } from "@/components/ui/auto-save-indicator";
import type { SaveStatus } from "@/hooks/useAutoSave";
import {
  ChevronLeft,
  Moon,
  Sun,
  Monitor,
  Languages,
  Settings,
  Database,
  Palette,
  Check,
  Activity,
  AlertCircle
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Locale } from "@/lib/i18n";
import type { RuntimeCatalog } from "@/lib/types";

export function SettingsPage() {
  const router = useRouter();
  const { theme, setTheme } = useTheme();
  const { locale, setLocale, t } = useI18n();
  const [runtimeCatalog, setRuntimeCatalog] = useState<RuntimeCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    getRuntimeCatalog()
      .then(setRuntimeCatalog)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load runtime catalog"))
      .finally(() => setLoading(false));
  }, []);

  const themeOptions: { value: ThemePreference; label: string; icon: React.ReactNode }[] = [
    { value: "light", label: t("settings.theme.light"), icon: <Sun size={18} /> },
    { value: "dark", label: t("settings.theme.dark"), icon: <Moon size={18} /> },
    { value: "system", label: t("settings.theme.system"), icon: <Monitor size={18} /> },
  ];

  const localeOptions: { value: Locale; label: string }[] = [
    { value: "zh-CN", label: t("settings.language.zh") },
    { value: "en-US", label: t("settings.language.en") },
  ];

  return (
    <div className="flex flex-col h-screen bg-background font-sans overflow-hidden">
      {/* Topbar */}
      <header className="h-16 shrink-0 flex items-center justify-between px-8 border-b border-border-subtle bg-surface/80 backdrop-blur-xl z-50">
        <div className="flex items-center gap-8">
          <div 
            className="flex items-center gap-3 cursor-pointer hover:opacity-80 transition-opacity"
            onClick={() => router.push("/")}
          >
            <div className="size-8 rounded-xl bg-brand flex items-center justify-center shadow-lg shadow-brand/20">
              <Activity size={18} className="text-background" />
            </div>
            <span className="text-lg font-black tracking-tighter text-foreground">JACKMOUSE.AI</span>
          </div>

          <div className="h-4 w-px bg-border-subtle" />

          <div className="flex items-center gap-6">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => router.push("/")}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold text-text-muted hover:bg-surface-hover hover:text-foreground transition-all group"
                >
                  <ChevronLeft size={16} className="group-hover:-translate-x-0.5 transition-transform" />
                  {t("nav.home")}
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <span className="flex items-center gap-1.5">
                  {t("nav.home")}
                  <Kbd>H</Kbd>
                </span>
              </TooltipContent>
            </Tooltip>

            <div className="flex items-center gap-3">
              <div className="size-8 rounded-xl bg-brand/10 flex items-center justify-center shadow-inner">
                <Settings size={18} className="text-brand animate-spin-slow" />
              </div>
              <h1 className="text-[10px] font-black tracking-[0.2em] text-foreground uppercase opacity-80">
                {t("settings.title")}
              </h1>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <AutoSaveIndicator status={saveStatus} error={saveError} />
        </div>
      </header>

      {/* Main Content with Sidebar Layout */}
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
                              {option.value === 'zh-CN' ? '简体中文' : 'English (United States)'}
                            </p>
                          </div>
                          {locale === option.value && <div className="size-5 rounded-full bg-brand flex items-center justify-center animate-in zoom-in duration-300">
                            <Check size={12} className="text-background" />
                          </div>}
                        </button>
                      ))}
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
                              setSaveError(err instanceof Error ? err.message : "Save failed");
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
            </div>
          </main>
        </Tabs>
      </div>
    </div>
  );
}
