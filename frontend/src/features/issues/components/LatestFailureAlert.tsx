"use client";

import { AlertTriangle, ExternalLink, ListTree } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { LatestFailure } from "../hooks/useLatestFailure";

interface Props {
  failure: LatestFailure | null;
  onJump: () => void;
  onOpenDetail: () => void;
}

export function LatestFailureAlert({ failure, onJump, onOpenDetail }: Props) {
  if (!failure) return null;
  return (
    <section className="rounded-2xl border border-status-failed/35 bg-status-failed/10 px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.2em] text-status-failed">
            <AlertTriangle size={15} />
            Latest failure · {failure.role} {failure.createdAt ? `@ ${formatTime(failure.createdAt)}` : ""}
          </div>
          <p className="truncate text-sm text-foreground">{failure.summary}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={onJump} className="gap-2 rounded-xl">
            <ListTree size={14} />
            Jump to timeline
          </Button>
          <Button size="sm" onClick={onOpenDetail} className="gap-2 rounded-xl bg-status-failed text-white hover:bg-status-failed/90">
            <ExternalLink size={14} />
            Full output
          </Button>
        </div>
      </div>
    </section>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
