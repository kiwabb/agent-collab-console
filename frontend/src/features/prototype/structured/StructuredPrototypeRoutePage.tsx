"use client";

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { ProjectShell } from "@/features/projects/ProjectShell";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { getProject } from "@/lib/api/projects";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";

import { StructuredPrototypeStudioPage } from "./StructuredPrototypeStudioPage";

interface Props {
  projectId: string;
}

export function StructuredPrototypeRoutePage({ projectId }: Props) {
  const { addToast } = useToast();
  const { t } = useI18n();
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadProject = useCallback(async () => {
    setLoadError(null);
    try {
      setProject(await getProject(projectId));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("prototype project shell load failed:", error);
      setLoadError(message);
      addToast({
        type: "error",
        title: t("workspace.toast.loadFailed"),
        message,
      });
    }
  }, [addToast, projectId, t]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  return (
    <WorkbenchShell
      breadcrumbs={[
        { label: t("project.nav.workspaces"), href: `/projects/${projectId}` },
        { label: t("project.nav.prototypes"), href: `/projects/${projectId}/prototypes` },
      ]}
    >
      <ProjectShell projectId={projectId} project={project}>
        {loadError && (
          <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-failed-ring bg-failed-bg px-4 py-3 text-sm text-status-failed"
            role="alert"
          >
            <span className="min-w-0 break-words">{loadError}</span>
            <button
              type="button"
              className="min-h-9 rounded-md border border-failed-ring bg-surface-raised px-3 text-xs font-semibold text-foreground hover:bg-surface-hover"
              onClick={() => void loadProject()}
            >
              {t("prototype.structured.retry")}
            </button>
          </div>
        )}
        <StructuredPrototypeStudioPage projectId={projectId} />
      </ProjectShell>
    </WorkbenchShell>
  );
}
