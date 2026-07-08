"use client";

import { cn } from "@/lib/utils";

interface LoaderProps {
  className?: string;
  variant?: "inline" | "card" | "full";
  label?: string;
}

/** Three brand dots cascading — used as a "thinking/working" affordance under labels. */
function CascadeDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-brand/60 animate-dot-cascade"
          style={{ animationDelay: `${i * 0.16}s` }}
        />
      ))}
    </span>
  );
}

/**
 * AI/agent-themed loaders. Visual language: a glowing "core" (neural-pulse) with
 * particles in orbit, an ambient synapse-glow halo, and cascading dots for labels.
 * Every variant carries `motion-essential` so it keeps animating even when the
 * user has reduced motion enabled (loaders are essential feedback, not decoration).
 */
export function Loader({ className, variant = "card", label }: LoaderProps) {
  if (variant === "inline") {
    return (
      <div className={cn("motion-essential inline-flex items-center gap-2", className)}>
        <span className="relative inline-block h-3.5 w-3.5">
          <span className="absolute inset-0 animate-orbit">
            <span className="absolute left-1/2 top-0 h-1 w-1 -translate-x-1/2 rounded-full bg-brand" />
          </span>
          <span className="absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand/50 animate-neural-pulse" />
        </span>
        {label && <span className="text-xs text-text-muted font-medium">{label}</span>}
      </div>
    );
  }

  if (variant === "full") {
    return (
      <div
        className={cn(
          "motion-essential absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/70 backdrop-blur-md",
          className,
        )}
      >
        <div className="relative flex flex-col items-center">
          {/* Ambient aura — breathing synapse glow */}
          <div className="absolute -inset-10 rounded-full bg-brand/10 blur-3xl animate-synapse-glow" />

          {/* Orbit system: a pulsing core with two particles in orbit */}
          <div className="relative h-16 w-16">
            <div className="absolute inset-0 rounded-full border border-brand/15" />
            <div className="absolute inset-2 rounded-full border border-brand/10" />
            {/* Core */}
            <div className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand animate-neural-pulse shadow-[0_0_14px_var(--color-brand)]" />
            {/* Outer particle */}
            <div className="absolute inset-0 animate-orbit">
              <span className="absolute left-1/2 top-0 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-brand shadow-[0_0_8px_var(--color-brand)]" />
            </div>
            {/* Inner particle, reversed */}
            <div
              className="absolute inset-2.5 animate-orbit"
              style={{ animationDirection: "reverse" }}
            >
              <span className="absolute left-1/2 top-0 h-1 w-1 -translate-x-1/2 rounded-full bg-brand/70" />
            </div>
          </div>

          {/* Label + cascade dots */}
          <div className="mt-6 flex flex-col items-center gap-2 text-center">
            <span className="text-sm font-semibold tracking-wider text-text-primary uppercase">
              {label || "Loading"}
            </span>
            <CascadeDots />
          </div>
        </div>
      </div>
    );
  }

  // "card" variant (default) — panels, tabs, lists
  return (
    <div
      className={cn(
        "motion-essential flex flex-col items-center justify-center p-8 min-h-[160px] rounded-xl bg-surface-raised/40 border border-border-subtle/50 relative overflow-hidden",
        className,
      )}
    >
      {/* Ambient background glow */}
      <div className="absolute -right-16 -bottom-16 w-32 h-32 rounded-full bg-brand/5 blur-2xl pointer-events-none animate-synapse-glow" />

      <div className="relative flex flex-col items-center gap-3">
        <div className="relative h-10 w-10">
          <div className="absolute inset-0 rounded-full border border-brand/15" />
          {/* Core */}
          <div className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand animate-neural-pulse" />
          {/* Orbiting particle */}
          <div className="absolute inset-0 animate-orbit">
            <span className="absolute left-1/2 top-0 h-1.5 w-1.5 -translate-x-1/2 rounded-full bg-brand shadow-[0_0_6px_var(--color-brand)]" />
          </div>
        </div>
        {label && (
          <span className="flex items-center gap-1.5 text-xs font-medium text-text-secondary tracking-wide">
            {label}
            <CascadeDots className="gap-0.5 [&>span]:h-1 [&>span]:w-1" />
          </span>
        )}
      </div>
    </div>
  );
}
