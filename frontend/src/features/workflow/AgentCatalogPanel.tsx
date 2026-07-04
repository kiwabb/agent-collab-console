"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Bot, Network, RefreshCcw, ShieldCheck, Sparkles } from "lucide-react";
import { listAgents } from "@/lib/api/agents";
import type { Agent } from "@/lib/types";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

type AgentTier = Agent["agent_tier"];
type AgentDisplay = { name: string; description: string | null };

const TIER_ORDER: AgentTier[] = ["managed", "specialist", "custom"];
const MANAGED_ROLE_KEYS = [
  "product_manager",
  "architect",
  "engineer",
  "engineer_frontend",
  "engineer_backend",
  "operations_engineer",
  "qa",
] as const;
const SPECIALIST_ROLE_KEYS = [
  "accessibility_reviewer",
  "api_contract_checker",
  "code_reviewer",
  "dependency_auditor",
  "doc_writer",
  "i18n_checker",
  "log_summarizer",
  "migration_planner",
  "performance_reviewer",
  "security_reviewer",
] as const;

function isManagedRoleKey(roleKey: string): roleKey is (typeof MANAGED_ROLE_KEYS)[number] {
  return (MANAGED_ROLE_KEYS as readonly string[]).includes(roleKey);
}

function isSpecialistRoleKey(roleKey: string): roleKey is (typeof SPECIALIST_ROLE_KEYS)[number] {
  return (SPECIALIST_ROLE_KEYS as readonly string[]).includes(roleKey);
}

export function AgentCatalogPanel() {
  const { t } = useI18n();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    setLoading(true);
    try {
      setAgents(await listAgents());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const grouped = useMemo(() => {
    return TIER_ORDER.reduce<Record<AgentTier, Agent[]>>((acc, tier) => {
      acc[tier] = agents.filter((agent) => agent.agent_tier === tier);
      return acc;
    }, { managed: [], specialist: [], custom: [] });
  }, [agents]);

  const tierCopy: Record<AgentTier, { title: string; description: string; icon: ReactNode; tone: string }> = {
    managed: {
      title: t("settings.agentTier.managed.title"),
      description: t("settings.agentTier.managed.desc"),
      icon: <Network size={16} />,
      tone: "text-brand bg-brand/10 border-brand/20",
    },
    specialist: {
      title: t("settings.agentTier.specialist.title"),
      description: t("settings.agentTier.specialist.desc"),
      icon: <ShieldCheck size={16} />,
      tone: "text-status-running bg-status-running/10 border-status-running/20",
    },
    custom: {
      title: t("settings.agentTier.custom.title"),
      description: t("settings.agentTier.custom.desc"),
      icon: <Sparkles size={16} />,
      tone: "text-status-passed bg-status-passed/10 border-status-passed/20",
    },
  };

  const getAgentDisplay = (agent: Agent): AgentDisplay => {
    if (isManagedRoleKey(agent.role_key)) {
      return {
        name: t(`settings.agentRole.managed.${agent.role_key}.name` as const),
        description: t(`settings.agentRole.managed.${agent.role_key}.desc` as const),
      };
    }
    if (agent.role_key.startsWith("specialist:")) {
      const specialistKey = agent.role_key.slice("specialist:".length);
      if (isSpecialistRoleKey(specialistKey)) {
        return {
          name: t(`settings.agentRole.specialist.${specialistKey}.name` as const),
          description: t(`settings.agentRole.specialist.${specialistKey}.desc` as const),
        };
      }
    }
    return {
      name: agent.name,
      description: agent.description ?? null,
    };
  };

  return (
    <Card className="w-full bg-surface-raised/50 border-border-subtle shadow-2xl shadow-black/5 overflow-hidden backdrop-blur-sm">
      <CardHeader className="border-b border-border-subtle/50 pb-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
              {t("settings.agents")}
            </CardTitle>
            <CardDescription className="text-xs font-medium mt-2 max-w-2xl">
              {t("settings.agentsDesc")}
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void reload()}
            disabled={loading}
            data-density={loading ? "agent-catalog-refresh-dispatch" : "agent-catalog-refresh"}
            className={cn("gap-2 rounded-xl", loading && "motion-essential")}
          >
            {loading ? <AgentThinkingIndicator phase="dispatching" size={14} /> : <RefreshCcw size={14} />}
            {t("settings.refresh")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-6">
        {error ? (
          <div className="rounded-2xl border border-error/25 bg-error/10 p-4 text-sm font-semibold text-error">
            {error}
          </div>
        ) : loading ? (
          <div
            data-density="agent-catalog-dispatch-loading"
            className="motion-essential relative flex items-center justify-center gap-3 overflow-hidden rounded-2xl border border-brand/25 bg-brand-muted/10 py-16 text-xs font-black uppercase tracking-[0.25em] text-brand"
          >
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
            />
            <AgentThinkingIndicator phase="dispatching" size={18} />
            {t("settings.loadingCatalog")}
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            {TIER_ORDER.map((tier) => {
              const meta = tierCopy[tier];
              return (
                <section
                  key={tier}
                  className="rounded-3xl border border-border-subtle bg-surface/60 overflow-hidden"
                >
                  <div className="p-4 border-b border-border-subtle bg-surface-raised/60">
                    <div className="flex items-center gap-3">
                      <div className={cn("size-9 rounded-xl border flex items-center justify-center", meta.tone)}>
                        {meta.icon}
                      </div>
                      <div className="min-w-0">
                        <h3 className="text-sm font-black tracking-tight">{meta.title}</h3>
                        <p className="text-[10px] text-text-muted leading-relaxed">{meta.description}</p>
                      </div>
                    </div>
                    <div className="mt-4 text-[10px] font-black uppercase tracking-[0.2em] text-text-muted">
                      {t("settings.agentCount", { count: grouped[tier].length })}
                    </div>
                  </div>

                  <div className="divide-y divide-border-subtle">
                    {grouped[tier].length === 0 ? (
                      <div className="p-6 text-center text-xs text-text-muted">
                        {t(`settings.agentTierEmpty.${tier}` as const)}
                      </div>
                    ) : grouped[tier].map((agent) => {
                      const display = getAgentDisplay(agent);
                      return (
                        <article key={agent.id} className="p-4 hover:bg-surface-hover transition-colors">
                          <div className="flex items-start gap-3">
                            <div className="mt-0.5 size-8 rounded-xl bg-surface-raised border border-border-subtle flex items-center justify-center text-text-muted">
                              <Bot size={14} />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <h4 className="text-[13px] font-bold truncate">{display.name}</h4>
                                {agent.is_builtin && (
                                  <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[9px] font-black uppercase tracking-widest text-brand">
                                    {t("settings.builtIn")}
                                  </span>
                                )}
                              </div>
                              <p className="mt-1 font-mono text-[10px] text-text-muted truncate">{agent.role_key}</p>
                              {display.description && (
                                <p className="mt-2 text-[11px] text-text-secondary leading-relaxed line-clamp-3">
                                  {display.description}
                                </p>
                              )}
                              <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-text-muted">
                                <span className="rounded-lg border border-border-subtle bg-surface-raised px-2 py-1 font-mono">
                                  {t("settings.agentMeta.executor")}: {agent.default_executor ?? t("settings.agentMeta.unset")}
                                </span>
                                <span className="rounded-lg border border-border-subtle bg-surface-raised px-2 py-1 font-mono">
                                  {t("settings.agentMeta.artifact")}: {agent.artifact_subdir ?? t("settings.agentMeta.none")}
                                </span>
                              </div>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
