"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { listProjects } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";

interface UseResumeProjectsResult {
  activeProject: Project | null;
  activeProjectIsListed: boolean;
  loadProjects: () => Promise<void>;
  loadingProjects: boolean;
  projectError: string | null;
  projectSelectPlaceholder: string;
  projects: Project[];
}

export function useResumeProjects(
  projectId: string | null,
  selectProject: (projectId: string | null) => void,
): UseResumeProjectsResult {
  const { t } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [projectError, setProjectError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true);
    setProjectError(null);
    try {
      const items = await listProjects();
      setProjects(items);
    } catch (err) {
      setProjects([]);
      setProjectError(err instanceof Error ? err.message : t("resume.projectLoadFailed"));
    } finally {
      setLoadingProjects(false);
    }
  }, [t]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (projects.length === 0) return;
    const firstProject = projects[0];
    if (!firstProject) return;
    if (!projectId || !projects.some((project) => project.id === projectId)) {
      selectProject(firstProject.id);
    }
  }, [projectId, projects, selectProject]);

  const activeProject = useMemo(
    () => projects.find((project) => project.id === projectId) ?? null,
    [projectId, projects],
  );
  const activeProjectIsListed = Boolean(
    projectId && projects.some((project) => project.id === projectId),
  );
  const projectSelectPlaceholder = loadingProjects
    ? t("resume.loadingProjects")
    : projectError
      ? t("resume.projectLoadFailed")
      : t("resume.noProject");

  return {
    activeProject,
    activeProjectIsListed,
    loadProjects,
    loadingProjects,
    projectError,
    projectSelectPlaceholder,
    projects,
  };
}
