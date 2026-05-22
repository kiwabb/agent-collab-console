"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PageFrameProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
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
  children,
  className,
  contentClassName,
  maxWidthClassName = "max-w-[1280px]",
}: PageFrameProps) {
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
        <div aria-hidden className="agent-mesh-grid pointer-events-none absolute inset-0 opacity-[0.18]" />
        <div className={cn("relative px-6 pt-7 pb-6 mx-auto", maxWidthClassName)}>
          <div className="flex items-end justify-between gap-6">
            <div className="min-w-0">
              {eyebrow && (
                <div className="mb-3 flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.22em] text-text-muted">
                  <span className="agent-orb" aria-hidden />
                  <span>{eyebrow}</span>
                  <span className="h-px w-10 bg-gradient-to-r from-brand/60 to-transparent" aria-hidden />
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
              <div className="flex shrink-0 items-center gap-2 rounded-2xl border border-border-subtle bg-surface/55 p-1.5 shadow-[0_12px_34px_-30px_rgba(0,0,0,0.8)] backdrop-blur-sm">
                {actions}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className={cn("px-6 py-6 mx-auto", maxWidthClassName, contentClassName)}>
        {children}
      </div>
    </div>
  );
}
