"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useOnboardingTour, type TourStep, isTourCompleted, markTourCompleted } from "./OnboardingTooltip";
import { cn } from "@/lib/utils";
import { HelpCircle, X, ChevronRight, ChevronLeft, Check } from "lucide-react";

const WORKFLOW_TOUR_ID = "workflow-guide";
const SETUP_TOUR_ID = "setup-guide";

interface OnboardingGuideProps {
  enabled?: boolean;
}

export function OnboardingGuide({ enabled = true }: OnboardingGuideProps) {
  const { isActive, currentStep, steps, nextStep, prevStep, endTour, startTour } = useOnboardingTour();

  const [hasSeenTour, setHasSeenTour] = useState(false);

  useEffect(() => {
    if (enabled) {
      const completed = isTourCompleted(WORKFLOW_TOUR_ID);
      setHasSeenTour(completed);
    }
  }, [enabled]);

  const handleStartTour = useCallback(() => {
    const tourSteps: TourStep[] = [
      {
        id: "workspace",
        target: "[data-tour='workspace']",
        title: "Create a Workspace",
        content: "Workspaces help you organize different projects. Click 'New Workspace' to get started with your first project.",
        placement: "bottom",
      },
      {
        id: "issue",
        target: "[data-tour='issue-create']",
        title: "Create an Issue",
        content: "Issues represent the work to be done. Each issue can have multiple tasks across different phases.",
        placement: "bottom",
      },
      {
        id: "phases",
        target: "[data-tour='phases']",
        title: "Track Progress",
        content: "Watch your tasks move through phases: Requirements, Architecture, Development, and Testing.",
        placement: "top",
      },
      {
        id: "artifacts",
        target: "[data-tour='artifacts']",
        title: "View Artifacts",
        content: "AI agents generate artifacts like requirements docs, system designs, and code. Click to expand and view them.",
        placement: "left",
      },
      {
        id: "keyboard",
        target: "[data-tour='shortcuts']",
        title: "Keyboard Shortcuts",
        content: "Press H for Home, W for Workspace, I for Issue details. Use Escape to go back.",
        placement: "top",
      },
    ];
    startTour(tourSteps);
    markTourCompleted(WORKFLOW_TOUR_ID);
    setHasSeenTour(true);
  }, [startTour]);

  if (!enabled || hasSeenTour) return null;

  return (
    <>
      {/* Tour trigger button */}
      <motion.button
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 1, duration: 0.3 }}
        onClick={handleStartTour}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-3 px-5 py-3 bg-brand text-background rounded-full shadow-lg shadow-brand/30 hover:bg-brand/90 transition-all group"
        data-tour="help-button"
      >
        <HelpCircle size={18} className="group-hover:rotate-12 transition-transform" />
        <span className="text-sm font-bold">Take Tour</span>
      </motion.button>

      {/* Onboarding overlay */}
      {isActive && <OnboardingOverlay />}
    </>
  );
}

function OnboardingOverlay() {
  const { currentStep, steps, nextStep, prevStep, endTour } = useOnboardingTour();

  if (!steps.length) return null;

  const step = steps[currentStep];
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const updateRect = () => {
      const el = document.querySelector(step.target);
      if (el) {
        setTargetRect(el.getBoundingClientRect());
      }
    };

    updateRect();
    window.addEventListener("resize", updateRect);
    return () => window.removeEventListener("resize", updateRect);
  }, [step.target]);

  if (!mounted) return null;

  const isLastStep = currentStep === steps.length - 1;
  const isFirstStep = currentStep === 0;

  const spotlightStyle = targetRect
    ? {
        top: targetRect.top - 8,
        left: targetRect.left - 8,
        width: targetRect.width + 16,
        height: targetRect.height + 16,
      }
    : { display: "none" };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50"
      >
        {/* Dark overlay with spotlight */}
        <div className="absolute inset-0 bg-black/60" style={{ backdropFilter: "blur(2px)" }} />

        {/* Spotlight effect */}
        <motion.div
          layoutId="spotlight"
          className="absolute rounded-2xl"
          style={spotlightStyle}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
        />

        {/* Tooltip card */}
        <motion.div
          className="absolute w-80 bg-surface-raised border border-border-subtle rounded-2xl shadow-2xl overflow-hidden"
          style={{
            top: targetRect ? step.placement === "bottom" ? targetRect.bottom + 16 : targetRect.top - 16 : "50%",
            left: targetRect ? step.placement === "right" ? targetRect.right + 16 : step.placement === "left" ? targetRect.left - 320 : targetRect.left + targetRect.width / 2 - 160 : "50%",
            transform: targetRect
              ? step.placement === "bottom" || step.placement === "top"
                ? "translateX(-50%)"
                : step.placement === "left"
                  ? "translateY(-50%)"
                  : "translateX(-50%)"
              : "translate(-50%, -50%)",
          }}
          initial={{ opacity: 0, scale: 0.9, y: step.placement === "bottom" ? -20 : 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          {/* Header */}
          <div className="p-5 pb-4 border-b border-border-subtle">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-black uppercase tracking-widest text-brand">
                Step {currentStep + 1} of {steps.length}
              </span>
              <button
                onClick={endTour}
                className="p-1 rounded-lg hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors"
              >
                <X size={16} />
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
              disabled={isFirstStep}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all",
                isFirstStep
                  ? "text-text-muted/40 cursor-not-allowed"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover"
              )}
            >
              <ChevronLeft size={14} />
              Back
            </button>

            {/* Progress dots */}
            <div className="flex gap-1.5">
              {steps.map((_, i) => (
                <motion.div
                  key={i}
                  className={cn(
                    "size-2 rounded-full transition-all",
                    i === currentStep ? "bg-brand w-5" : "bg-border-strong"
                  )}
                  animate={{ width: i === currentStep ? 20 : 8 }}
                />
              ))}
            </div>

            <button
              onClick={isLastStep ? endTour : nextStep}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 text-[10px] font-bold uppercase tracking-wider rounded-lg transition-all",
                isLastStep
                  ? "bg-success text-background hover:bg-success/90"
                  : "bg-brand text-background hover:bg-brand/90"
              )}
            >
              {isLastStep ? (
                <>
                  Done
                  <Check size={14} />
                </>
              ) : (
                <>
                  Next
                  <ChevronRight size={14} />
                </>
              )}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// Helper hook for integrating tour targets into components
export function useTourTarget(tourId: string) {
  useEffect(() => {
    const el = document.querySelector(`[data-tour="${tourId}"]`);
    if (el) {
      el.setAttribute(`data-tour`, tourId);
    }
  }, [tourId]);
}

// Component to wrap elements with tour target
interface TourTargetProps {
  tourId: string;
  children: React.ReactNode;
  className?: string;
}

export function TourTarget({ tourId, children, className }: TourTargetProps) {
  return (
    <div data-tour={tourId} className={className}>
      {children}
    </div>
  );
}
