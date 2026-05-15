"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { ChevronRight, FolderGit2, Home, Settings, Users, ChevronDown } from "lucide-react";
import { listProjects, getWorkspaces } from "@/lib/api";
import type { Project, Workspace } from "@/lib/types";
import { useSelection } from "@/features/workbench/state/SelectionProvider";
import { cn } from "@/lib/utils";

export function AppSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { projectId, workspaceId, setProjectId, setWorkspaceId } = useSelection();
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);

  useEffect(() => {
    void listProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    if (!projectId) {
      setWorkspaces([]);
      return;
    }
    void getWorkspaces(projectId)
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));
  }, [projectId]);

  const currentProject = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId]);

  return (
    <aside className="w-60 shrink-0 h-full border-r border-border-subtle bg-surface flex flex-col">
      <div className="px-3 pt-3 pb-2">
        <button
          type="button"
          onClick={() => setProjectMenuOpen((v) => !v)}
          className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-surface-raised border border-border-subtle hover:border-border-strong text-left"
        >
          <span className="flex items-center gap-2 min-w-0">
            <FolderGit2 size={14} className="text-text-muted shrink-0" />
            <span className="truncate text-sm font-semibold">
              {currentProject ? currentProject.name : "Select project"}
            </span>
          </span>
          <ChevronDown size={14} className="text-text-muted shrink-0" />
        </button>
        {projectMenuOpen && (
          <div className="mt-1 max-h-64 overflow-auto rounded-lg border border-border-subtle bg-surface-raised shadow-lg">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setProjectId(p.id);
                  setWorkspaceId(null);
                  setProjectMenuOpen(false);
                  router.push(`/projects/${p.id}`);
                }}
                className={cn(
                  "w-full text-left px-3 py-2 text-sm hover:bg-surface-hover",
                  p.id === projectId && "text-brand font-semibold"
                )}
              >
                <div className="truncate">{p.name}</div>
                <div className="truncate text-[10px] text-text-muted">{p.repo_path}</div>
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setProjectMenuOpen(false);
                router.push("/projects");
              }}
              className="w-full text-left px-3 py-2 text-xs text-text-muted hover:bg-surface-hover border-t border-border-subtle"
            >
              Manage projects…
            </button>
          </div>
        )}
      </div>

      <div className="px-3 pb-2 text-[10px] font-black uppercase tracking-widest text-text-muted">
        Workspaces
      </div>
      <div className="px-2 flex-1 overflow-auto">
        {workspaces.length === 0 && (
          <div className="px-3 py-2 text-xs text-text-muted">No workspaces yet</div>
        )}
        {workspaces.map((ws) => {
          const active = ws.id === workspaceId;
          return (
            <button
              key={ws.id}
              type="button"
              onClick={() => {
                setWorkspaceId(ws.id);
                router.push(`/workspaces/${ws.id}`);
              }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors",
                active ? "bg-brand/10 text-brand font-semibold" : "hover:bg-surface-hover"
              )}
            >
              <ChevronRight size={12} className={cn("shrink-0", active ? "text-brand" : "text-text-muted")} />
              <span className="truncate">{ws.title || ws.id.slice(0, 8)}</span>
            </button>
          );
        })}
      </div>

      <div className="border-t border-border-subtle p-2 flex flex-col gap-1">
        <SideLink href="/" icon={<Home size={14} />} label="Workbench" active={pathname === "/"} />
        <SideLink href="/projects" icon={<FolderGit2 size={14} />} label="Projects" active={pathname.startsWith("/projects")} />
        <SideLink href="/agents" icon={<Users size={14} />} label="Agents" active={pathname.startsWith("/agents")} />
        <SideLink href="/settings" icon={<Settings size={14} />} label="Settings" active={pathname.startsWith("/settings")} />
      </div>
    </aside>
  );
}

function SideLink({
  href,
  icon,
  label,
  active,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
}) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.push(href)}
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors",
        active ? "bg-surface-raised text-foreground font-semibold" : "text-text-muted hover:bg-surface-hover hover:text-foreground"
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
