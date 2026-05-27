"use client";

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface LoaderProps {
  className?: string;
  variant?: "inline" | "card" | "full";
  label?: string;
}

export function Loader({ className, variant = "card", label }: LoaderProps) {
  if (variant === "inline") {
    return (
      <div className={cn("inline-flex items-center gap-2", className)}>
        <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" />
        {label && <span className="text-xs text-text-muted font-medium">{label}</span>}
      </div>
    );
  }

  if (variant === "full") {
    return (
      <div
        className={cn(
          "absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/70 backdrop-blur-md transition-all duration-300",
          className
        )}
      >
        <div className="relative flex flex-col items-center">
          {/* Glowing background aura */}
          <div className="absolute -inset-10 rounded-full bg-brand/10 blur-3xl animate-pulse" />
          
          {/* Premium rotating double-ring spinner */}
          <div className="relative h-16 w-16">
            {/* Inner Ring */}
            <div className="absolute inset-0 rounded-full border-2 border-brand/20" />
            <div
              className="absolute inset-0 rounded-full border-2 border-t-brand border-r-brand animate-spin"
              style={{ animationDuration: "1s" }}
            />
            
            {/* Outer Ring */}
            <div className="absolute -inset-2 rounded-full border border-text-secondary/10" />
            <div
              className="absolute -inset-2 rounded-full border border-t-transparent border-b-brand/40 animate-spin"
              style={{ animationDuration: "2.5s", animationDirection: "reverse" }}
            />
          </div>

          {/* Loading text with shifting subtle opacity and elegant letters */}
          <div className="mt-6 flex flex-col items-center text-center">
            <span className="text-sm font-semibold tracking-wider text-text-primary uppercase animate-pulse">
              {label || "Loading"}
            </span>
            <span
              className="mt-1 text-[10px] text-text-muted font-mono tracking-widest uppercase animate-pulse"
              style={{ animationDuration: "1.5s" }}
            >
              please wait
            </span>
          </div>
        </div>
      </div>
    );
  }

  // "card" variant (default) - sleek, medium-sized loader inside lists, panels, tabs
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center p-8 min-h-[160px] rounded-xl bg-surface-raised/40 border border-border-subtle/50 relative overflow-hidden",
        className
      )}
    >
      {/* Ambient background glow */}
      <div className="absolute -right-16 -bottom-16 w-32 h-32 rounded-full bg-brand/5 blur-2xl pointer-events-none" />
      
      <div className="relative flex flex-col items-center gap-3">
        <div className="relative h-10 w-10">
          <div className="absolute inset-0 rounded-full border-[3px] border-surface-input" />
          <div className="absolute inset-0 rounded-full border-[3px] border-t-brand border-r-brand animate-spin" />
        </div>
        {label && (
          <span className="text-xs font-medium text-text-secondary tracking-wide animate-pulse">
            {label}
          </span>
        )}
      </div>
    </div>
  );
}
