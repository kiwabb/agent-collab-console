"use client";

import { useEffect, useState } from "react";

import { listAgents } from "@/lib/api";
import type { Agent } from "@/lib/types";

/**
 * PR1 placeholder for the Agent Library page.
 *
 * Reachable at /agents but intentionally not linked from the nav while the
 * Workflow DAG feature is still gated by WORKFLOW_DAG_ENABLED. PR4 replaces
 * this with a full CRUD UI + system-prompt editor.
 */
export function AgentLibraryPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((rows) => {
        if (!cancelled) setAgents(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex items-baseline gap-2">
        <h1 className="text-xl font-semibold">Agent Library</h1>
        <span className="text-xs text-muted-foreground">PR1 preview — DAG editor lands in PR4</span>
      </header>

      {loading && <div className="text-sm text-muted-foreground">Loading agents…</div>}
      {error && <div className="text-sm text-destructive">Failed to load: {error}</div>}

      {!loading && !error && (
        <table className="w-full border border-border text-sm">
          <thead className="bg-muted text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">role_key</th>
              <th className="px-3 py-2 font-medium">Built-in</th>
              <th className="px-3 py-2 font-medium">Replan on done</th>
              <th className="px-3 py-2 font-medium">Replan on fail</th>
              <th className="px-3 py-2 font-medium">Artifact dir</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-muted-foreground">
                  No agents found. Built-in agents are seeded on backend startup.
                </td>
              </tr>
            )}
            {agents.map((a) => (
              <tr key={a.id} className="border-t border-border">
                <td className="px-3 py-2">{a.name}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.role_key}</td>
                <td className="px-3 py-2">{a.is_builtin ? "yes" : "no"}</td>
                <td className="px-3 py-2">{a.triggers_replan_on_done ? "yes" : "no"}</td>
                <td className="px-3 py-2">{a.triggers_replan_on_fail ? "yes" : "no"}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.artifact_subdir ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
