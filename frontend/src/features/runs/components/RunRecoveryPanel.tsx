"use client";

import type { RecoveryAction } from "@/features/workbench/interaction/interactionState";

interface RunRecoveryPanelProps {
  actions: RecoveryAction[];
  onAction: (id: RecoveryAction["id"]) => void;
}

export function RunRecoveryPanel({
  actions,
  onAction,
}: RunRecoveryPanelProps) {
  if (actions.length === 0) return null;

  return (
    <section className="enterprise-card rounded-2xl p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-foreground">
          Recovery actions
        </h3>
        <p className="text-xs text-text-muted">
          Choose a safe next step for this run.
        </p>
      </div>
      <div className="grid gap-2">
        {actions.map((action) => (
          <button
            key={action.id}
            type="button"
            onClick={() => onAction(action.id)}
            className="rounded-xl border border-border-subtle bg-surface/70 px-3 py-2 text-left hover:border-brand/40 hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
          >
            <span className="block text-[12px] font-semibold text-foreground">
              {action.label}
            </span>
            <span className="block text-[11px] text-text-muted">
              {action.detail}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
