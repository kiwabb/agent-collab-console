"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PageFrameProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  leading?: ReactNode;
  /** Compact single-row header: [leading] title … [actions]. Drops eyebrow/description and shrinks padding. */
  compact?: boolean;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  maxWidthClassName?: string;
}

export function PageFrame({
  eyebrow,
  title,
  description,
  actions,
  leading,
  compact = false,
  children,
  className,
  contentClassName,
  maxWidthClassName = "max-w-[1280px]",
}: PageFrameProps) {
  if (compact) {
    return (
      <div className={cn("min-h-full enterprise-page", className)}>
        <div className="relative overflow-hidden border-b border-border-subtle">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-90"
            style={{
              background:
                "radial-gradient(700px 200px at 10% -40%, rgba(230,149,82,0.16), transparent 60%), linear-gradient(120deg, rgba(255,255,255,0.04), transparent 42%)",
            }}
          />
          <div
            className={cn(
              "relative mx-auto flex items-center gap-3 px-4 py-3.5 sm:gap-4 sm:px-6",
              maxWidthClassName,
            )}
          >
            {leading}
            <h1 className="truncate text-[19px] font-semibold tracking-[-0.01em] leading-tight">
              {title}
            </h1>
            {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
          </div>
        </div>
        <div
          className={cn("mx-auto px-4 py-4 sm:px-6 sm:py-6", maxWidthClassName, contentClassName)}
        >
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className={cn("min-h-full enterprise-page", className)}>
      <div className="relative overflow-hidden border-b border-border-subtle">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(900px 300px at 12% -10%, rgba(230,149,82,0.22), transparent 60%), radial-gradient(760px 260px at 92% -12%, rgba(96,165,250,0.18), transparent 62%), linear-gradient(120deg, rgba(255,255,255,0.055), transparent 42%)",
          }}
        />
        <div
          aria-hidden
          className="agent-mesh-grid pointer-events-none absolute inset-0 opacity-[0.18]"
        />
        <div
          className={cn(
            "relative mx-auto px-4 pb-5 pt-6 sm:px-6 sm:pb-6 sm:pt-7",
            maxWidthClassName,
          )}
        >
          {leading && <div className="mb-4 flex items-center">{leading}</div>}
          <div className="flex flex-col items-start justify-between gap-4 lg:flex-row lg:items-end lg:gap-6">
            <div className="min-w-0">
              {eyebrow && (
                <div className="mb-3 flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.22em] text-text-muted">
                  <span className="agent-orb" aria-hidden />
                  <span>{eyebrow}</span>
                  <span
                    className="h-px w-10 bg-gradient-to-r from-brand/60 to-transparent"
                    aria-hidden
                  />
                </div>
              )}
              <div className="min-w-0">
                <h1 className="truncate text-[28px] font-semibold tracking-[-0.035em] leading-tight">
                  {title}
                </h1>
                {description && (
                  <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-text-muted">
                    {description}
                  </p>
                )}
              </div>
            </div>
            {actions && (
              <div className="flex w-full items-center gap-2 rounded-2xl border border-border-subtle bg-surface/55 p-1.5 shadow-[0_12px_34px_-30px_rgba(0,0,0,0.8)] backdrop-blur-sm lg:w-auto lg:shrink-0">
                {actions}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className={cn("mx-auto px-4 py-4 sm:px-6 sm:py-6", maxWidthClassName, contentClassName)}>
        {children}
      </div>
    </div>
  );
}
