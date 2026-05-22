"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  ChevronRight,
  ChevronDown,
  CircleDot,
  Inbox,
  CheckCircle2,
  FileBox,
  Folder,
  Settings,
  Command,
  Users,
  ChevronsUpDown,
  Library,
} from "lucide-react";
import { getCodexIssues, getWorkspaces, listProjects } from "@/lib/api";
import type { CodexIssue, Project, Workspace } from "@/lib/types";
import { useSelection } from "@/features/workbench/state/SelectionProvider";
import { cn } from "@/lib/utils";
import { useDataEvent, emitDataEvent } from "@/lib/dataEvents";
import { workspaceLabel } from "@/lib/workspaceLabel";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuGroup,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";

/**
 * Console v2 reference sidebar:
 *
 *   WORKSPACE
 *     ○ Inbox          3
 *     ◆ Issues         7   ← active row (orange dot + bg)
 *     ○ Approvals      2
 *     ◐ Artifacts
 *
 *   SESSIONS
 *     ▶ Auth refactor
 *     ▼ Console v2          ← expanded
 *         · planning
 *         ● development     ← active sub-item
 *         · testing
 *
 *     ⚙ Settings    ⌘ Shortcuts
 */
export function AppSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useI18n();
  const { projectId, workspaceId, issueId, setProjectId, setWorkspaceId } = useSelection();

  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  // Map workspaceId → issues (loaded lazily on expand)
  const [issuesByWs, setIssuesByWs] = useState<Record<string, CodexIssue[]>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const refreshProjects = useCallback(() => {
    void listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  const refreshWorkspaces = useCallback(() => {
    if (!projectId) {
      setWorkspaces([]);
      return;
    }
    void getWorkspaces(projectId).then(setWorkspaces).catch(() => setWorkspaces([]));
  }, [projectId]);

  useEffect(refreshProjects, [refreshProjects]);
  useEffect(refreshWorkspaces, [refreshWorkspaces]);

  // Re-fetch when other parts of the app create/edit/delete a workspace or
  // project. Without this the sidebar count drifts out of sync with whatever
  // the page currently shows.
  useDataEvent("workspaces:changed", refreshWorkspaces);
  useDataEvent("projects:changed", refreshProjects);
  useDataEvent("issues:changed", () => {
    // Drop the cache so the next expand refetches; cheaper than refetching
    // every open workspace's issue list eagerly.
    setIssuesByWs({});
  });

  // Backend-driven sidebar refresh. The sidebar always lives inside
  // WorkbenchShell — when a workspace is selected we get per-workspace WS
  // events, otherwise we get the global WS stream. Either way the bus
  // surfaces session_*/project_*/issue_* events.
  useBusEventEffect({
    match: busEventMatchers.typeIn(
      "session_created",
      "session_updated",
      "session_deleted",
    ),
    onEvent: () => {
      refreshWorkspaces();
      emitDataEvent("workspaces:changed");
    },
    throttleMs: 500,
  });
  useBusEventEffect({
    match: busEventMatchers.typeIn("issue_created", "issue_deleted", "issue_updated", "issue_merged", "issue_abandoned"),
    onEvent: () => {
      // Bust the per-workspace issue cache so the next render fetches fresh
      // status badges; also bump count totals.
      setIssuesByWs({});
      emitDataEvent("issues:changed");
    },
    throttleMs: 500,
  });

  // Also refresh whenever the route changes — the user may have arrived here
  // from a page that mutated state without dispatching the event.
  useEffect(() => {
    refreshWorkspaces();
  }, [pathname, refreshWorkspaces]);

  // Auto-pick the first project if none selected — keeps sidebar populated.
  useEffect(() => {
    if (!projectId && projects.length > 0) setProjectId(projects[0].id);
  }, [projectId, projects, setProjectId]);

  // Auto-expand current workspace
  useEffect(() => {
    if (workspaceId && !expanded[workspaceId]) {
      setExpanded((p) => ({ ...p, [workspaceId]: true }));
    }
  }, [workspaceId, expanded]);

  const ensureIssuesLoaded = useCallback(
    async (wsId: string) => {
      if (issuesByWs[wsId]) return;
      try {
        const issues = await getCodexIssues(wsId);
        setIssuesByWs((p) => ({ ...p, [wsId]: issues }));
      } catch {
        setIssuesByWs((p) => ({ ...p, [wsId]: [] }));
      }
    },
    [issuesByWs],
  );

  const toggleWorkspace = useCallback(
    (wsId: string) => {
      setExpanded((p) => {
        const next = { ...p, [wsId]: !p[wsId] };
        if (next[wsId]) void ensureIssuesLoaded(wsId);
        return next;
      });
    },
    [ensureIssuesLoaded],
  );

  // Counters for the WORKSPACE section. We don't yet have a real backend for
  // these, but it's easy to wire to runs/approvals once that surfaces.
  const counts = useMemo(() => {
    const allIssues = Object.values(issuesByWs).flat();
    return {
      inbox: allIssues.filter((i) => i.status === "open" || i.status === "in_progress").length,
      myTasks: allIssues.length,
      approvals: allIssues.filter((i) => i.status === "review" || i.status === "awaiting_approval").length,
    };
  }, [issuesByWs]);

  return (
    <aside className="w-60 shrink-0 h-full border-r border-border-subtle bg-surface flex flex-col">
      {/* PROJECT SELECTOR */}
      <div className="p-2 border-b border-border-subtle mb-1">
        <DropdownMenu>
          <DropdownMenuTrigger className="w-full flex items-center gap-2.5 p-1.5 rounded-md hover:bg-surface-hover transition-colors text-left outline-none cursor-default">
            <div className="size-6 shrink-0 rounded bg-brand/20 flex items-center justify-center text-brand font-bold text-xs uppercase">
              {(projects.find(p => p.id === projectId)?.name || "P").charAt(0)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold truncate text-foreground">
                {projects.find(p => p.id === projectId)?.name || t("workbench.projectSwitcher")}
              </div>
              <div className="text-[10px] text-text-muted truncate">
                {t("workbench.changeProject")}
              </div>
            </div>
            <ChevronsUpDown size={14} className="text-text-muted shrink-0" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("workbench.projectSwitcher")}</DropdownMenuLabel>
              {projects.map(p => (
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
              {projects.length === 0 && (
                <div className="px-2 py-1.5 text-xs text-text-muted">{t("projects.empty")}</div>
              )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push("/projects")}>
              <Settings size={14} className="mr-2 opacity-50" />
              {t("workbench.manageProjects")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* WORKSPACE section */}
      <SectionHeader label={t("sidebar.workspace")} />
      <div className="px-2 flex flex-col gap-0.5">
        <NavRow
          icon={<Inbox size={13} />}
          label={t("sidebar.inbox")}
          count={counts.inbox || undefined}
          active={pathname === "/"}
          onClick={() => router.push("/")}
        />
        <NavRow
          icon={<Folder size={13} />}
          label={t("sidebar.workspaces")}
          count={workspaces.length || undefined}
          active={pathname.startsWith("/projects")}
          onClick={() => {
            if (projectId) router.push(`/projects/${projectId}`);
            else if (projects[0]) router.push(`/projects/${projects[0].id}`);
            else router.push("/projects");
          }}
        />
        <NavRow
          icon={<CircleDot size={13} className="text-brand" />}
          label={t("sidebar.myTasks")}
          count={counts.myTasks || undefined}
          active={pathname.startsWith("/workspaces") || pathname.startsWith("/issues")}
          onClick={() => {
            if (workspaces[0]) router.push(`/workspaces/${workspaces[0].id}`);
            else router.push("/projects");
          }}
          highlightActive
        />
        <NavRow
          icon={<CheckCircle2 size={13} />}
          label={t("sidebar.approvals")}
          count={counts.approvals || undefined}
          active={pathname.startsWith("/approvals")}
          onClick={() => router.push("/approvals")}
        />
        <NavRow
          icon={<FileBox size={13} />}
          label={t("sidebar.artifacts")}
          active={pathname.startsWith("/artifacts")}
          onClick={() => router.push("/artifacts")}
        />
        <NavRow
          icon={<Library size={13} />}
          label={t("sidebar.knowledge")}
          active={pathname.startsWith("/knowledge")}
          onClick={() => router.push("/knowledge")}
        />
        <NavRow
          icon={<Users size={13} />}
          label={t("sidebar.agents")}
          active={pathname.startsWith("/agents")}
          onClick={() => router.push("/agents")}
        />
      </div>

      {/* SESSIONS section */}
      <SectionHeader label={t("sidebar.sessions")} className="mt-3" />
      <div className="px-2 flex-1 overflow-auto flex flex-col gap-0.5">
        {workspaces.length === 0 && (
          <div className="px-3 py-2 text-xs text-text-muted">{t("sidebar.noSessionsYet")}</div>
        )}
        {workspaces.map((ws) => {
          const isOpen = !!expanded[ws.id];
          const isActiveWs = ws.id === workspaceId;
          const issues = issuesByWs[ws.id] ?? [];
          return (
            <div key={ws.id}>
              <div
                className={cn(
                  "w-full flex items-center px-2 py-1.5 rounded-md text-[13px] transition-colors",
                  isActiveWs
                    ? "text-foreground font-semibold"
                    : "text-text-secondary hover:text-foreground hover:bg-surface-hover",
                )}
              >
                <button
                  type="button"
                  aria-label={isOpen ? "Collapse" : "Expand"}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleWorkspace(ws.id);
                  }}
                  className="size-4 flex items-center justify-center shrink-0 text-text-muted hover:text-foreground"
                >
                  {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setWorkspaceId(ws.id);
                    router.push(`/workspaces/${ws.id}`);
                  }}
                  className="flex-1 ml-1 truncate text-left"
                  title={ws.title || ws.id}
                >
                  {workspaceLabel(ws)}
                </button>
              </div>
              {isOpen && (
                <div className="pl-5 flex flex-col gap-0.5 mt-0.5 mb-1">
                  {issues.length === 0 && (
                    <div className="px-2 py-1 text-[11px] text-text-muted">{t("sidebar.empty")}</div>
                  )}
                  {issues.slice(0, 8).map((issue) => {
                    const active = issue.id === issueId;
                    return (
                      <button
                        key={issue.id}
                        type="button"
                        onClick={() => router.push(`/issues/${issue.id}`)}
                        className={cn(
                          "flex items-center gap-1.5 px-2 py-1 rounded-md text-[12px] transition-colors text-left",
                          active
                            ? "text-foreground font-medium"
                            : "text-text-muted hover:text-foreground hover:bg-surface-hover",
                        )}
                        title={issue.title}
                      >
                        <span
                          className={cn(
                            "size-1.5 rounded-full shrink-0",
                            issue.status === "completed" && "bg-status-done",
                            issue.status === "in_progress" && "bg-status-running",
                            issue.status === "failed" && "bg-status-failed",
                            (issue.status === "open" || !issue.status) && "bg-status-queued",
                          )}
                        />
                        <span className="truncate">{issue.title || issue.id.slice(0, 8)}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Bottom strip */}
      <div className="border-t border-border-subtle p-2 flex flex-col gap-0.5">
        <NavRow
          icon={<Settings size={13} />}
          label={t("sidebar.settings")}
          active={pathname.startsWith("/settings")}
          onClick={() => router.push("/settings")}
        />
        <NavRow
          icon={<Command size={13} />}
          label={t("sidebar.helpAndShortcuts")}
          active={pathname.startsWith("/help")}
          onClick={() => router.push("/help")}
        />
      </div>
    </aside>
  );
}

function SectionHeader({ label, className }: { label: string; className?: string }) {
  return (
    <div
      className={cn(
        "px-4 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted",
        className,
      )}
    >
      {label}
    </div>
  );
}

function NavRow({
  icon,
  label,
  count,
  active,
  onClick,
  highlightActive,
}: {
  icon: React.ReactNode;
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  /** When true, active state uses brand bg highlight (the "Issues" treatment). */
  highlightActive?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative group w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-[13px] transition-colors",
        active
          ? highlightActive
            ? "text-brand-strong font-medium"
            : "text-foreground font-medium bg-surface-hover"
          : "text-text-secondary hover:text-foreground hover:bg-surface-hover",
      )}
      style={
        active && highlightActive
          ? { background: "var(--color-brand-bg)" }
          : undefined
      }
    >
      {active && highlightActive && (
        <span
          aria-hidden
          className="absolute -left-2 top-1.5 bottom-1.5 w-[2px] rounded-full bg-brand"
        />
      )}
      <span
        className={cn(
          "shrink-0",
          active && highlightActive ? "text-brand-strong" : "text-text-muted",
        )}
      >
        {icon}
      </span>
      <span className="flex-1 truncate text-left">{label}</span>
      {count !== undefined && (
        <span
          className={cn(
            "text-[11px] font-mono tabular-nums shrink-0 px-1.5 leading-[18px] min-w-[18px] text-center rounded",
            active && highlightActive
              ? "text-brand-strong border border-brand-ring/40 bg-transparent"
              : "text-text-muted border border-border-muted bg-surface-input",
          )}
          style={
            active && highlightActive
              ? { borderColor: "var(--color-brand-ring)" }
              : undefined
          }
        >
          {count}
        </span>
      )}
    </button>
  );
}
