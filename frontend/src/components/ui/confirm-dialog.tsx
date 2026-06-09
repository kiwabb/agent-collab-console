"use client";

import { AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  isLoading?: boolean;
  loadingMotionPhase?: string;
  loadingDensity?: string;
  loadingIndicatorSize?: number;
  variant?: "destructive" | "warning" | "default";
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText,
  cancelText,
  onConfirm,
  isLoading = false,
  loadingMotionPhase,
  loadingDensity,
  loadingIndicatorSize = 12,
  variant = "destructive",
}: ConfirmDialogProps) {
  const { t } = useI18n();

  const variantStyles = {
    destructive: "bg-error text-background hover:bg-error/90",
    warning: "bg-warning text-background hover:bg-warning/90",
    default: "bg-brand text-background hover:bg-brand/90",
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <div className="flex items-center gap-3">
            {variant === "destructive" && (
              <div className="size-10 rounded-xl bg-error/10 flex items-center justify-center">
                <AlertTriangle size={20} className="text-error" />
              </div>
            )}
            {variant === "warning" && (
              <div className="size-10 rounded-xl bg-warning/10 flex items-center justify-center">
                <AlertTriangle size={20} className="text-warning" />
              </div>
            )}
            <DialogTitle>{title}</DialogTitle>
          </div>
          {description && (
            <DialogDescription className="pt-2">{description}</DialogDescription>
          )}
        </DialogHeader>
        <DialogFooter className="sm:justify-end">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            {cancelText || t("issue.cancel")}
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            data-density={isLoading ? loadingDensity : undefined}
            className={cn(
              variantStyles[variant],
              "shadow-md",
              isLoading && loadingMotionPhase && "motion-essential",
            )}
          >
            {isLoading ? (
              loadingMotionPhase ? (
                <AgentThinkingIndicator
                  phase={loadingMotionPhase}
                  size={loadingIndicatorSize}
                />
              ) : (
                <span className="flex items-center gap-2">
                  <div className="flex gap-1">
                    <div className="size-1 bg-current rounded-full animate-bounce [animation-delay:-0.3s]" />
                    <div className="size-1 bg-current rounded-full animate-bounce [animation-delay:-0.15s]" />
                    <div className="size-1 bg-current rounded-full animate-bounce" />
                  </div>
                </span>
              )
            ) : (
              confirmText || t("issue.deleteConfirm")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
