"use client";

import { useRef, useState, useCallback, type ReactNode } from "react";
import { motion, useMotionValue, useTransform, type PanInfo } from "framer-motion";
import { cn } from "@/lib/utils";

type MotionDragEvent = MouseEvent | TouchEvent | PointerEvent;

interface SwipeableCardProps {
  children: ReactNode;
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  onSwipeUp?: () => void;
  onSwipeDown?: () => void;
  leftThreshold?: number;
  rightThreshold?: number;
  upThreshold?: number;
  downThreshold?: number;
  leftContent?: ReactNode;
  rightContent?: ReactNode;
  upContent?: ReactNode;
  downContent?: ReactNode;
  className?: string;
  enabled?: boolean;
}

export function SwipeableCard({
  children,
  onSwipeLeft,
  onSwipeRight,
  onSwipeUp,
  onSwipeDown,
  leftThreshold = 100,
  rightThreshold = 100,
  upThreshold = 80,
  downThreshold = 80,
  leftContent,
  rightContent,
  upContent,
  downContent,
  className,
  enabled = true,
}: SwipeableCardProps) {
  const constraintsRef = useRef(null);
  const [isSwiping, setIsSwiping] = useState(false);
  const [direction, setDirection] = useState<"left" | "right" | "up" | "down" | null>(null);

  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const rotate = useTransform(x, [-200, 200], [-15, 15]);

  const handleDragEnd = useCallback(
    (_: MotionDragEvent, info: PanInfo) => {
      setIsSwiping(false);
      const tx = info.offset.x;
      const ty = info.offset.y;

      if (direction === "left" && tx < -leftThreshold && onSwipeLeft) {
        onSwipeLeft();
      } else if (direction === "right" && tx > rightThreshold && onSwipeRight) {
        onSwipeRight();
      } else if (direction === "up" && ty < -upThreshold && onSwipeUp) {
        onSwipeUp();
      } else if (direction === "down" && ty > downThreshold && onSwipeDown) {
        onSwipeDown();
      }
      setDirection(null);
    },
    [
      direction,
      leftThreshold,
      rightThreshold,
      upThreshold,
      downThreshold,
      onSwipeLeft,
      onSwipeRight,
      onSwipeUp,
      onSwipeDown,
    ],
  );

  const handleDragStart = useCallback(() => {
    setIsSwiping(true);
  }, []);

  const handleDrag = useCallback((_: MotionDragEvent, info: PanInfo) => {
    const tx = info.offset.x;
    const ty = info.offset.y;
    const absX = Math.abs(tx);
    const absY = Math.abs(ty);

    if (absX > absY) {
      if (tx < 0) setDirection("left");
      else setDirection("right");
    } else {
      if (ty < 0) setDirection("up");
      else setDirection("down");
    }
  }, []);

  if (!enabled) {
    return <div className={className}>{children}</div>;
  }

  return (
    <div ref={constraintsRef} className={cn("relative", className)}>
      {/* Background indicators */}
      {direction === "left" && leftContent && (
        <div className="absolute inset-0 flex items-center justify-end pr-4 pointer-events-none">
          {leftContent}
        </div>
      )}
      {direction === "right" && rightContent && (
        <div className="absolute inset-0 flex items-center justify-start pl-4 pointer-events-none">
          {rightContent}
        </div>
      )}
      {direction === "up" && upContent && (
        <div className="absolute inset-0 flex items-end justify-center pb-4 pointer-events-none">
          {upContent}
        </div>
      )}
      {direction === "down" && downContent && (
        <div className="absolute inset-0 flex items-start justify-center pt-4 pointer-events-none">
          {downContent}
        </div>
      )}

      {/* Swipeable content */}
      <motion.div
        drag={enabled ? "x" : false}
        dragConstraints={{ left: -200, right: 200, top: -100, bottom: 100 }}
        dragElastic={0.2}
        onDragStart={handleDragStart}
        onDrag={handleDrag}
        onDragEnd={handleDragEnd}
        style={{ x, y, rotate }}
        whileTap={{ cursor: "grabbing" }}
        className={cn(
          "touch-none select-none cursor-grab active:cursor-grabbing",
          isSwiping && "z-10",
        )}
      >
        {children}
      </motion.div>
    </div>
  );
}
