"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrainCircuit, Folder, Layers } from "lucide-react";

import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

interface Props {
  projectId: string;
  project: Project | null;
  children: React.ReactNode;
}

export function ProjectShell({ projectId, project, children }: Props) {
  const { t } = useI18n();
  const pathname = usePathname();
  const conductorHref = `/projects/${projectId}/conductor`;
  const workspacesHref = `/projects/${projectId}`;
  const navItems = [
    { href: workspacesHref, label: t("project.nav.workspaces"), icon: Layers },
    { href: conductorHref, label: t("project.nav.conductor"), icon: BrainCircuit },
  ];

  return (
    <div className="min-h-full">
      <div className="relative overflow-hidden border-b border-border-subtle">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            background:
              "radial-gradient(900px 300px at 12% -10%, rgba(230,149,82,0.30), transparent 60%), radial-gradient(700px 240px at 90% -10%, rgba(96,165,250,0.18), transparent 60%)",
          }}
        />
        <div className="relative mx-auto max-w-[1280px] px-8 pb-4 pt-7">
          <div className="mb-4 flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-brand-strong shadow-lg shadow-brand/30">
              <Folder size={18} className="text-black" />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-2xl font-bold tracking-tight">
                {project?.name ?? t("workspace.projectPage.titleFallback")}
              </h1>
              <p className="truncate text-[12px] text-text-muted">
                {project?.repo_path}
              </p>
            </div>
          </div>
          <nav className="flex flex-wrap gap-2" aria-label="Project sections">
            {navItems.map((item) => {
              const active = item.href === workspacesHref
                ? pathname === workspacesHref
                : pathname?.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-colors",
                    active
                      ? "border-brand bg-brand/15 text-foreground shadow-[0_8px_24px_rgba(230,149,82,0.12)]"
                      : "border-border-subtle bg-surface-raised/70 text-text-muted hover:text-foreground",
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
      <div className="mx-auto max-w-[1280px] space-y-5 px-8 py-6">
        {children}
      </div>
    </div>
  );
}
