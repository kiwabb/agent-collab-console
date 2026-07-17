"use client";

import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";

import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const STRUCTURED_PROTOTYPE_DESKTOP_MEDIA_QUERY = "(min-width: 80rem)";

interface Props {
  children: ReactNode;
  closeLabel: string;
  description: string;
  desktop: boolean;
  desktopClassName: string;
  drawerClassName: string;
  open: boolean;
  side: "left" | "right";
  title: string;
  onOpenChange: (open: boolean) => void;
}

export function useStructuredPrototypeDesktopLayout(): boolean {
  const [desktop, setDesktop] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia(STRUCTURED_PROTOTYPE_DESKTOP_MEDIA_QUERY);
    const updateDesktopLayout = (): void => setDesktop(mediaQuery.matches);
    updateDesktopLayout();
    mediaQuery.addEventListener("change", updateDesktopLayout);
    return () => mediaQuery.removeEventListener("change", updateDesktopLayout);
  }, []);

  return desktop;
}

export function StructuredPrototypeResponsiveSideRegion({
  children,
  closeLabel,
  description,
  desktop,
  desktopClassName,
  drawerClassName,
  open,
  side,
  title,
  onOpenChange,
}: Props) {
  if (desktop) {
    return (
      <aside
        className={desktopClassName}
        data-prototype-responsive-side-region={side}
        data-prototype-side-region-mode="desktop"
      >
        {children}
      </aside>
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange} modal="trap-focus">
      {open && (
        <SheetContent
          className={cn(
            "max-w-full gap-0 overflow-hidden p-0 pb-14 motion-reduce:transition-none",
            drawerClassName,
          )}
          side={side}
          showCloseButton={false}
          overlayClassName="bg-black/45 supports-backdrop-filter:backdrop-blur-sm"
          data-prototype-responsive-side-region={side}
          data-prototype-side-region-mode="drawer"
        >
          <SheetTitle className="sr-only">{title}</SheetTitle>
          <SheetDescription className="sr-only">{description}</SheetDescription>
          <SheetClose
            render={
              <button
                type="button"
                className="absolute top-0 right-0 z-20 grid size-11 cursor-pointer place-items-center bg-popover text-text-muted hover:bg-surface-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                aria-label={closeLabel}
                title={closeLabel}
              />
            }
          >
            <X size={18} aria-hidden />
          </SheetClose>
          {children}
        </SheetContent>
      )}
    </Sheet>
  );
}
