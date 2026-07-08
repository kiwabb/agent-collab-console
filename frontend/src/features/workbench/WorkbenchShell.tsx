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
  workspaceId?: string | null | undefined;
  issueId?: string | null | undefined;
}

export function WorkbenchShell({
  children,
  breadcrumbs,
  headerRight,
  workspaceId,
  issueId,
}: Props) {
  return (
    <SelectionProvider initial={{ workspaceId: workspaceId ?? null, issueId: issueId ?? null }}>
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
    <div className="relative isolate h-dvh overflow-hidden bg-background text-foreground">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(circle at top left, rgba(230,149,82,0.12), transparent 30%), radial-gradient(circle at top right, rgba(96,165,250,0.08), transparent 25%), linear-gradient(180deg, rgba(255,255,255,0.02), transparent 24%)",
        }}
      />
      <div className="relative z-10 flex h-full flex-col">
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
            <div className="absolute inset-y-2 left-2 w-72 max-w-[calc(100vw-1rem)]">
              <AppSidebar />
            </div>
          </div>
        )}
        <div className="flex min-h-0 flex-1 gap-0 px-2 pb-2 sm:px-3 sm:pb-3 lg:gap-3">
          <div className="hidden h-full shrink-0 lg:block">
            <AppSidebar />
          </div>
          <main className="enterprise-panel min-w-0 flex-1 overflow-hidden rounded-[22px] lg:rounded-[30px]">
            <div className="h-full overflow-auto">{children}</div>
          </main>
        </div>
        <AppStatusBar />
      </div>
    </div>
  );
}
