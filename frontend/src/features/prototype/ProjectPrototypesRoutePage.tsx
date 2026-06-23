"use client";

import { useCallback, useEffect, useState } from "react";

import { getProject } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { ProjectShell } from "@/features/projects/ProjectShell";

import { ProjectPrototypesPage } from "./ProjectPrototypesPage";

/**
 * Route-level shell for `/projects/:id/prototypes`. Loads the project
 * record so the breadcrumb/title shows the correct name, then renders
 * the actual page inside the shared `ProjectShell` (which already has
 * the new "Prototypes" nav entry).
 */
export function ProjectPrototypesRoutePage({ projectId }: { projectId: string }) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [project, setProject] = useState<Project | null>(null);

  const load = useCallback(async () => {
    try {
      setProject(await getProject(projectId));
    } catch (err) {
      addToast({
        type: "error",
        title: t("workspace.toast.loadFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ProjectShell projectId={projectId} project={project}>
      <ProjectPrototypesPage projectId={projectId} project={project} />
    </ProjectShell>
  );
}