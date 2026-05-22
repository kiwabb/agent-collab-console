"use client";

import type { ReactNode } from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface InteractionEmptyStateProps {
  tone?: "empty" | "loading" | "error";
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function InteractionEmptyState({
  tone = "empty",
  title,
  description,
  action,
}: InteractionEmptyStateProps) {
  const Icon =
    tone === "loading" ? Loader2 : tone === "error" ? AlertCircle : Inbox;

  return (
    <div
      className={cn(
        "enterprise-card flex min-h-[220px] flex-col items-center justify-center rounded-3xl px-6 py-10 text-center",
        tone === "error" && "border-error/30",
      )}
    >
      <div
        className={cn(
          "mb-4 flex size-12 items-center justify-center rounded-2xl border",
          tone === "error"
            ? "border-error/30 bg-error/10 text-error"
            : "border-border-subtle bg-surface-input text-text-muted",
        )}
      >
        <Icon className={cn("size-5", tone === "loading" && "animate-spin")} />
      </div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {description && (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function EmptyStateAction(props: React.ComponentProps<typeof Button>) {
  return (
    <Button
      size="sm"
      className="bg-brand text-black hover:bg-brand-strong"
      {...props}
    />
  );
}
