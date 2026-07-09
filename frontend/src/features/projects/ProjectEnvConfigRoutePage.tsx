"use client";

import { useCallback, useEffect, useState } from "react";

import { getProject } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { ProjectShell } from "@/features/projects/ProjectShell";

import { ProjectEnvConfigPage } from "./ProjectEnvConfigPage";

/**
 * Route-level shell for `/projects/:id/env`. Loads the project record for
 * the breadcrumb/title, then renders the env config page inside
 * `ProjectShell`.
 */
export function ProjectEnvConfigRoutePage({ projectId }: { projectId: string }) {
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
        message: String(err),
      });
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <ProjectShell projectId={projectId} project={project}>
      <ProjectEnvConfigPage projectId={projectId} />
    </ProjectShell>
  );
}