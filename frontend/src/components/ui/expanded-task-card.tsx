"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence, type PanInfo } from "framer-motion";
import { cn } from "@/lib/utils";

type MotionDragEvent = MouseEvent | TouchEvent | PointerEvent;

interface ExpandableTaskCardProps {
  children: ReactNode;
  expandedContent: ReactNode;
  isExpanded: boolean;
  onToggle: () => void;
  className?: string;
}

export function ExpandableTaskCard({
  children,
  expandedContent,
  isExpanded,
  onToggle,
  className,
}: ExpandableTaskCardProps) {
  return (
    <div className={cn("relative", className)}>
      <motion.div
        layout
        className={cn(
          "rounded-2xl border transition-all duration-300 cursor-pointer",
          isExpanded
            ? "border-brand/40 bg-surface-raised shadow-lg shadow-brand/5"
            : "border-border-subtle bg-surface/20 hover:border-border-strong hover:bg-surface/40"
        )}
        onClick={onToggle}
      >
        {children}
      </motion.div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0, marginTop: 0 }}
            animate={{ height: "auto", opacity: 1, marginTop: 12 }}
            exit={{ height: 0, opacity: 0, marginTop: 0 }}
            transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
          >
            <div className="p-4 bg-surface/50 rounded-xl border border-border-subtle">
              {expandedContent}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface SwipeToDeleteProps {
  children: ReactNode;
  onDelete: () => void;
  enabled?: boolean;
  className?: string;
}

export function SwipeToDelete({
  children,
  onDelete,
  enabled = true,
  className,
}: SwipeToDeleteProps) {
  const [offset, setOffset] = useState(0);

  const handleDrag = (_: MotionDragEvent, info: PanInfo) => {
    if (!enabled) return;
    setOffset(info.offset.x);
  };

  const handleDragEnd = (_: MotionDragEvent, info: PanInfo) => {
    if (!enabled) return;
    if (info.offset.x < -100) {
      onDelete();
    }
    setOffset(0);
  };

  const backgroundOpacity = Math.min(Math.abs(offset) / 100, 1);
  const isDeleting = offset < -50;

  return (
    <div className={cn("relative overflow-hidden", className)}>
      {/* Delete indicator background */}
      <div
        className={cn(
          "absolute inset-0 flex items-center justify-end pr-6 rounded-2xl transition-opacity",
          offset < 0 ? "bg-error/20 opacity-100" : "opacity-0"
        )}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: backgroundOpacity, scale: 1 }}
          className="flex items-center gap-2 text-error"
        >
          <span className="text-xs font-bold uppercase tracking-widest">Delete</span>
          <motion.svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={cn(isDeleting && "animate-pulse")}
          >
            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
          </motion.svg>
        </motion.div>
      </div>

      {/* Swipeable content */}
      <motion.div
        drag={enabled ? "x" : false}
        dragConstraints={{ left: -150, right: 0 }}
        dragElastic={0.1}
        onDrag={handleDrag}
        onDragEnd={handleDragEnd}
        animate={{ x: Math.max(offset, -120) }}
        style={{ position: "relative", zIndex: 1 }}
      >
        {children}
      </motion.div>
    </div>
  );
}
