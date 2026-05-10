"use client";

import { createContext, useContext, useState, useCallback, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";

export type TourStep = {
  id: string;
  target: string;
  title: string;
  content: string;
  placement?: "top" | "bottom" | "left" | "right";
};

interface OnboardingTourContextType {
  isActive: boolean;
  currentStep: number;
  startTour: (steps: TourStep[]) => void;
  nextStep: () => void;
  prevStep: () => void;
  endTour: () => void;
  steps: TourStep[];
}

const OnboardingTourContext = createContext<OnboardingTourContextType | null>(null);

export function useOnboardingTour() {
  const context = useContext(OnboardingTourContext);
  if (!context) {
    throw new Error("useOnboardingTour must be used within OnboardingTourProvider");
  }
  return context;
}

export function OnboardingTourProvider({ children }: { children: React.ReactNode }) {
  const [isActive, setIsActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [steps, setSteps] = useState<TourStep[]>([]);

  const startTour = useCallback((newSteps: TourStep[]) => {
    setSteps(newSteps);
    setCurrentStep(0);
    setIsActive(true);
  }, []);

  const nextStep = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, steps.length - 1));
  }, [steps.length]);

  const prevStep = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 0));
  }, []);

  const endTour = useCallback(() => {
    setIsActive(false);
    setCurrentStep(0);
    setSteps([]);
  }, []);

  return (
    <OnboardingTourContext.Provider value={{
      isActive,
      currentStep,
      startTour,
      nextStep,
      prevStep,
      endTour,
      steps,
    }}>
      {children}
    </OnboardingTourContext.Provider>
  );
}

interface OnboardingTooltipProps {
  className?: string;
}

export function OnboardingTooltip({ className }: OnboardingTooltipProps) {
  const { isActive, currentStep, steps, nextStep, prevStep, endTour } = useOnboardingTour();
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isActive || steps.length === 0) return;

    const step = steps[currentStep];
    const targetEl = document.querySelector(step.target);
    if (targetEl) {
      const rect = targetEl.getBoundingClientRect();
      setTargetRect(rect);
    }
  }, [isActive, currentStep, steps]);

  if (!isActive || steps.length === 0) return null;

  const step = steps[currentStep];
  const placement = step.placement || "bottom";

  const tooltipStyle: React.CSSProperties = targetRect
    ? {
        position: "fixed",
        top: placement === "bottom" ? targetRect.bottom + 12 :
              placement === "top" ? targetRect.top - 12 :
              placement === "left" ? targetRect.left :
              targetRect.right,
        left: placement === "right" ? targetRect.right + 12 :
               placement === "left" ? targetRect.left - 12 :
               targetRect.left + targetRect.width / 2,
        transform: placement === "bottom" ? "translateX(-50%)" :
                   placement === "top" ? "translateX(-50%) translateY(-100%)" :
                   placement === "left" ? "translateX(-100%)" : undefined,
      }
    : {};

  return (
    <AnimatePresence>
      <motion.div
        ref={tooltipRef}
        style={tooltipStyle}
        initial={{ opacity: 0, scale: 0.9, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 10 }}
        transition={{ duration: 0.2 }}
        className={cn(
          "z-50 w-80 bg-surface-raised border border-border-subtle rounded-2xl shadow-2xl shadow-black/20 overflow-hidden",
          className
        )}
      >
        {/* Spotlight */}
        <div
          className="absolute pointer-events-none"
          style={{
            position: "fixed",
            top: targetRect ? targetRect.top - 4 : 0,
            left: targetRect ? targetRect.left - 4 : 0,
            width: (targetRect?.width ?? 0) + 8,
            height: (targetRect?.height ?? 0) + 8,
            borderRadius: "12px",
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.5)",
          }}
        />

        {/* Header */}
        <div className="p-5 pb-4 border-b border-border-subtle">
          <div className="flex items-center justify-between">
            <span className="text-[9px] font-black uppercase tracking-widest text-brand">
              Step {currentStep + 1} of {steps.length}
            </span>
            <button
              onClick={endTour}
              className="text-text-muted hover:text-foreground transition-colors"
            >
              ✕
            </button>
          </div>
          <h3 className="mt-3 text-sm font-bold text-foreground">{step.title}</h3>
        </div>

        {/* Content */}
        <div className="p-5">
          <p className="text-xs text-text-secondary leading-relaxed">{step.content}</p>
        </div>

        {/* Footer */}
        <div className="p-5 pt-4 flex items-center justify-between border-t border-border-subtle bg-surface/30">
          <button
            onClick={prevStep}
            disabled={currentStep === 0}
            className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider text-text-muted hover:text-foreground disabled:opacity-30 transition-all"
          >
            ← Back
          </button>
          <div className="flex gap-1.5">
            {steps.map((_, i) => (
              <div
                key={i}
                className={cn(
                  "size-1.5 rounded-full transition-all",
                  i === currentStep ? "bg-brand w-4" : "bg-border-strong"
                )}
              />
            ))}
          </div>
          {currentStep < steps.length - 1 ? (
            <button
              onClick={nextStep}
              className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider bg-brand text-background rounded-lg hover:bg-brand/90 transition-all"
            >
              Next →
            </button>
          ) : (
            <button
              onClick={endTour}
              className="px-4 py-2 text-[10px] font-bold uppercase tracking-wider bg-success text-background rounded-lg hover:bg-success/90 transition-all"
            >
              Done ✓
            </button>
          )}
        </div>

        {/* Arrow indicator */}
        {targetRect && (
          <div
            className={cn(
              "absolute w-3 h-3 bg-surface-raised border-border-subtle rotate-45",
              placement === "bottom" && "-top-1.5 left-1/2 -translate-x-1/2",
              placement === "top" && "-bottom-1.5 left-1/2 -translate-x-1/2",
              placement === "left" && "-right-1.5 top-1/2 -translate-y-1/2",
              placement === "right" && "-left-1.5 top-1/2 -translate-y-1/2"
            )}
            style={{
              ...(placement === "bottom" && targetRect ? {
                left: targetRect.left + targetRect.width / 2,
              } : {}),
            }}
          />
        )}
      </motion.div>
    </AnimatePresence>
  );
}

// Local storage keys for tracking completed tours
const TOUR_COMPLETED_KEY = "onboarding_tour_completed";

export function isTourCompleted(tourId: string): boolean {
  if (typeof window === "undefined") return false;
  const completed = localStorage.getItem(TOUR_COMPLETED_KEY);
  if (!completed) return false;
  return JSON.parse(completed).includes(tourId);
}

export function markTourCompleted(tourId: string): void {
  if (typeof window === "undefined") return;
  const completed = JSON.parse(localStorage.getItem(TOUR_COMPLETED_KEY) || "[]");
  if (!completed.includes(tourId)) {
    completed.push(tourId);
    localStorage.setItem(TOUR_COMPLETED_KEY, JSON.stringify(completed));
  }
}