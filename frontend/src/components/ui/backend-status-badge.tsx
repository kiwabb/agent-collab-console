"use client";

import { useBackendStatus } from "@/hooks/useBackendStatus";
import { cn } from "@/lib/utils";
import { RefreshCw } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function BackendStatusBadge() {
  const { status, retry } = useBackendStatus();

  if (status === "online") return null;

  if (status === "reconnecting") {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-warning/10 border border-warning/30 text-warning">
            <div className="size-2 rounded-full bg-warning animate-pulse" />
            <span className="text-[10px] font-black uppercase tracking-widest">Reconnecting</span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          Realtime WebSocket dropped — using polling fallback. HTTP is OK.
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void retry()}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1 rounded-full",
        "bg-error/10 border border-error/30 text-error",
        "hover:bg-error/20 transition-colors",
      )}
    >
      <div className="size-2 rounded-full bg-error" />
      <span className="text-[10px] font-black uppercase tracking-widest">Backend offline</span>
      <RefreshCw size={11} className="ml-0.5" />
    </button>
  );
}
