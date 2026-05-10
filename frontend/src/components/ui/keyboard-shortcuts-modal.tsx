"use client";

import { useState, useEffect } from "react";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useI18n } from "@/providers/I18nProvider";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";

interface ShortcutEntry {
  keys: string[];
  description: string;
  category: string;
}

const shortcutsByCategory = (t: (key: string) => string): Record<string, ShortcutEntry[]> => ({
  "Navigation": [
    { keys: ["H"], description: t("shortcuts.home"), category: "Navigation" },
    { keys: ["W"], description: t("shortcuts.workspace"), category: "Navigation" },
    { keys: ["I"], description: t("shortcuts.issue"), category: "Navigation" },
    { keys: ["Esc"], description: t("shortcuts.back"), category: "Navigation" },
  ],
  "Actions": [
    { keys: ["?"], description: t("shortcuts.help"), category: "Actions" },
    { keys: ["N"], description: t("shortcuts.newIssue"), category: "Actions" },
    { keys: ["S"], description: t("shortcuts.settings"), category: "Actions" },
    { keys: ["R"], description: t("shortcuts.rerun"), category: "Actions" },
    { keys: ["P"], description: t("shortcuts.pasteImage"), category: "Actions" },
  ],
});

export function KeyboardShortcutsModal() {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();

  useKeyboardShortcuts([
    {
      key: "?",
      action: () => setOpen(true),
      description: "Open keyboard shortcuts",
    },
  ]);

  const categories = shortcutsByCategory(t as (key: string) => string);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md" showCloseButton>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="text-lg">⌨️</span>
            {t("shortcuts.title")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-6 py-2">
          {Object.entries(categories).map(([category, items]) => (
            <div key={category}>
              <h3 className="text-[10px] font-black uppercase tracking-widest text-text-muted mb-3">
                {category}
              </h3>
              <div className="space-y-2">
                {items.map((shortcut) => (
                  <div
                    key={shortcut.description}
                    className="flex items-center justify-between py-1.5"
                  >
                    <span className="text-sm text-text-secondary">
                      {shortcut.description}
                    </span>
                    <div className="flex items-center gap-1">
                      {shortcut.keys.map((key) => (
                        <Kbd key={key} className={cn(
                          "min-w-[1.5rem] h-6 text-xs",
                          key === "?" && "bg-brand/20 text-brand border-brand/30"
                        )}>
                          {key}
                        </Kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}