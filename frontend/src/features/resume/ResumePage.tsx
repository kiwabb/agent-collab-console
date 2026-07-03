"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  getProjectResume,
  importProjectResumePdf,
  saveProjectResume,
  type ProjectResume,
  type ProjectResumeImport,
} from "@/lib/api";
import { useI18n } from "@/providers/I18nProvider";
import { useSelection } from "@/features/workbench/state/SelectionProvider";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { ResumeEditorPanel } from "./ResumeEditorPanel";
import { ResumePageActions } from "./ResumePageActions";
import { ResumeSidebar } from "./ResumeSidebar";
import { deriveResumeStats } from "./resumeStats";
import { useResumeProjects } from "./useResumeProjects";

type PendingDiscardAction =
  | { type: "switch"; projectId: string | null }
  | { type: "refresh" }
  | { type: "import"; file: File };

export function ResumePage() {
  const { locale, t } = useI18n();
  const { addToast } = useToast();
  const { projectId, setProjectId } = useSelection();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectIdRef = useRef<string | null>(projectId);
  const resumeRequestIdRef = useRef(0);
  const saveRequestIdRef = useRef(0);
  const importRequestIdRef = useRef(0);
  const [resume, setResume] = useState<ProjectResume | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [importDraft, setImportDraft] = useState<ProjectResumeImport | null>(null);
  const [pendingDiscardAction, setPendingDiscardAction] = useState<PendingDiscardAction | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    projectIdRef.current = projectId;
  }, [projectId]);

  const selectProject = useCallback(
    (nextProjectId: string | null) => {
      projectIdRef.current = nextProjectId;
      setProjectId(nextProjectId);
    },
    [setProjectId],
  );

  const {
    activeProject,
    activeProjectIsListed,
    loadProjects,
    loadingProjects,
    projectError,
    projectSelectPlaceholder,
    projects,
  } = useResumeProjects(projectId, selectProject);

  const loadResume = useCallback(async () => {
    const requestId = ++resumeRequestIdRef.current;
    if (!projectId) {
      setResume(null);
      setMarkdown("");
      setImportDraft(null);
      setLoading(false);
      setError(null);
      setActionError(null);
      return;
    }
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const data = await getProjectResume(projectId);
      if (requestId !== resumeRequestIdRef.current) return;
      setResume(data);
      setMarkdown(data.markdown);
      setImportDraft(null);
    } catch (err) {
      if (requestId !== resumeRequestIdRef.current) return;
      setResume(null);
      setMarkdown("");
      setError(err instanceof Error ? err.message : t("resume.loadFailed"));
    } finally {
      if (requestId === resumeRequestIdRef.current) setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    void loadResume();
  }, [loadResume]);

  const stats = useMemo(() => deriveResumeStats(markdown), [markdown]);
  const hasUnsavedChanges = Boolean(resume && resume.markdown !== markdown);
  const updatedAtLabel = useMemo(() => {
    if (!resume?.updated_at) return t("resume.neverSaved");
    const date = new Date(resume.updated_at);
    return Number.isNaN(date.getTime()) ? resume.updated_at : date.toLocaleString(locale);
  }, [locale, resume?.updated_at, t]);

  const requestProjectChange = (nextProjectId: string | null) => {
    if (nextProjectId === projectId) return;
    if (hasUnsavedChanges) {
      setPendingDiscardAction({ type: "switch", projectId: nextProjectId });
      return;
    }
    selectProject(nextProjectId);
  };

  const requestRefresh = () => {
    if (saving || importing) return;
    if (hasUnsavedChanges) {
      setPendingDiscardAction({ type: "refresh" });
      return;
    }
    void loadResume();
  };

  const handleSave = async () => {
    const currentProjectId = projectId;
    if (!currentProjectId || saving || importing) return;
    const saveRequestId = ++saveRequestIdRef.current;
    resumeRequestIdRef.current += 1;
    setLoading(false);
    setActionError(null);
    setSaving(true);
    try {
      const saved = await saveProjectResume(currentProjectId, markdown);
      if (projectIdRef.current !== currentProjectId) return;
      setResume(saved);
      setMarkdown(saved.markdown);
      setImportDraft(null);
      addToast({ type: "success", title: t("resume.toast.saved") });
    } catch (err) {
      if (projectIdRef.current !== currentProjectId) return;
      const message = err instanceof Error ? err.message : t("resume.toast.saveFailed");
      setActionError(message);
      addToast({
        type: "error",
        title: t("resume.toast.saveFailed"),
        message,
      });
    } finally {
      if (saveRequestId === saveRequestIdRef.current) setSaving(false);
    }
  };

  const importPdf = useCallback(
    async (file: File) => {
      const currentProjectId = projectId;
      if (!currentProjectId || saving || importing) return;
      const importRequestId = ++importRequestIdRef.current;
      resumeRequestIdRef.current += 1;
      setLoading(false);
      setError(null);
      setActionError(null);
      setImporting(true);
      try {
        const draft = await importProjectResumePdf(currentProjectId, file);
        if (
          importRequestId !== importRequestIdRef.current ||
          projectIdRef.current !== currentProjectId
        ) {
          return;
        }
        setImportDraft(draft);
        setMarkdown(draft.markdown);
        addToast({ type: "success", title: t("resume.toast.imported") });
      } catch (err) {
        if (
          importRequestId !== importRequestIdRef.current ||
          projectIdRef.current !== currentProjectId
        ) {
          return;
        }
        const message = err instanceof Error ? err.message : t("resume.toast.importFailed");
        setActionError(message);
        addToast({
          type: "error",
          title: t("resume.toast.importFailed"),
          message,
        });
      } finally {
        if (importRequestId === importRequestIdRef.current) setImporting(false);
      }
    },
    [addToast, importing, projectId, saving, t],
  );

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !projectId) return;
    if (hasUnsavedChanges) {
      setPendingDiscardAction({ type: "import", file });
      return;
    }
    void importPdf(file);
  };

  const confirmDiscardAction = () => {
    const action = pendingDiscardAction;
    setPendingDiscardAction(null);
    if (!action) return;
    if (action.type === "switch") {
      selectProject(action.projectId);
      return;
    }
    if (action.type === "refresh") {
      void loadResume();
      return;
    }
    void importPdf(action.file);
  };

  return (
    <>
      <PageFrame
        eyebrow={t("resume.eyebrow")}
        title={t("resume.title")}
        description={t("resume.subtitle")}
        actions={
          <ResumePageActions
            activeProjectIsListed={activeProjectIsListed}
            hasUnsavedChanges={hasUnsavedChanges}
            loading={loading}
            loadingProjects={loadingProjects}
            projectId={projectId}
            projectSelectPlaceholder={projectSelectPlaceholder}
            projects={projects}
            saving={saving}
            importing={importing}
            onProjectChange={requestProjectChange}
            onRefresh={requestRefresh}
            onSave={() => void handleSave()}
          />
        }
        contentClassName="grid min-h-[640px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]"
      >
        <ResumeEditorPanel
          actionError={actionError}
          activeProjectName={activeProject?.name ?? null}
          error={error}
          hasUnsavedChanges={hasUnsavedChanges}
          loading={loading}
          markdown={markdown}
          projectError={projectError}
          projectId={projectId}
          onMarkdownChange={setMarkdown}
          onRetryLoad={() => void loadResume()}
          onRetryProjects={() => void loadProjects()}
        />

        <ResumeSidebar
          fileInputRef={fileInputRef}
          importDraft={importDraft}
          importing={importing}
          projectId={projectId}
          resume={resume}
          saving={saving}
          stats={stats}
          updatedAtLabel={updatedAtLabel}
          onFileChange={handleFileChange}
          onImportClick={() => fileInputRef.current?.click()}
        />
      </PageFrame>

      <ConfirmDialog
        open={pendingDiscardAction !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDiscardAction(null);
        }}
        title={t("resume.discardTitle")}
        description={t("resume.discardBody")}
        confirmText={t("resume.discardConfirm")}
        onConfirm={confirmDiscardAction}
        variant="warning"
      />
    </>
  );
}
