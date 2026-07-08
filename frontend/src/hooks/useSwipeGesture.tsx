"use client";

import { useCallback, useRef, useState } from "react";

interface SwipeState {
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  isSwiping: boolean;
}

interface UseSwipeGestureOptions {
  onSwipeLeft?: (() => void) | undefined;
  onSwipeRight?: (() => void) | undefined;
  onSwipeUp?: (() => void) | undefined;
  onSwipeDown?: (() => void) | undefined;
  threshold?: number | undefined;
  enabled?: boolean | undefined;
}

export function useSwipeGesture({
  onSwipeLeft,
  onSwipeRight,
  onSwipeUp,
  onSwipeDown,
  threshold = 50,
  enabled = true,
}: UseSwipeGestureOptions) {
  const [swipeState, setSwipeState] = useState<SwipeState>({
    startX: 0,
    startY: 0,
    currentX: 0,
    currentY: 0,
    isSwiping: false,
  });
  const [swipeProgress, setSwipeProgress] = useState(0);
  const directionRef = useRef<"left" | "right" | "up" | "down" | null>(null);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (!enabled) return;
      const touch = e.touches[0];
      if (!touch) return;
      directionRef.current = null;
      setSwipeState({
        startX: touch.clientX,
        startY: touch.clientY,
        currentX: touch.clientX,
        currentY: touch.clientY,
        isSwiping: true,
      });
      setSwipeProgress(0);
    },
    [enabled],
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!swipeState.isSwiping) return;
      const touch = e.touches[0];
      if (!touch) return;
      const deltaX = touch.clientX - swipeState.startX;
      const deltaY = touch.clientY - swipeState.startY;

      // Determine primary direction
      if (!directionRef.current) {
        if (Math.abs(deltaX) > Math.abs(deltaY)) {
          directionRef.current = deltaX > 0 ? "right" : "left";
        } else {
          directionRef.current = deltaY > 0 ? "down" : "up";
        }
      }

      const currentDelta =
        directionRef.current === "left" || directionRef.current === "right" ? deltaX : deltaY;

      const progress = Math.min(Math.abs(currentDelta) / threshold, 1);
      setSwipeProgress(progress);
      setSwipeState((prev) => ({
        ...prev,
        currentX: touch.clientX,
        currentY: touch.clientY,
      }));
    },
    [swipeState.isSwiping, swipeState.startX, swipeState.startY, threshold],
  );

  const handleTouchEnd = useCallback(() => {
    if (!swipeState.isSwiping) return;

    const deltaX = swipeState.currentX - swipeState.startX;
    const absDeltaX = Math.abs(deltaX);

    const deltaY = swipeState.currentY - swipeState.startY;
    const absDeltaY = Math.abs(deltaY);

    if (directionRef.current === "left" && absDeltaX > threshold && onSwipeLeft) {
      onSwipeLeft();
    } else if (directionRef.current === "right" && absDeltaX > threshold && onSwipeRight) {
      onSwipeRight();
    } else if (directionRef.current === "up" && absDeltaY > threshold && onSwipeUp) {
      onSwipeUp();
    } else if (directionRef.current === "down" && absDeltaY > threshold && onSwipeDown) {
      onSwipeDown();
    }

    setSwipeState({
      startX: 0,
      startY: 0,
      currentX: 0,
      currentY: 0,
      isSwiping: false,
    });
    setSwipeProgress(0);
    directionRef.current = null;
  }, [swipeState, threshold, onSwipeLeft, onSwipeRight, onSwipeUp, onSwipeDown]);

  const handlers = {
    onTouchStart: handleTouchStart,
    onTouchMove: handleTouchMove,
    onTouchEnd: handleTouchEnd,
  };

  return { handlers, swipeProgress, isSwiping: swipeState.isSwiping };
}

interface SwipeableCardProps {
  children: React.ReactNode;
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  className?: string;
  enabled?: boolean;
}

export function SwipeableCard({
  children,
  onSwipeLeft,
  onSwipeRight,
  className,
  enabled = true,
}: SwipeableCardProps) {
  const { handlers, swipeProgress, isSwiping } = useSwipeGesture({
    onSwipeLeft,
    onSwipeRight,
    enabled,
  });

  return (
    <div
      {...handlers}
      className={className}
      style={{
        transform:
          isSwiping && swipeProgress > 0
            ? `translateX(${(swipeProgress - 1) * 30}px) rotate(${swipeProgress * 2}deg)`
            : undefined,
        opacity: isSwiping ? 1 - swipeProgress * 0.3 : 1,
        transition: isSwiping ? "none" : "all 0.3s ease",
      }}
    >
      {children}
      {isSwiping && swipeProgress > 0.3 && (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ opacity: swipeProgress }}
        >
          <div className={swipeProgress > 0.6 ? "text-error" : "text-text-muted"}>
            {swipeProgress > 0.6 ? "Release to delete" : "Swipe to delete"}
          </div>
        </div>
      )}
    </div>
  );
}
