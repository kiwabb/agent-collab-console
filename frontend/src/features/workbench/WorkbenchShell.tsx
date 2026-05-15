"use client";

import { AppSidebar } from "@/features/workbench/components/AppSidebar";
import { AppHeader, type BreadcrumbItem } from "@/features/workbench/components/AppHeader";
import { SelectionProvider } from "@/features/workbench/state/SelectionProvider";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";

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
        <div className="h-screen flex bg-background text-foreground">
          <AppSidebar />
          <div className="flex-1 flex flex-col min-w-0">
            <AppHeader breadcrumbs={breadcrumbs} right={headerRight} />
            <main className="flex-1 min-h-0 overflow-auto">{children}</main>
          </div>
        </div>
      </ExecutionProcessesProvider>
    </SelectionProvider>
  );
}
