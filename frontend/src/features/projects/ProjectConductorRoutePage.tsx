"use client";

import { useCallback, useEffect, useState } from "react";

import { getProject } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { ProjectConductorPage } from "@/features/projects/ProjectConductorPage";
import { ProjectShell } from "@/features/projects/ProjectShell";

export function ProjectConductorRoutePage({ projectId }: { projectId: string }) {
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
      <ProjectConductorPage projectId={projectId} />
    </ProjectShell>
  );
}
