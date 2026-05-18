"use client";

import { useEffect, useRef, useState } from "react";
import { Undo2, X } from "lucide-react";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

interface UndoBarProps {
  message: string;
  /** Seconds until auto-confirm; component disappears when this hits zero. */
  countdownSeconds: number;
  /** Called when the user clicks Undo. Should restore prior state. */
  onUndo: () => void | Promise<void>;
  /** Called when the timer expires without the user clicking Undo. */
  onExpire: () => void | Promise<void>;
  /** Manually dismiss without firing either callback. */
  onDismiss?: () => void;
}

/**
 * Bottom-center black bar with "Undo in Ns" countdown. Matches Gmail/Linear
 * pattern — destructive action lands optimistically, user has N seconds
 * to revert, otherwise it's finalized.
 */
export function UndoBar({ message, countdownSeconds, onUndo, onExpire, onDismiss }: UndoBarProps) {
  const { t } = useI18n();
  const [remaining, setRemaining] = useState(countdownSeconds);
  const expiredRef = useRef(false);

  useEffect(() => {
    const id = window.setInterval(() => {
      setRemaining((s) => {
        if (s <= 1) {
          window.clearInterval(id);
          if (!expiredRef.current) {
            expiredRef.current = true;
            void onExpire();
          }
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [onExpire]);

  if (remaining <= 0) return null;

  return (
    <div
      className={cn(
        "fixed bottom-6 left-1/2 -translate-x-1/2 z-[60]",
        "flex items-center gap-3 pl-4 pr-2 py-2 rounded-full",
        "bg-foreground text-background shadow-2xl ring-1 ring-foreground/20",
        "animate-in fade-in slide-in-from-bottom-2 duration-200",
      )}
      role="alert"
    >
      <span className="text-[13px] font-medium">{message}</span>
      <span className="text-[11px] tabular-nums text-background/60">
        {remaining}s
      </span>
      <button
        type="button"
        onClick={() => {
          expiredRef.current = true; // prevent expire firing
          void onUndo();
        }}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-semibold",
          "bg-brand text-black hover:bg-brand-strong transition-colors",
        )}
      >
        <Undo2 size={12} />
        {t("task.diffMerge.undo")}
      </button>
      {onDismiss && (
        <button
          type="button"
          onClick={() => {
            expiredRef.current = true;
            onDismiss();
          }}
          aria-label={t("task.diffMerge.dismiss")}
          className="size-7 rounded-full hover:bg-background/10 text-background/60 hover:text-background flex items-center justify-center transition-colors"
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}
