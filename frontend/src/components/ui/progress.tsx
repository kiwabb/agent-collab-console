"use client";

import { cn } from "@/lib/utils";

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  showLabel?: boolean;
  label?: string;
}

export function ProgressBar({
  value,
  max = 100,
  className,
  showLabel = false,
  label,
}: ProgressBarProps) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="flex-1 h-1.5 rounded-full bg-surface-input overflow-hidden">
        <div
          className="h-full rounded-full bg-brand transition-all duration-300 ease-out"
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-[10px] font-bold text-text-muted min-w-[3rem] text-right">
          {label || `${Math.round(percentage)}%`}
        </span>
      )}
    </div>
  );
}

interface LoadingOverlayProps {
  isLoading: boolean;
  progress?: number;
  message?: string;
  children: React.ReactNode;
}

export function LoadingOverlay({ isLoading, progress, message, children }: LoadingOverlayProps) {
  return (
    <div className="relative">
      {children}
      {isLoading && (
        <div className="absolute inset-0 bg-surface/60 backdrop-blur-sm rounded-xl flex flex-col items-center justify-center gap-4 z-50 animate-in fade-in duration-200">
          {progress !== undefined ? (
            <>
              <ProgressBar value={progress} showLabel className="w-48" />
              {message && <p className="text-xs font-medium text-text-secondary">{message}</p>}
            </>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex gap-1">
                <div className="size-1.5 bg-brand rounded-full animate-bounce [animation-delay:-0.3s]" />
                <div className="size-1.5 bg-brand rounded-full animate-bounce [animation-delay:-0.15s]" />
                <div className="size-1.5 bg-brand rounded-full animate-bounce" />
              </div>
              {message && <p className="text-xs font-medium text-text-secondary">{message}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
