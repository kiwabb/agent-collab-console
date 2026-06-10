"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ExternalLink,
  GitBranch,
  Moon,
  Settings as SettingsIcon,
  Sun,
} from "lucide-react";
import { checkBackendHealth, getCodexCostStats } from "@/lib/api";
import { useTheme } from "@/providers/ThemeProvider";
import { cn } from "@/lib/utils";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";

/**
 * "Account" surface in the top-right of the header. Replaces the dead
 * UserAvatar with a real popover containing:
 *   - Version / backend reach info
 *   - Theme quick toggle
 *   - Cumulative cost meter
 *   - Settings shortcut + GitHub link
 *
 * No real auth yet — that lives in Stage 4 (auth + multi-user). This is the
 * lightweight surface until we have accounts.
 */
export function AccountPopover() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  const [tokens, setTokens] = useState<number | null>(null);
  const [costUsd, setCostUsd] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const { theme, setTheme, resolvedTheme } = useTheme();

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    void Promise.all([
      checkBackendHealth().catch(() => null),
      getCodexCostStats().catch(() => null),
    ])
      .then(([health, cost]) => {
        if (health && typeof health === "object" && "version" in health) {
          setVersion(String((health as { version?: string }).version ?? "0.0"));
        }
        if (cost) {
          setTokens(cost.input_tokens + cost.output_tokens);
          setCostUsd(cost.est_cost_usd);
        }
      })
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "size-7 rounded-full bg-surface-raised border border-border-subtle",
          "flex items-center justify-center text-[11px] font-semibold text-text-secondary",
          "hover:border-border-strong transition-colors",
        )}
        aria-label="Account"
      >
        Z
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-50 w-72 rounded-xl bg-popover shadow-2xl ring-1 ring-foreground/10 p-1.5">
          <div className="px-3 py-2.5 border-b border-border-subtle">
            <div className="text-[13px] font-semibold">Agent Collab Console</div>
            <div className="text-[10px] text-text-muted mt-0.5 font-mono">
              {loading ? (
                <span data-density="account-popover-version-tool" className="motion-essential inline-flex items-center gap-1">
                  <AgentThinkingIndicator phase="tool" size={10} /> loading
                </span>
              ) : version ? (
                `version ${version}`
              ) : (
                "backend unreachable"
              )}
            </div>
          </div>
          <div className="px-3 py-2 border-b border-border-subtle space-y-1">
            <div className="flex justify-between text-[11px] text-text-muted">
              <span>Tokens used</span>
              <span className="tabular-nums text-foreground">
                {tokens === null ? "—" : tokens.toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between text-[11px] text-text-muted">
              <span>Estimated cost</span>
              <span className="tabular-nums text-foreground">
                {costUsd === null ? "—" : `$${costUsd.toFixed(3)}`}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="w-full px-3 py-1.5 rounded-md text-[12px] flex items-center gap-2 hover:bg-surface-hover transition-colors"
          >
            {resolvedTheme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
            <span>Switch to {resolvedTheme === "dark" ? "light" : "dark"} theme</span>
          </button>
          <button
            type="button"
            onClick={() => {
              router.push("/settings");
              setOpen(false);
            }}
            className="w-full px-3 py-1.5 rounded-md text-[12px] flex items-center gap-2 hover:bg-surface-hover transition-colors"
          >
            <SettingsIcon size={13} />
            <span>Settings · runtime · prefs</span>
          </button>
          <a
            href="https://github.com/anthropics/claude-code/issues"
            target="_blank"
            rel="noreferrer"
            className="w-full px-3 py-1.5 rounded-md text-[12px] flex items-center gap-2 hover:bg-surface-hover transition-colors"
          >
            <GitBranch size={13} />
            <span className="flex-1 text-left">Report an issue</span>
            <ExternalLink size={10} className="text-text-muted" />
          </a>
        </div>
      )}
    </div>
  );
}
