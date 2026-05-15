"use client";

import type { ReplanPending } from "@/lib/api";

interface Props {
  issueId: string;
  pending: ReplanPending;
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
}

/**
 * Renders the orchestrator's proposed DAG diff with Confirm / Reject buttons.
 *
 * The diff is intentionally read-only — finer-grained per-edge editing lives
 * in the WorkflowGraphEditor (PR4+). This is the safety gate users hit when
 * the brain wants to reshape the graph.
 */
export function ReplanDiffModal({ pending, busy, onConfirm, onReject }: Props) {
  const { diff, triggered_by_node_key, trigger_reason, rationale } = pending;
  const addedNodes = diff.added_nodes ?? [];
  const addedEdges = diff.added_edges ?? [];
  const removedKeys = diff.removed_node_keys ?? [];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card text-card-foreground shadow-xl">
        <header className="flex items-baseline justify-between border-b border-border px-5 py-3">
          <h2 className="text-lg font-semibold">Replan proposed</h2>
          <span className="text-xs text-muted-foreground">
            triggered by <code className="font-mono">{triggered_by_node_key}</code> ({trigger_reason})
          </span>
        </header>
        <div className="flex flex-col gap-3 px-5 py-4 text-sm">
          {rationale && (
            <p className="rounded border border-border bg-muted/30 px-3 py-2 text-xs">
              {rationale}
            </p>
          )}
          {addedNodes.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Add nodes</div>
              <ul className="ml-4 list-disc text-sm">
                {addedNodes.map((n) => (
                  <li key={n.node_key}>
                    <code className="font-mono">{n.node_key}</code>
                    {n.title && <span className="text-muted-foreground"> — {n.title}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {addedEdges.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Add edges</div>
              <ul className="ml-4 list-disc text-sm">
                {addedEdges.map((e, idx) => (
                  <li key={idx}>
                    <code className="font-mono">{e.from_node_key} → {e.to_node_key}</code>{" "}
                    <span className="text-xs text-muted-foreground">({e.edge_type})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {removedKeys.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Remove nodes</div>
              <ul className="ml-4 list-disc text-sm">
                {removedKeys.map((k) => (
                  <li key={k}><code className="font-mono">{k}</code></li>
                ))}
              </ul>
            </div>
          )}
          {addedNodes.length === 0 && addedEdges.length === 0 && removedKeys.length === 0 && (
            <p className="text-sm text-muted-foreground">No structural changes proposed.</p>
          )}
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            className="rounded border border-border bg-card px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            disabled={busy}
            onClick={onReject}
          >
            Reject
          </button>
          <button
            type="button"
            className="rounded border border-primary bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? "Applying…" : "Confirm"}
          </button>
        </footer>
      </div>
    </div>
  );
}
