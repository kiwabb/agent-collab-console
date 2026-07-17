"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrainCircuit, Folder, Layers, Palette, Settings2 } from "lucide-react";

import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

interface Props {
  projectId: string;
  project: Project | null;
  children: React.ReactNode;
  layout?: "default" | "workspace";
}

export function ProjectShell({ projectId, project, children, layout = "default" }: Props) {
  const { t } = useI18n();
  const pathname = usePathname();
  const isWorkspaceLayout = layout === "workspace";
  const conductorHref = `/projects/${projectId}/conductor`;
  const prototypesHref = `/projects/${projectId}/prototypes`;
  const envConfigHref = `/projects/${projectId}/env`;
  const workspacesHref = `/projects/${projectId}`;
  const navItems = [
    { href: workspacesHref, label: t("project.nav.workspaces"), icon: Layers },
    { href: conductorHref, label: t("project.nav.conductor"), icon: BrainCircuit },
    { href: prototypesHref, label: t("project.nav.prototypes"), icon: Palette },
    { href: envConfigHref, label: t("project.nav.envConfig"), icon: Settings2 },
  ];

  return (
    <div className={cn("min-h-full", isWorkspaceLayout && "flex h-full min-h-0 flex-col")}>
      <div className="relative overflow-hidden border-b border-border-subtle">
        {!isWorkspaceLayout && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.35]"
            style={{
              background:
                "radial-gradient(900px 300px at 12% -10%, rgba(230,149,82,0.30), transparent 60%), radial-gradient(700px 240px at 90% -10%, rgba(96,165,250,0.18), transparent 60%)",
            }}
          />
        )}
        <div
          className={cn(
            "relative mx-auto",
            isWorkspaceLayout
              ? "flex min-h-14 w-full max-w-none items-center gap-4 px-3 sm:px-4"
              : "max-w-[1280px] px-4 pb-4 pt-7 sm:px-6 lg:px-8",
          )}
        >
          <div
            className={cn(
              "flex min-w-0 items-center gap-3",
              isWorkspaceLayout ? "shrink-0" : "mb-4",
            )}
          >
            <span
              className={cn(
                "flex items-center justify-center bg-gradient-to-br from-brand to-brand-strong",
                isWorkspaceLayout
                  ? "size-8 rounded-md"
                  : "size-9 rounded-xl shadow-lg shadow-brand/30",
              )}
            >
              <Folder size={18} className="text-black" />
            </span>
            <div className="min-w-0 flex-1">
              <h1
                className={cn(
                  "truncate font-bold",
                  isWorkspaceLayout ? "max-w-48 text-sm" : "text-2xl tracking-tight",
                )}
              >
                {project?.name ?? t("workspace.projectPage.titleFallback")}
              </h1>
              {!isWorkspaceLayout && (
                <p className="text-xs text-text-muted [overflow-wrap:anywhere]">
                  {project?.repo_path}
                </p>
              )}
            </div>
          </div>
          <nav
            className={cn(
              "flex",
              isWorkspaceLayout ? "min-w-0 flex-1 self-stretch overflow-x-auto" : "flex-wrap gap-2",
            )}
            aria-label="Project sections"
          >
            {navItems.map((item) => {
              const active =
                item.href === workspacesHref
                  ? pathname === workspacesHref
                  : pathname?.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-2 text-sm font-semibold transition-colors",
                    isWorkspaceLayout
                      ? cn(
                          "min-h-14 border-b-2 px-3",
                          active
                            ? "border-brand text-foreground"
                            : "border-transparent text-text-muted hover:border-border-strong hover:text-foreground",
                        )
                      : cn(
                          "min-h-11 rounded-full border px-4 py-2",
                          active
                            ? "border-brand bg-brand/15 text-foreground shadow-[0_8px_24px_rgba(230,149,82,0.12)]"
                            : "border-border-subtle bg-surface-raised/70 text-text-muted hover:text-foreground",
                        ),
                  )}
                >
                  <Icon size={14} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      <div
        className={cn(
          isWorkspaceLayout
            ? "min-h-0 flex-1"
            : "mx-auto max-w-[1280px] space-y-5 px-4 py-6 sm:px-6 lg:px-8",
        )}
      >
        {children}
      </div>
    </div>
  );
}
