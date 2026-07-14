"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Braces,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  RefreshCcw,
  ServerCog,
  Wrench,
} from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getMcpCatalog, type McpCatalogResponse } from "@/lib/api/mcp";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { formatMcpTimestamp, mcpRiskTone, resolveSelectedMcpServer } from "./mcpManagement";

export function McpManagementPanel() {
  const { locale, t } = useI18n();
  const [catalog, setCatalog] = useState<McpCatalogResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getMcpCatalog();
      setCatalog(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("settings.mcp.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const selectedServer = useMemo(
    () => resolveSelectedMcpServer(catalog?.servers ?? [], selectedId),
    [catalog, selectedId],
  );
  const selectedCalls = useMemo(
    () =>
      selectedServer === null
        ? []
        : (catalog?.recent_calls.filter((call) => call.server_id === selectedServer.id) ?? []),
    [catalog, selectedServer],
  );
  const totalTools = catalog?.servers.reduce((sum, server) => sum + server.tool_count, 0) ?? 0;
  const activeSessions =
    catalog?.servers.reduce((sum, server) => sum + server.active_session_count, 0) ?? 0;

  return (
    <Card className="w-full rounded-none bg-transparent ring-0 hover:translate-y-0 hover:shadow-none">
      <CardHeader className="border-b border-border-subtle/50 pb-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-brand">
              {t("settings.mcp.registry")}
            </CardTitle>
            <CardDescription className="mt-2 max-w-2xl text-xs font-medium">
              {t("settings.mcp.description")}
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void reload()}
            disabled={loading}
            className={cn("min-h-11 gap-2 rounded-lg", loading && "motion-essential")}
          >
            {loading ? <AgentThinkingIndicator phase="tool" size={14} /> : <RefreshCcw size={14} />}
            {t("settings.refresh")}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        {error && (
          <div
            role="alert"
            className="flex items-start gap-3 border-b border-error/20 bg-error/10 px-5 py-3 text-xs font-semibold text-error"
          >
            <CircleAlert size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loading && catalog === null ? (
          <div className="motion-essential relative flex min-h-[420px] items-center justify-center gap-3 overflow-hidden text-xs font-black uppercase tracking-[0.2em] text-text-muted">
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool/70 to-transparent"
            />
            <AgentThinkingIndicator phase="tool" size={18} />
            {t("settings.mcp.loading")}
          </div>
        ) : catalog === null ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 p-8 text-center">
            <CircleAlert size={26} className="text-error" />
            <p className="text-sm font-bold text-foreground">{t("settings.mcp.unavailable")}</p>
            <Button variant="outline" onClick={() => void reload()} className="min-h-11 gap-2">
              <RefreshCcw size={14} />
              {t("settings.retryConnection")}
            </Button>
          </div>
        ) : catalog.servers.length === 0 ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 p-8 text-center">
            <ServerCog size={28} className="text-text-muted" />
            <p className="text-sm font-bold text-foreground">{t("settings.mcp.empty")}</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 divide-y divide-border-subtle border-b border-border-subtle sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              <Metric
                icon={<ServerCog size={15} />}
                label={t("settings.mcp.servers")}
                value={catalog.servers.length}
              />
              <Metric
                icon={<Wrench size={15} />}
                label={t("settings.mcp.tools")}
                value={totalTools}
              />
              <Metric
                icon={<Activity size={15} />}
                label={t("settings.mcp.activeSessions")}
                value={activeSessions}
              />
            </div>

            <div className="grid min-h-[560px] grid-cols-1 lg:grid-cols-[minmax(240px,0.72fr)_minmax(0,1.6fr)]">
              <nav
                aria-label={t("settings.mcp.servers")}
                className="border-b border-border-subtle bg-surface/30 lg:border-b-0 lg:border-r"
              >
                <div className="border-b border-border-subtle px-4 py-3 text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
                  {t("settings.mcp.servers")}
                </div>
                <div className="divide-y divide-border-subtle">
                  {catalog.servers.map((server) => {
                    const active = selectedServer?.id === server.id;
                    const available = server.availability === "available";
                    return (
                      <button
                        key={server.id}
                        type="button"
                        onClick={() => setSelectedId(server.id)}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex min-h-20 w-full items-start gap-3 px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-inset",
                          active ? "bg-brand/10" : "hover:bg-surface-hover",
                        )}
                      >
                        <span
                          className={cn(
                            "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border",
                            active
                              ? "border-brand/30 bg-brand/15 text-brand"
                              : "border-border-subtle bg-surface-raised text-text-muted",
                          )}
                        >
                          <ServerCog size={16} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-xs font-bold text-foreground">
                              {server.display_name}
                            </span>
                            <span
                              className={cn(
                                "size-2 shrink-0 rounded-full",
                                available ? "bg-status-passed" : "bg-error",
                              )}
                            />
                            <span className="sr-only">
                              {available
                                ? t("settings.mcp.available")
                                : t("settings.mcp.unavailable")}
                            </span>
                          </span>
                          <span className="mt-1 block truncate font-mono text-[10px] text-text-muted">
                            {server.id}
                          </span>
                          <span className="mt-2 block text-[10px] text-text-secondary">
                            {t("settings.mcp.toolCount", { count: server.tool_count })}
                          </span>
                        </span>
                        <ChevronRight
                          size={15}
                          className={cn("mt-2 shrink-0", active ? "text-brand" : "text-text-muted")}
                        />
                      </button>
                    );
                  })}
                </div>
              </nav>

              {selectedServer && (
                <section aria-labelledby="mcp-server-title" className="min-w-0">
                  <div className="border-b border-border-subtle px-5 py-5 sm:px-6">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 id="mcp-server-title" className="text-lg font-black text-foreground">
                            {selectedServer.display_name}
                          </h3>
                          <StatusBadge available={selectedServer.availability === "available"} />
                        </div>
                        <p className="mt-2 max-w-3xl text-xs leading-5 text-text-secondary">
                          {selectedServer.description}
                        </p>
                      </div>
                      <span className="shrink-0 rounded-lg border border-border-subtle bg-surface px-2.5 py-1.5 font-mono text-[10px] text-text-muted">
                        v{selectedServer.version}
                      </span>
                    </div>

                    <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                      <Meta label={t("settings.mcp.scope")} value={selectedServer.scope} />
                      <Meta label={t("settings.mcp.owner")} value={selectedServer.owner} />
                      <Meta label={t("settings.mcp.transport")} value={selectedServer.transport} />
                      <Meta
                        label={t("settings.mcp.protocol")}
                        value={selectedServer.protocol_version}
                      />
                    </dl>
                  </div>

                  <div className="border-b border-border-subtle">
                    <div className="flex items-center justify-between px-5 py-3 sm:px-6">
                      <h4 className="text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
                        {t("settings.mcp.tools")}
                      </h4>
                      <span className="text-[10px] font-semibold text-text-muted">
                        {t("settings.mcp.recentCalls", { count: selectedServer.recent_call_count })}
                      </span>
                    </div>
                    <div className="divide-y divide-border-subtle border-t border-border-subtle">
                      {selectedServer.tools.map((tool) => (
                        <details key={tool.id} className="group">
                          <summary className="flex min-h-16 cursor-pointer list-none items-start gap-3 px-5 py-4 transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-inset sm:px-6">
                            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border-subtle bg-surface text-text-muted">
                              <Wrench size={14} />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <code className="break-all text-xs font-bold text-foreground">
                                  {tool.id}
                                </code>
                                <span
                                  className={cn(
                                    "rounded-md border px-2 py-0.5 text-[9px] font-black uppercase",
                                    mcpRiskTone(tool.risk_level),
                                  )}
                                >
                                  {t(`settings.mcp.risk.${tool.risk_level}`)}
                                </span>
                              </span>
                              <span className="mt-1 block text-[11px] leading-5 text-text-secondary">
                                {tool.description}
                              </span>
                              <span className="mt-2 block text-[10px] text-text-muted">
                                {t("settings.mcp.recentCalls", { count: tool.recent_call_count })}
                                {tool.error_call_count > 0
                                  ? ` · ${t("settings.mcp.errors", { count: tool.error_call_count })}`
                                  : ""}
                              </span>
                            </span>
                            <ChevronRight
                              size={15}
                              className="mt-2 shrink-0 text-text-muted transition-transform group-open:rotate-90"
                            />
                          </summary>
                          <div className="border-t border-border-subtle bg-surface/50 px-5 py-4 sm:px-6">
                            <div className="mb-2 flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.16em] text-text-muted">
                              <Braces size={13} />
                              {t("settings.mcp.inputSchema")}
                            </div>
                            <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-background/70 p-4 font-mono text-[11px] leading-5 text-text-secondary">
                              {JSON.stringify(tool.input_schema, null, 2)}
                            </pre>
                          </div>
                        </details>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between px-5 py-3 sm:px-6">
                      <h4 className="text-[10px] font-black uppercase tracking-[0.18em] text-text-muted">
                        {t("settings.mcp.callHistory")}
                      </h4>
                      <span className="text-[10px] text-text-muted">
                        {t("settings.mcp.auditWindow", { count: catalog.audit_window_size })}
                      </span>
                    </div>
                    {selectedCalls.length === 0 ? (
                      <div className="border-t border-border-subtle px-5 py-10 text-center text-xs text-text-muted sm:px-6">
                        {t("settings.mcp.noCalls")}
                      </div>
                    ) : (
                      <div className="divide-y divide-border-subtle border-t border-border-subtle">
                        {selectedCalls.map((call) => {
                          const ok = call.status !== "error";
                          const timestamp = formatMcpTimestamp(call.created_at, locale);
                          return (
                            <div
                              key={call.id}
                              className="grid grid-cols-1 gap-2 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-6"
                            >
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  {ok ? (
                                    <CheckCircle2
                                      size={14}
                                      className="shrink-0 text-status-passed"
                                    />
                                  ) : (
                                    <CircleAlert size={14} className="shrink-0 text-error" />
                                  )}
                                  <code className="truncate text-[11px] font-bold text-foreground">
                                    {call.tool_id}
                                  </code>
                                  <span className="text-[10px] text-text-muted">
                                    {ok ? t("settings.mcp.callOk") : t("settings.mcp.callError")}
                                  </span>
                                </div>
                                {(call.task_id || call.scope_id) && (
                                  <p className="mt-1 truncate pl-[22px] font-mono text-[9px] text-text-muted">
                                    {call.task_id ?? call.scope_id}
                                  </p>
                                )}
                              </div>
                              <div className="flex items-center gap-3 pl-[22px] text-[10px] text-text-muted sm:pl-0">
                                {call.duration_ms !== null && (
                                  <span className="flex items-center gap-1 font-mono">
                                    <Activity size={12} />
                                    {call.duration_ms} ms
                                  </span>
                                )}
                                {timestamp && (
                                  <span className="flex items-center gap-1">
                                    <Clock3 size={12} />
                                    {timestamp}
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </section>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3 px-5 py-4">
      <span className="flex size-8 items-center justify-center rounded-lg border border-border-subtle bg-surface text-text-muted">
        {icon}
      </span>
      <div>
        <div className="font-mono text-lg font-black tabular-nums text-foreground">{value}</div>
        <div className="text-[10px] font-semibold text-text-muted">{label}</div>
      </div>
    </div>
  );
}

function StatusBadge({ available }: { available: boolean }) {
  const { t } = useI18n();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[9px] font-black uppercase",
        available
          ? "border-status-passed/25 bg-status-passed/10 text-status-passed"
          : "border-error/25 bg-error/10 text-error",
      )}
    >
      {available ? <CheckCircle2 size={11} /> : <CircleAlert size={11} />}
      {available ? t("settings.mcp.available") : t("settings.mcp.unavailable")}
    </span>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[9px] font-black uppercase tracking-[0.14em] text-text-muted">{label}</dt>
      <dd
        className="mt-1 truncate font-mono text-[11px] font-semibold text-text-secondary"
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
