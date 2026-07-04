"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useCallback, useMemo } from "react";
import { useI18n } from "@/providers/I18nProvider";

type MacroRecorderProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function useMacros() {
  const runMacro = useCallback((id: string) => {
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent("agent-collab-run-macro", { detail: { id } }));
  }, []);

  return useMemo(() => ({ runMacro }), [runMacro]);
}

export function MacroRecorder({ open, onOpenChange }: MacroRecorderProps) {
  const { t } = useI18n();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("macroRecorder.title")}</DialogTitle>
        </DialogHeader>
        <div className="p-4 text-sm text-muted-foreground">
          {t("macroRecorder.placeholder")}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default MacroRecorder;
