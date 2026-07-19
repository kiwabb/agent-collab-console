"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { AppSidebar } from "@/features/workbench/components/AppSidebar";
import { AppHeader, type BreadcrumbItem } from "@/features/workbench/components/AppHeader";
import { AppStatusBar } from "@/features/workbench/components/AppStatusBar";
import { SelectionProvider } from "@/features/workbench/state/SelectionProvider";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";
import { useBrowserNotifications } from "@/hooks/useBrowserNotifications";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  children: React.ReactNode;
  breadcrumbs?: BreadcrumbItem[] | undefined;
  headerRight?: React.ReactNode | undefined;
  projectId?: string | null | undefined;
  workspaceId?: string | null | undefined;
  issueId?: string | null | undefined;
}

export function WorkbenchShell({
  children,
  breadcrumbs,
  headerRight,
  projectId,
  workspaceId,
  issueId,
}: Props) {
  const initialSelection = {
    ...(projectId !== undefined ? { projectId: projectId ?? null } : {}),
    workspaceId: workspaceId ?? null,
    issueId: issueId ?? null,
  };

  return (
    <SelectionProvider initial={initialSelection}>
      <ExecutionProcessesProvider workspaceId={workspaceId ?? null}>
        <WorkbenchInner breadcrumbs={breadcrumbs} headerRight={headerRight}>
          {children}
        </WorkbenchInner>
      </ExecutionProcessesProvider>
    </SelectionProvider>
  );
}

function WorkbenchInner({
  children,
  breadcrumbs,
  headerRight,
}: {
  children: React.ReactNode;
  breadcrumbs?: BreadcrumbItem[] | undefined;
  headerRight?: React.ReactNode | undefined;
}) {
  const pathname = usePathname();
  const { t } = useI18n();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // D3: tab-title + favicon + Notification API for cross-session events.
  // Mounted once at the shell so every route benefits.
  useBrowserNotifications();

  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  return (
    <div className="h-dvh overflow-hidden bg-background text-foreground">
      <div className="flex h-full flex-col">
        <AppHeader
          breadcrumbs={breadcrumbs}
          onMenuClick={() => setSidebarOpen(true)}
          right={headerRight}
        />
        {sidebarOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button
              type="button"
              aria-label={t("ui.closeNavigation")}
              className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
              onClick={() => setSidebarOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-72 max-w-[calc(100vw-2rem)] border-r border-border-subtle bg-surface shadow-xl">
              <AppSidebar />
            </div>
          </div>
        )}
        <div className="flex min-h-0 min-w-0 flex-1">
          <div className="hidden h-full shrink-0 border-r border-border-subtle lg:block">
            <AppSidebar />
          </div>
          <main className="min-w-0 flex-1 overflow-hidden bg-background">
            <div className="h-full overflow-auto">{children}</div>
          </main>
        </div>
        <AppStatusBar />
      </div>
    </div>
  );
}
