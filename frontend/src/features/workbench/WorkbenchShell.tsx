"use client";

import { AppSidebar } from "@/features/workbench/components/AppSidebar";
import { AppHeader, type BreadcrumbItem } from "@/features/workbench/components/AppHeader";
import { AppStatusBar } from "@/features/workbench/components/AppStatusBar";
import { SelectionProvider } from "@/features/workbench/state/SelectionProvider";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";
import { useBrowserNotifications } from "@/hooks/useBrowserNotifications";

interface Props {
  children: React.ReactNode;
  breadcrumbs?: BreadcrumbItem[];
  headerRight?: React.ReactNode;
  workspaceId?: string | null;
}

export function WorkbenchShell({ children, breadcrumbs, headerRight, workspaceId }: Props) {
  return (
    <SelectionProvider initial={{ workspaceId: workspaceId ?? undefined }}>
      <ExecutionProcessesProvider workspaceId={workspaceId ?? null}>
        <WorkbenchInner
          breadcrumbs={breadcrumbs}
          headerRight={headerRight}
        >
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
  breadcrumbs?: BreadcrumbItem[];
  headerRight?: React.ReactNode;
}) {
  // D3: tab-title + favicon + Notification API for cross-session events.
  // Mounted once at the shell so every route benefits.
  useBrowserNotifications();
  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <AppHeader breadcrumbs={breadcrumbs} right={headerRight} />
      <div className="flex-1 min-h-0 flex">
        <AppSidebar />
        <main className="flex-1 min-h-0 overflow-auto">{children}</main>
      </div>
      <AppStatusBar />
    </div>
  );
}
