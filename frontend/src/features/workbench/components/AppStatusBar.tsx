"use client";

import { useEffect, useMemo, useState } from "react";
import { useBackendStatus } from "@/hooks/useBackendStatus";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
import { getCodexCostStats, type CodexCostStats } from "@/lib/api/stats";
import { getEmbeddingStatus, type EmbeddingStatus } from "@/lib/api/knowledge";
import { formatTok } from "@/lib/format";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

/**
 * Always-visible bottom strip, mirroring the reference shot:
 *
 *   ● codex 0.1.0   backend localhost:9000 ✓   2 running · 1 awaiting        main · clean · ahead 3
 */
export function AppStatusBar() {
  const { status: backendStatus } = useBackendStatus();
  const { executionProcessesAll } = useExecutionProcessesContext();
  const [cost, setCost] = useState<CodexCostStats | null>(null);
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const c = await getCodexCostStats();
        if (!cancelled) setCost(c);
      } catch {
        // silent — if the endpoint fails we just don't show cost
      }
    }
    void tick();
    void getEmbeddingStatus()
      .then((e) => {
        if (!cancelled) setEmbedding(e);
      })
      .catch(() => undefined);
    const id = window.setInterval(tick, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const { running, awaiting } = useMemo(() => {
    let running = 0;
    let awaiting = 0;
    for (const p of executionProcessesAll ?? []) {
      const s = (p.status ?? "").toLowerCase();
      if (s === "running" || s === "in_progress") running += 1;
      else if (s === "awaiting_approval" || s === "awaiting" || s === "pending_review") awaiting += 1;
    }
    return { running, awaiting };
  }, [executionProcessesAll]);

  const backendLabel =
    backendStatus === "online"
      ? "backend localhost:9000 ✓"
      : backendStatus === "reconnecting"
        ? "backend reconnecting…"
        : "backend offline";
  const backendTone =
    backendStatus === "online"
      ? "text-text-muted"
      : backendStatus === "reconnecting"
        ? "text-status-awaiting"
        : "text-status-failed";

  return (
    <footer className="h-7 shrink-0 border-t border-border-subtle/80 bg-surface/90 backdrop-blur-sm flex items-center px-4 text-[11px] font-mono leading-none">
      <div className="flex items-center gap-4 text-text-muted">
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              "size-1.5 rounded-full",
              backendStatus === "online" && "bg-status-done",
              backendStatus === "reconnecting" && "bg-status-awaiting animate-pulse",
              backendStatus === "offline" && "bg-status-failed",
            )}
          />
          codex 0.1.0
        </span>
        <span className={backendTone}>{backendLabel}</span>
        {(running > 0 || awaiting > 0) && (
          <span>
            {running > 0 && <span className="text-status-running">{running} running</span>}
            {running > 0 && awaiting > 0 && <span className="text-text-muted"> · </span>}
            {awaiting > 0 && <span className="text-status-awaiting">{awaiting} awaiting</span>}
          </span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-3 text-text-muted">
        {embedding && (
          <button
            type="button"
            onClick={() => router.push("/knowledge")}
            title={
              embedding.enabled
                ? `Semantic: ${embedding.model ?? ""}`
                : "Semantic search disabled — click to manage"
            }
            className="flex items-center gap-1.5 hover:text-foreground transition-colors"
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                embedding.enabled ? "bg-status-done" : "bg-zinc-500",
              )}
            />
            knowledge {embedding.enabled ? "on" : "off"}
          </button>
        )}
        {cost && (cost.input_tokens > 0 || cost.output_tokens > 0) && (
          <span
            title={`Input ${cost.input_tokens.toLocaleString()} · Output ${cost.output_tokens.toLocaleString()}${cost.cache_read_tokens ? ` · Cache ${cost.cache_read_tokens.toLocaleString()}` : ""} (pricing: $${cost.pricing.input_per_m}/M in, $${cost.pricing.output_per_m}/M out)`}
            className="text-text-muted tabular-nums"
          >
            <span className="text-foreground">${cost.est_cost_usd.toFixed(3)}</span>
            <span className="mx-1">·</span>
            <span>{formatTok(cost.input_tokens + cost.output_tokens)} tok</span>
          </span>
        )}
      </div>
    </footer>
  );
}
