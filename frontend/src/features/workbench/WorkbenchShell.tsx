"use client";

import { useCallback, useEffect, useState } from "react";

import { AppSidebar } from "@/features/workbench/components/AppSidebar";
import { AppHeader, type BreadcrumbItem } from "@/features/workbench/components/AppHeader";
import { AppStatusBar } from "@/features/workbench/components/AppStatusBar";
import { AttentionRail } from "@/features/workbench/components/AttentionRail";
import { SelectionProvider } from "@/features/workbench/state/SelectionProvider";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";
import { useBrowserNotifications } from "@/hooks/useBrowserNotifications";
import { getCodexIssues, getCodexTasks, getPendingApprovals } from "@/lib/api";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import {
  deriveAttentionItems,
  type AttentionItem,
} from "@/features/workbench/interaction/interactionState";

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
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);

  const loadAttention = useCallback(async () => {
    const [issues, tasks, approvals] = await Promise.all([
      getCodexIssues(null, null).catch(() => []),
      getCodexTasks(null, null).catch(() => []),
      getPendingApprovals()
        .then((response) => response.pending)
        .catch(() => []),
    ]);
    setAttentionItems(
      deriveAttentionItems({
        issues,
        tasks,
        approvals,
        processes: [],
      }),
    );
  }, []);

  // D3: tab-title + favicon + Notification API for cross-session events.
  // Mounted once at the shell so every route benefits.
  useBrowserNotifications();

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      if (cancelled) return;
      await loadAttention();
    }
    void tick();
    const id = window.setInterval(() => void tick(), 30000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [loadAttention]);

  useBusEventEffect({
    match: busEventMatchers.typeIn(
      "task_status",
      "approval_required",
      "approval_resolved",
      "issue_updated",
      "issue_created",
      "issue_merged",
      "issue_abandoned",
    ),
    onEvent: () => {
      void loadAttention();
    },
    throttleMs: 800,
  });

  return (
    <div className="relative isolate h-screen overflow-hidden bg-background text-foreground">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(circle at top left, rgba(230,149,82,0.12), transparent 30%), radial-gradient(circle at top right, rgba(96,165,250,0.08), transparent 25%), linear-gradient(180deg, rgba(255,255,255,0.02), transparent 24%)",
        }}
      />
      <div className="relative z-10 flex h-full flex-col">
        <AppHeader breadcrumbs={breadcrumbs} right={headerRight} />
        <div className="flex flex-1 min-h-0 gap-3 px-3 pb-3">
          <AppSidebar />
          <main className="enterprise-panel flex-1 min-h-0 overflow-hidden rounded-[30px]">
            <div className="h-full overflow-auto">{children}</div>
          </main>
        </div>
        <AttentionRail items={attentionItems} />
        <AppStatusBar />
      </div>
    </div>
  );
}
