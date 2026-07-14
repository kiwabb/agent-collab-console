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
      <div className={cn("min-h-full bg-background", className)}>
        <header className="border-b border-border-subtle bg-surface">
          <div
            className={cn(
              "mx-auto flex min-w-0 flex-wrap items-center gap-3 px-4 py-3.5 sm:gap-4 sm:px-6",
              maxWidthClassName,
            )}
          >
            {leading}
            <h1 className="min-w-0 flex-1 truncate text-[19px] font-semibold leading-tight">
              {title}
            </h1>
            {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
          </div>
        </header>
        <div
          className={cn("mx-auto px-4 py-4 sm:px-6 sm:py-6", maxWidthClassName, contentClassName)}
        >
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className={cn("min-h-full bg-background", className)}>
      <header className="border-b border-border-subtle bg-surface">
        <div className={cn("mx-auto px-4 pb-5 pt-6 sm:px-6 sm:pb-6 sm:pt-7", maxWidthClassName)}>
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
                <h1 className="truncate text-[28px] font-semibold leading-tight">{title}</h1>
                {description && (
                  <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-text-muted">
                    {description}
                  </p>
                )}
              </div>
            </div>
            {actions && (
              <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0">
                {actions}
              </div>
            )}
          </div>
        </div>
      </header>

      <div className={cn("mx-auto px-4 py-4 sm:px-6 sm:py-6", maxWidthClassName, contentClassName)}>
        {children}
      </div>
    </div>
  );
}
