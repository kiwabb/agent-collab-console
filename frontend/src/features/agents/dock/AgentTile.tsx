"use client";

import { motion } from "framer-motion";
import type { Persona } from "./personas";
import type { RoleStatus } from "./useAgentStatus";
import { StatusBubble } from "./StatusBubble";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";

interface Props {
  persona: Persona;
  status: RoleStatus;
  isActiveSpeaker: boolean;
  onClick: () => void;
  /** Pixel size of the avatar circle. Default 64 (dock); use ~96 for canvas. */
  size?: number;
  /** Container width reserved per tile. Default 84 (dock). */
  containerWidth?: number;
}

/**
 * Single character "tile" in the bottom dock. Idle = subtle breathing,
 * active = lean forward + glow ring + typing dots.
 */
export function AgentTile({
  persona,
  status,
  isActiveSpeaker,
  onClick,
  size = 64,
  containerWidth = 84,
}: Props) {
  const { t } = useI18n();
  const isActive = status.mode === "active" || isActiveSpeaker;
  const isDone = status.mode === "done";
  const isFailed = status.mode === "failed";
  const emojiSize = Math.round(size * 0.44);
  const translatedName = t(persona.nameKey);

  return (
    <div className="relative flex flex-col items-center" style={{ minWidth: containerWidth }}>
      <StatusBubble persona={persona} status={status} isActiveSpeaker={isActiveSpeaker} />
      <motion.button
        type="button"
        onClick={onClick}
        layout
        data-density={isActive ? "agent-dock-active-tile" : "agent-dock-tile"}
        animate={{
          scale: isActive ? [1, 1.04, 1] : [1, 1.015, 1],
          rotate: isActive ? -3 : 0,
        }}
        transition={{
          scale: { duration: isActive ? 1.4 : 3.2, repeat: Infinity, ease: "easeInOut" },
          rotate: { duration: 0.4, ease: "easeOut" },
        }}
        whileHover={{ y: -3 }}
        className={cn(
          "relative rounded-full flex items-center justify-center",
          "leading-none select-none cursor-pointer",
          "bg-surface border-2 shadow",
          isActive && "shadow-xl",
          isActive && "motion-essential",
          isFailed && "bg-error/5",
          isDone && "bg-success/5",
        )}
        style={{
          width: size,
          height: size,
          fontSize: emojiSize,
          borderColor: isActive ? persona.color : "var(--border-subtle, #e5e7eb)",
          boxShadow: isActive
            ? `0 0 0 4px ${persona.color}33, 0 8px 24px ${persona.color}22`
            : undefined,
        }}
        aria-label={`${translatedName}: ${status.text || "idle"}`}
      >
        <span aria-hidden>{persona.emoji}</span>
        {/* Status dot */}
        {isActive && !isFailed && !isDone ? (
          <span
            data-density="agent-dock-active-status"
            className="motion-essential absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-surface bg-surface"
          >
            <AgentThinkingIndicator phase="dispatching" size={10} />
          </span>
        ) : (
          <span
            className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-surface"
            style={{
              background: isFailed
                ? "var(--error)"
                : isDone
                  ? "var(--success)"
                  : "var(--border-subtle, #cbd5e1)",
            }}
          />
        )}
        {/* Typing dots while active */}
        {isActive && !isFailed && !isDone && (
          <div className="absolute -top-2 left-1/2 -translate-x-1/2 flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="size-1 rounded-full"
                style={{ background: persona.color }}
                animate={{ opacity: [0.2, 1, 0.2], y: [0, -2, 0] }}
                transition={{
                  duration: 0.9,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: i * 0.18,
                }}
              />
            ))}
          </div>
        )}
      </motion.button>
      <div
        className={cn(
          "mt-1.5 text-[10px] font-semibold uppercase tracking-wide",
          isActive ? "text-foreground" : "text-text-muted",
        )}
      >
        {translatedName}
      </div>
    </div>
  );
}
