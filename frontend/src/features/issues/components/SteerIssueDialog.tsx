"use client";

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/providers/I18nProvider";

export function SteerIssueDialog({
  open,
  draft,
  sending,
  onOpenChange,
  onDraftChange,
  onSubmit,
}: {
  open: boolean;
  draft: string;
  sending: boolean;
  onOpenChange: (open: boolean) => void;
  onDraftChange: (draft: string) => void;
  onSubmit: () => void;
}) {
  const { t } = useI18n();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("issue.steerDialogTitle")}</DialogTitle>
          <DialogDescription>{t("issue.steerDialogBody")}</DialogDescription>
        </DialogHeader>
        <textarea
          autoFocus
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          rows={5}
          placeholder={t("issue.steerPlaceholder")}
          className="w-full rounded-md border border-border-subtle bg-background px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-2 focus:ring-brand/50"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={sending}>
            {t("issue.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={sending || !draft.trim()} className="bg-brand text-black hover:bg-brand-strong">
            {sending ? (
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> {t("issue.sending")}
              </span>
            ) : (
              t("issue.sendToAgent")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
