"use client";

import { useCallback, useEffect, useState } from "react";

import { getProject } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { ProjectShell } from "@/features/projects/ProjectShell";

import { PrototypePlanReviewPage } from "./PrototypePlanReviewPage";

interface Props {
  projectId: string;
  planId: string;
}

export function PrototypePlanRoutePage({ projectId, planId }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const load = useCallback(async () => {
    try {
      setProject(await getProject(projectId));
    } catch (err) {
      console.error("prototype plan project load failed:", err);
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
      <PrototypePlanReviewPage projectId={projectId} planId={planId} />
    </ProjectShell>
  );
}
