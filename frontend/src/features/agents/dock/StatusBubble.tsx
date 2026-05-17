"use client";

import { motion, AnimatePresence } from "framer-motion";
import type { Persona } from "./personas";
import type { RoleStatus } from "./useAgentStatus";
import { cn } from "@/lib/utils";

interface Props {
  persona: Persona;
  status: RoleStatus;
  /** When true, render with the larger "active speaker" style. */
  isActiveSpeaker: boolean;
}

const TONE_CLASS: Record<RoleStatus["tone"], string> = {
  neutral: "border-border-subtle text-text-secondary",
  info: "border-info/40 text-info",
  success: "border-success/40 text-success",
  warning: "border-warning/40 text-warning",
  error: "border-error/50 text-error",
};

/**
 * Speech bubble that sits above an AgentTile. Springs in / out and shows
 * one short line of status + optional second line of detail.
 */
export function StatusBubble({ persona, status, isActiveSpeaker }: Props) {
  const show = !!status.text;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key={`bubble-${persona.id}-${status.text}-${status.detail ?? ""}`}
          layout
          initial={{ opacity: 0, scale: 0.6, y: 6 }}
          animate={{ opacity: 1, scale: isActiveSpeaker ? 1 : 0.92, y: 0 }}
          exit={{ opacity: 0, scale: 0.6, y: 6 }}
          transition={{ type: "spring", stiffness: 320, damping: 22, mass: 0.6 }}
          className={cn(
            "absolute bottom-full left-1/2 -translate-x-1/2 mb-2",
            "min-w-[160px] max-w-[280px] px-3 py-2 rounded-2xl",
            "bg-surface/95 backdrop-blur border shadow-lg",
            TONE_CLASS[status.tone],
            isActiveSpeaker ? "scale-100" : "scale-90 opacity-90",
          )}
          style={{ borderColor: status.tone === "neutral" ? undefined : undefined }}
        >
          <div className="text-[12px] font-semibold leading-snug whitespace-nowrap overflow-hidden text-ellipsis">
            {status.text}
          </div>
          {status.detail && (
            <div
              className="text-[10px] mt-0.5 text-text-muted leading-snug overflow-hidden"
              style={{
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
              title={status.detail}
            >
              {status.detail}
            </div>
          )}
          {/* Tail */}
          <div
            className={cn(
              "absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-3 h-3 rotate-45",
              "bg-surface/95 border-r border-b",
              TONE_CLASS[status.tone],
            )}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
