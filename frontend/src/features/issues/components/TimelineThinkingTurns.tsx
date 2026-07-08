"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ConductorTurn } from "@/lib/api/conductors";
import { useI18n } from "@/providers/I18nProvider";
import { isRecord } from "@/lib/utils";

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

/** Best-effort human-readable summary of a single turn's payload. */
function readableTurn(turn: ConductorTurn): string {
  const payload = asRecord(turn.payload);
  if (turn.kind === "llm_response") {
    const content = payload["content"];
    if (Array.isArray(content)) {
      const lines: string[] = [];
      for (const block of content) {
        const b = asRecord(block);
        if (b["type"] === "text" && typeof b["text"] === "string" && b["text"].trim()) {
          lines.push(b["text"].trim());
        } else if (b["type"] === "tool_use") {
          lines.push(`→ ${String(b["name"] || "tool")}(${JSON.stringify(b["input"] ?? {})})`);
        }
      }
      if (lines.length) return lines.join("\n\n");
    }
  }
  if (turn.kind === "llm_request") {
    const count = payload["message_count"];
    return typeof count === "number" ? `LLM request · ${count} messages` : "LLM request";
  }
  return JSON.stringify(turn.payload, null, 2);
}

export function TimelineThinkingTurns({ turns }: { turns: ConductorTurn[] }) {
  const { t } = useI18n();
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
        {t("issue.command.thinking", { count: turns.length })}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {turns.map((turn) => (
            <pre
              key={turn.id}
              className="max-h-44 overflow-auto whitespace-pre-wrap rounded-xl border border-border-subtle bg-background p-3 text-[11px] leading-relaxed text-text-secondary"
            >
              {readableTurn(turn)}
            </pre>
          ))}
        </div>
      )}
    </div>
  );
}
