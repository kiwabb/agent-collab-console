"use client";

import { useEffect, useState } from "react";
import { CommandPalette as InnerCommandPalette } from "@/features/workbench/components/CommandPalette";

type CommandPaletteProps = {
  open?: boolean;
  onClose?: () => void;
  onOpenChange?: (open: boolean) => void;
  onCreateIssue?: () => void;
  onCreateWorkspace?: () => void;
};

export function CommandPalette({
  open,
  onClose,
  onOpenChange,
  onCreateIssue,
  onCreateWorkspace,
}: CommandPaletteProps) {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (typeof open === "boolean") {
      setIsOpen(open);
    }
  }, [open]);

  const closePalette = () => {
    if (onOpenChange) {
      onOpenChange(false);
    } else {
      setIsOpen(false);
    }
    onClose?.();
    onCreateIssue?.();
    onCreateWorkspace?.();
  };

  const isControlled = typeof open === "boolean";
  const shown = isControlled ? open : isOpen;

  return <InnerCommandPalette open={shown} onClose={closePalette} />;
}

export default CommandPalette;
