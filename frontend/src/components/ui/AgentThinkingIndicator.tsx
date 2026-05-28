"use client";

import { cn } from "@/lib/utils";

/**
 * Semantic, AI-themed "agent is working" indicator. Picks an animation that
 * matches the agent's current activity:
 *   - thinking / reasoning / awaiting_llm  → neural-pulse core
 *   - streaming / streaming_llm / text      → blinking caret
 *   - tool / dispatching / awaiting_subagent→ orbiting particle
 *   - paused                                → static pause glyph
 *   - working / idle / fallback             → cascading dots
 * Always carries `motion-essential` so it animates even under reduced motion.
 */
type Glyph = "neural" | "caret" | "orbit" | "paused" | "cascade";

const PHASE_TO_GLYPH: Record<string, Glyph> = {
  thinking: "neural",
  reasoning: "neural",
  awaiting_llm: "neural",
  streaming: "caret",
  streaming_llm: "caret",
  text: "caret",
  tool: "orbit",
  dispatching: "orbit",
  awaiting_subagent: "orbit",
  paused: "paused",
  idle: "cascade",
  working: "cascade",
};

interface Props {
  phase?: string;
  label?: string;
  size?: number;
  className?: string;
}

export function AgentThinkingIndicator({ phase = "working", label, size = 14, className }: Props) {
  const glyph = PHASE_TO_GLYPH[phase] ?? "cascade";
  return (
    <span className={cn("motion-essential inline-flex items-center gap-2", className)}>
      <GlyphMark glyph={glyph} size={size} />
      {label ? <span className="font-mono text-text-secondary">{label}</span> : null}
    </span>
  );
}

function GlyphMark({ glyph, size }: { glyph: Glyph; size: number }) {
  if (glyph === "caret") {
    return (
      <span
        aria-hidden
        className="inline-block w-px bg-brand animate-caret-blink"
        style={{ height: size }}
      />
    );
  }

  if (glyph === "paused") {
    return (
      <span aria-hidden className="inline-flex items-center gap-[3px]">
        <span className="w-[3px] rounded-sm bg-text-muted" style={{ height: size * 0.85 }} />
        <span className="w-[3px] rounded-sm bg-text-muted" style={{ height: size * 0.85 }} />
      </span>
    );
  }

  if (glyph === "cascade") {
    return (
      <span aria-hidden className="inline-flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-brand animate-dot-cascade"
            style={{ animationDelay: `${i * 0.16}s` }}
          />
        ))}
      </span>
    );
  }

  if (glyph === "orbit") {
    return (
      <span aria-hidden className="relative inline-block" style={{ width: size, height: size }}>
        <span className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand/50" />
        <span className="absolute inset-0 animate-orbit">
          <span className="absolute left-1/2 top-0 h-1 w-1 -translate-x-1/2 rounded-full bg-brand" />
        </span>
      </span>
    );
  }

  // neural (default for thinking)
  return (
    <span aria-hidden className="relative inline-block" style={{ width: size, height: size }}>
      <span className="absolute inset-0 rounded-full border border-brand/20" />
      <span className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand animate-neural-pulse" />
    </span>
  );
}
