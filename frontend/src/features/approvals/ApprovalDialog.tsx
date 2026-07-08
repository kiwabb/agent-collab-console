"use client";

import { useState } from "react";
import type { Approval } from "@/lib/types";
import { AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import { useI18n } from "@/providers/I18nProvider";

interface ApprovalDialogProps {
  approval: Approval | null;
  onResolve: (decision: "approve" | "reject", feedback: string | null) => void;
  onClose: () => void;
}

export function ApprovalDialog({ approval, onResolve, onClose }: ApprovalDialogProps) {
  const { t } = useI18n();
  const [feedback, setFeedback] = useState("");

  if (!approval) return null;

  function handleApprove() {
    onResolve("approve", feedback || null);
  }

  function handleReject() {
    onResolve("reject", feedback || null);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card border border-border rounded-lg shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center gap-2 p-4 border-b border-border">
          <AlertTriangle size={16} className="text-yellow-500" />
          <h2 className="text-sm font-semibold text-foreground">{t("approval.pending")}</h2>
        </div>

        <div className="p-4">
          <div className="mb-3">
            <p className="text-xs text-muted-foreground">{t("approval.taskId")}</p>
            <p className="text-sm text-foreground font-mono">{approval.task_id}</p>
          </div>
          <div className="mb-3">
            <p className="text-xs text-muted-foreground">{t("approval.action")}</p>
            <p className="text-sm text-foreground">{approval.action}</p>
          </div>
          <div className="mb-4">
            <label className="text-xs text-muted-foreground mb-1 block">
              {t("approval.feedback")}
            </label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder={t("approval.feedbackPlaceholder")}
              rows={3}
              className="w-full px-2 py-1.5 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
            />
          </div>
        </div>

        <div className="flex gap-2 p-4 border-t border-border">
          <button
            onClick={handleReject}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-md border border-red-500 text-red-500 hover:bg-red-500/10 transition-colors"
          >
            <XCircle size={14} />
            {t("approval.reject")}
          </button>
          <button
            onClick={handleApprove}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <CheckCircle size={14} />
            {t("approval.approve")}
          </button>
        </div>

        <button
          onClick={onClose}
          className="absolute top-3 right-3 p-1 rounded-md hover:bg-accent text-muted-foreground"
          aria-label="Close"
        >
          ×
        </button>
      </div>
    </div>
  );
}
