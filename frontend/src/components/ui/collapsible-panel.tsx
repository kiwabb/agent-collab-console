"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface CollapsiblePanelProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
  rightContent?: React.ReactNode;
  onToggle?: (isOpen: boolean) => void;
}

export function CollapsiblePanel({
  title,
  children,
  defaultOpen = true,
  className,
  headerClassName,
  contentClassName,
  rightContent,
  onToggle,
}: CollapsiblePanelProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const handleToggle = () => {
    const newState = !isOpen;
    setIsOpen(newState);
    onToggle?.(newState);
  };

  return (
    <div className={cn("rounded-xl border border-border-subtle overflow-hidden", className)}>
      <button
        type="button"
        onClick={handleToggle}
        className={cn(
          "w-full flex items-center gap-2 px-4 py-3 bg-surface-raised hover:bg-surface-hover transition-colors text-left",
          headerClassName
        )}
      >
        {isOpen ? (
          <ChevronDown size={16} className="text-text-muted flex-shrink-0" />
        ) : (
          <ChevronRight size={16} className="text-text-muted flex-shrink-0" />
        )}
        <span className="text-sm font-bold text-foreground flex-1">{title}</span>
        {rightContent && <div className="flex items-center gap-2">{rightContent}</div>}
      </button>
      <div
        className={cn(
          "transition-all duration-300 ease-out",
          isOpen ? "max-h-[5000px] opacity-100" : "max-h-0 opacity-0 overflow-hidden"
        )}
      >
        <div className={cn("p-4", contentClassName)}>{children}</div>
      </div>
    </div>
  );
}
