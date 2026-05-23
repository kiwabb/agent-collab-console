"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ConductorTurn } from "@/lib/api";

export function TimelineThinkingTurns({ turns }: { turns: ConductorTurn[] }) {
  const [open, setOpen] = useState(false);
  if (turns.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((next) => !next)}
        className="inline-flex items-center gap-1 text-xs font-semibold text-text-muted hover:text-foreground"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        Thinking ({turns.length} turns)
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {turns.map((turn) => (
            <pre key={turn.id} className="max-h-44 overflow-auto rounded-xl border border-border-subtle bg-background p-3 text-[11px] leading-relaxed text-text-secondary">
              {JSON.stringify(turn.payload, null, 2)}
            </pre>
          ))}
        </div>
      )}
    </div>
  );
}
