"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { HelpCircle, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/features/workbench/components/CommandPalette";
import { AccountPopover } from "@/features/workbench/components/AccountPopover";
import { useI18n } from "@/providers/I18nProvider";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface Props {
  breadcrumbs?: BreadcrumbItem[];
  right?: React.ReactNode;
  /** Top-level workspace name shown right after the C logo. Falls back to the repo name. */
  workspaceLabel?: string;
}

/**
 * Console v2 reference style top bar:
 *
 *   [C] codex / jackmouse-ai / agent-collab-console        🔍 Search …  ⌘K   ●
 *
 * - Orange `C` brand mark
 * - Slash-separated breadcrumb (muted segments, last segment bold)
 * - Right-aligned search input with ⌘K hint chip + user avatar
 */
export function AppHeader({ breadcrumbs = [], right, workspaceLabel }: Props) {
  const { t } = useI18n();
  // Prepend a "codex" segment if not already part of breadcrumbs, mirroring the
  // reference (`codex / jackmouse-ai / agent-collab-console`).
  const rootCrumb: BreadcrumbItem = { label: workspaceLabel ?? "codex", href: "/" };
  const allCrumbs = [rootCrumb, ...breadcrumbs];
  const [paletteOpen, setPaletteOpen] = useState(false);

  // ⌘K / Ctrl+K globally opens the palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <header className="h-12 shrink-0 border-b border-border-subtle bg-surface flex items-center gap-3.5 px-4 relative z-10">
        <Link
          href="/"
          aria-label="Home"
          className="flex items-center justify-center size-[26px] rounded-[7px] font-mono font-bold text-[14px] shrink-0 transition-transform hover:scale-[1.04]"
          style={{
            background: "linear-gradient(135deg, var(--color-brand-strong), #cf7838)",
            color: "#1a0e05",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.18) inset, 0 4px 12px -3px var(--color-brand-ring)",
          }}
        >
          C
        </Link>
        <Breadcrumbs items={allCrumbs} />
        <div className="ml-auto flex items-center gap-2">
          {right}
          <SearchInput onOpen={() => setPaletteOpen(true)} t={t} />
          <HelpButton />
          <AccountPopover />
        </div>
      </header>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}

function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex items-center min-w-0 text-[13px]">
      {items.map((b, i) => {
        const isLast = i === items.length - 1;
        const content = (
          <span
            className={cn(
              "truncate",
              isLast ? "text-foreground font-semibold" : "text-text-muted",
              !isLast && b.href && "hover:text-foreground transition-colors",
            )}
          >
            {b.label}
          </span>
        );
        return (
          <span key={i} className="flex items-center gap-2 min-w-0">
            {i > 0 && <span className="text-text-muted/50 select-none">/</span>}
            {b.href && !isLast ? (
              <Link href={b.href}>{content}</Link>
            ) : (
              content
            )}
          </span>
        );
      })}
    </nav>
  );
}

function HelpButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.push("/help")}
      title="How does this work? (?)"
      className={cn(
        "size-7 rounded-md flex items-center justify-center text-text-muted",
        "hover:bg-surface-hover hover:text-foreground transition-colors",
      )}
      aria-label="Help"
    >
      <HelpCircle size={15} />
    </button>
  );
}

function SearchInput({ onOpen, t }: { onOpen: () => void; t: (key: string) => string }) {
  const [isMac, setIsMac] = useState(true);
  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setIsMac(/Mac|iPhone|iPad/i.test(navigator.userAgent));
    }
  }, []);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "relative w-[380px] max-w-[42vw] h-[30px] pl-7 pr-12 rounded-[7px] text-[12.5px] text-left outline-none",
        "bg-surface-input border border-border-muted",
        "text-text-muted hover:border-border-strong hover:text-foreground transition-colors",
      )}
    >
      <Search
        size={13}
        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
      />
      {t("header.jumpToPlaceholder")}
      <span className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5 text-[10px] text-text-muted font-mono pointer-events-none">
        <kbd className="px-1 py-0.5 rounded bg-surface-raised border border-border-subtle">
          {isMac ? "⌘" : "Ctrl"}
        </kbd>
        <kbd className="px-1 py-0.5 rounded bg-surface-raised border border-border-subtle">K</kbd>
      </span>
    </button>
  );
}
