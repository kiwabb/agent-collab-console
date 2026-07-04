"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Folder, HelpCircle, Menu, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { CommandPalette } from "@/features/workbench/components/CommandPalette";
import { AccountPopover } from "@/features/workbench/components/AccountPopover";
import { useSelection } from "@/features/workbench/state/SelectionProvider";
import { listProjects } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/providers/I18nProvider";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface Props {
  breadcrumbs?: BreadcrumbItem[];
  onMenuClick?: () => void;
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
export function AppHeader({ breadcrumbs = [], onMenuClick, right, workspaceLabel }: Props) {
  const { t } = useI18n();
  const rootLabel = workspaceLabel ?? "codex";
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
      <header className="relative z-10 flex h-14 shrink-0 items-center gap-2.5 border-b border-border-subtle/80 bg-surface/85 px-3 backdrop-blur-md sm:gap-3.5 sm:px-4">
        <Link
          href="/"
          aria-label={t("ui.home")}
          className="flex items-center justify-center size-[28px] rounded-[9px] font-mono font-bold text-[14px] shrink-0 transition-transform hover:scale-[1.04]"
          style={{
            background: "linear-gradient(135deg, var(--color-brand-strong), #cf7838)",
            color: "#1a0e05",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.18) inset, 0 4px 12px -3px var(--color-brand-ring)",
          }}
        >
          C
        </Link>
        {onMenuClick && (
          <button
            type="button"
            onClick={onMenuClick}
            aria-label={t("ui.openNavigation")}
            className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-surface-input/80 text-text-muted transition-colors hover:bg-surface-hover hover:text-foreground lg:hidden"
          >
            <Menu size={18} aria-hidden />
          </button>
        )}
        <nav
          aria-label={t("ui.breadcrumb")}
          className="flex min-w-0 flex-1 items-center gap-2 text-[13px]"
        >
          <Link href="/" className="shrink-0">
            <span className="text-text-muted hover:text-foreground transition-colors">
              {rootLabel}
            </span>
          </Link>
          <HeaderProjectSwitcher />
          {breadcrumbs.map((b, i) => {
            const isLast = i === breadcrumbs.length - 1;
            return (
              <span key={i} className="flex items-center gap-2 min-w-0">
                <span className="text-text-muted/50 select-none">/</span>
                {b.href && !isLast ? (
                  <Link href={b.href}>
                    <span className="truncate text-text-muted hover:text-foreground transition-colors">
                      {b.label}
                    </span>
                  </Link>
                ) : (
                  <span
                    className={cn(
                      "truncate",
                      isLast ? "text-foreground font-semibold" : "text-text-muted",
                    )}
                  >
                    {b.label}
                  </span>
                )}
              </span>
            );
          })}
        </nav>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2.5">
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

/**
 * Project name shown right after the "codex" root segment, as a dropdown that
 * switches the active project (mirrors the sidebar switcher). Renders nothing
 * until projects load, so the header reads "codex / <project> / <page>".
 */
function HeaderProjectSwitcher() {
  const { t } = useI18n();
  const router = useRouter();
  const { projectId, setProjectId } = useSelection();
  const [projects, setProjects] = useState<Project[]>([]);
  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((list) => {
        if (!cancelled) setProjects(list);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  if (projects.length === 0) return null;
  const active = projects.find((p) => p.id === projectId);
  return (
    <>
      <span className="text-text-muted/50 select-none">/</span>
      <DropdownMenu>
        <DropdownMenuTrigger className="flex items-center gap-1 min-w-0 max-w-[220px] outline-none text-foreground font-semibold hover:text-brand transition-colors">
          <span className="truncate">{active?.name ?? t("workbench.projectSwitcher")}</span>
          <ChevronDown size={13} className="shrink-0 opacity-60" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuGroup>
            <DropdownMenuLabel>{t("workbench.projectSwitcher")}</DropdownMenuLabel>
            {projects.map((p) => (
              <DropdownMenuItem
                key={p.id}
                onClick={() => {
                  setProjectId(p.id);
                  router.push(`/projects/${p.id}`);
                }}
                className={p.id === projectId ? "bg-brand/10 font-medium text-brand" : ""}
              >
                <Folder size={14} className="mr-2 opacity-50" />
                <span className="truncate">{p.name}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}

function HelpButton() {
  const router = useRouter();
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={() => router.push("/help")}
      title={t("ui.helpTitle")}
      className={cn(
        "size-8 rounded-lg flex items-center justify-center text-text-muted",
        "hover:bg-surface-hover hover:text-foreground transition-colors",
      )}
      aria-label={t("ui.help")}
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
        "relative hidden h-[34px] w-[360px] max-w-[42vw] rounded-[10px] pl-8 pr-12 text-left text-[12.5px] outline-none sm:block",
        "bg-surface-input/90 border border-border-muted shadow-sm",
        "text-text-muted hover:border-border-strong hover:text-foreground transition-colors",
      )}
    >
      <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
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
