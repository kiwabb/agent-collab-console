"use client";

import Link from "next/link";
import { Info, Play, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { IssueNextAction } from "@/features/workbench/interaction/interactionState";

export function IssueActionStrip({
  action,
  onPrimary,
}: {
  action: IssueNextAction;
  onPrimary?: () => void;
}) {
  return (
    <section className="enterprise-panel rounded-3xl px-4 py-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-9 items-center justify-center rounded-2xl bg-brand/10 text-brand">
            {action.id === "review_qa" ? <ShieldCheck size={17} /> : <Play size={17} />}
          </span>
          <div>
            <div className="text-sm font-semibold text-foreground">{action.label}</div>
            <div className="mt-0.5 text-xs text-text-muted">
              {action.disabledReason || action.detail}
            </div>
          </div>
        </div>
        {action.href ? (
          <Link
            href={action.href}
            className="inline-flex h-8 items-center justify-center rounded-md bg-brand px-3 text-sm font-medium text-black hover:bg-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
          >
            Open
          </Link>
        ) : (
          <Button
            size="sm"
            disabled={!action.enabled}
            onClick={onPrimary}
            className="bg-brand text-black hover:bg-brand-strong disabled:opacity-40"
          >
            {action.enabled ? "Continue" : "Blocked"}
          </Button>
        )}
      </div>
      {action.disabledReason && (
        <div className="mt-3 flex items-start gap-2 rounded-2xl border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          <span>{action.disabledReason}</span>
        </div>
      )}
    </section>
  );
}
