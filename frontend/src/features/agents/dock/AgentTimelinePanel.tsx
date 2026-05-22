"use client";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { PERSONAS, type RoleId } from "./personas";
import type { HistoryEntry } from "./agentBus";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  open: boolean;
  role: RoleId | null;
  history: HistoryEntry[];
  onClose: () => void;
}

const KIND_COLOR: Record<NonNullable<HistoryEntry["kind"]>, string> = {
  status: "text-text-secondary",
  tool: "text-info",
  artifact: "text-success",
  done: "text-success",
  error: "text-error",
};

function relTime(ts: number, now: number): string {
  const delta = Math.max(0, now - ts);
  if (delta < 1000) return "just now";
  if (delta < 60_000) return `${Math.floor(delta / 1000)}s ago`;
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  return `${Math.floor(delta / 3_600_000)}h ago`;
}

export function AgentTimelinePanel({ open, role, history, onClose }: Props) {
  const { t } = useI18n();
  const persona = role ? PERSONAS[role] : null;
  const now = Date.now();
  const reversed = [...history].reverse();
  const translatedName = persona ? t(persona.nameKey) : "";
  const translatedBlurb = persona ? t(persona.blurbKey) : "";

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[420px] sm:w-[480px] flex flex-col">
        {persona && (
          <>
            <SheetHeader className="px-5 pt-4 pb-2 shrink-0">
              <SheetTitle className="flex items-center gap-3 text-lg">
                <span
                  className="w-10 h-10 rounded-full flex items-center justify-center text-2xl border-2"
                  style={{ borderColor: persona.color, background: `${persona.color}11` }}
                  aria-hidden
                >
                  {persona.emoji}
                </span>
                {translatedName}
              </SheetTitle>
              <SheetDescription className="text-xs text-text-muted">
                {translatedBlurb}
              </SheetDescription>
            </SheetHeader>

            <div className="flex-1 overflow-auto px-5 pb-5">
              <div className="text-[10px] font-black uppercase tracking-widest text-text-muted mb-3">
                Timeline · {history.length} entries
              </div>
              {reversed.length === 0 ? (
                <div className="text-sm text-text-muted py-6 text-center">
                  No activity yet. {translatedName} hasn&apos;t spoken.
                </div>
              ) : (
                <ol className="relative border-l border-border-subtle ml-2 space-y-3">
                  {reversed.map((e, i) => (
                    <li key={i} className="pl-4">
                      <span
                        className="absolute -left-1.5 w-3 h-3 rounded-full border-2 border-surface"
                        style={{ background: persona.color }}
                      />
                      <div className="flex items-baseline justify-between gap-2">
                        <span
                          className={cn(
                            "text-sm font-semibold",
                            e.kind ? KIND_COLOR[e.kind] : KIND_COLOR.status,
                          )}
                        >
                          {e.text}
                        </span>
                        <span className="text-[10px] text-text-muted shrink-0">
                          {relTime(e.ts, now)}
                        </span>
                      </div>
                      {e.detail && (
                        <div className="text-xs text-text-muted mt-0.5 font-mono whitespace-pre-wrap">
                          {e.detail}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
