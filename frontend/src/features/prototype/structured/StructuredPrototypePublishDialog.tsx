"use client";

import { useEffect, useState } from "react";
import { CloudUpload } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/providers/I18nProvider";

export function StructuredPrototypePublishDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (summary: string | null) => void;
}) {
  const { t } = useI18n();
  const [summary, setSummary] = useState("");

  useEffect(() => {
    if (open) setSummary("");
  }, [open]);

  const confirm = (): void => {
    const trimmed = summary.trim();
    onConfirm(trimmed.length > 0 ? trimmed : null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CloudUpload size={16} aria-hidden />
            {t("prototype.structured.publishDialog.title")}
          </DialogTitle>
          <DialogDescription>
            {t("prototype.structured.publishDialog.description")}
          </DialogDescription>
        </DialogHeader>
        <label className="grid gap-1.5 text-xs font-semibold text-text-muted">
          {t("prototype.structured.publishDialog.summaryLabel")}
          <textarea
            className="min-h-20 w-full resize-y rounded-md border border-border-muted bg-surface-raised p-2 text-sm font-normal text-foreground outline-none focus:border-brand"
            value={summary}
            maxLength={200}
            placeholder={t("prototype.structured.publishDialog.summaryPlaceholder")}
            onChange={(event) => setSummary(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                confirm();
              }
            }}
          />
          <span className="justify-self-end font-normal">{summary.trim().length}/200</span>
        </label>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="inline-flex min-h-9 cursor-pointer items-center rounded-md border border-border-muted bg-surface-raised px-3 text-xs font-semibold text-foreground hover:bg-surface-hover"
            onClick={() => onOpenChange(false)}
          >
            {t("prototype.structured.publishDialog.cancel")}
          </button>
          <button
            type="button"
            className="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-md bg-brand px-3 text-xs font-semibold text-black hover:bg-brand-strong"
            onClick={confirm}
          >
            <CloudUpload size={14} aria-hidden />
            {t("prototype.structured.publishDialog.confirm")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
