"use client";

import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { createProject, selectDirectory } from "@/lib/api/projects";
import { emitDataEvent } from "@/lib/dataEvents";
import type { Project } from "@/lib/types";
import { FolderOpen } from "lucide-react";

type Source = "local" | "clone";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (project: Project) => void;
}

export function CreateProjectDialog({ open, onClose, onCreated }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [source, setSource] = useState<Source>("local");
  const [name, setName] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [originUrl, setOriginUrl] = useState("");
  const [destParent, setDestParent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Guards against double-firing the native directory picker: the OS dialog is
  // async, and a second click while it's open spawns a second picker.
  const [selectingDir, setSelectingDir] = useState(false);
  // Tracks whether the current name was auto-derived from a picked folder (vs
  // typed by the user). Lets us refresh the name when the user re-picks a
  // different folder, without clobbering a name they typed themselves.
  const [nameAutoFilled, setNameAutoFilled] = useState(false);

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      reset();
    }
  }, [open]);

  function reset() {
    setName("");
    setRepoPath("");
    setOriginUrl("");
    setDestParent("");
    setSource("local");
    setNameAutoFilled(false);
  }

  async function handleSubmit() {
    if (submitting) return;
    setSubmitting(true);
    try {
      const project = await createProject({
        name: name.trim(),
        source,
        ...(source === "local" ? { repo_path: repoPath.trim() } : {}),
        ...(source === "clone"
          ? { origin_url: originUrl.trim(), dest_parent: destParent.trim() }
          : {}),
      });
      emitDataEvent("projects:changed");
      reset();
      addToast({ type: "success", title: t("projects.toastLoaded") });
      onCreated(project);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create project";
      addToast({ type: "error", title: msg });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSelectDirectory(setter: (val: string) => void) {
    if (selectingDir) return;
    setSelectingDir(true);
    try {
      const path = await selectDirectory();
      if (path) {
        setter(path);
        // Auto-fill the name from the folder when it's empty OR was itself
        // auto-filled from a previous pick — so re-picking a different folder
        // refreshes the name, but a name the user typed by hand is kept.
        if (!name.trim() || nameAutoFilled) {
          const parts = path.split(/[/\\]/);
          const lastPart = parts[parts.length - 1] || parts[parts.length - 2]; // handle trailing slash
          if (lastPart) {
            setName(lastPart);
            setNameAutoFilled(true);
          }
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to select directory";
      addToast({ type: "error", title: msg });
    } finally {
      setSelectingDir(false);
    }
  }

  const canSubmit =
    !!name.trim() &&
    (source === "local" ? !!repoPath.trim() : !!originUrl.trim() && !!destParent.trim());

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? onClose() : null)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("projects.create")}</DialogTitle>
          <DialogDescription>
            {source === "local" ? t("projects.fromLocalHelp") : t("projects.fromCloneHelp")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2">
          <Button
            type="button"
            variant={source === "local" ? "default" : "outline"}
            size="sm"
            onClick={() => setSource("local")}
          >
            {t("projects.fromLocal")}
          </Button>
          <Button
            type="button"
            variant={source === "clone" ? "default" : "outline"}
            size="sm"
            onClick={() => setSource("clone")}
          >
            {t("projects.fromClone")}
          </Button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium block mb-1">{t("projects.name")}</label>
            <Input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameAutoFilled(false);
              }}
              placeholder="agent-collab-console"
            />
          </div>
          {source === "local" ? (
            <div>
              <label className="text-xs font-medium block mb-1">{t("projects.repoPath")}</label>
              <div className="flex gap-2">
                <Input
                  value={repoPath}
                  onChange={(e) => setRepoPath(e.target.value)}
                  placeholder="/Users/you/code/agent-collab-console"
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => handleSelectDirectory(setRepoPath)}
                  disabled={selectingDir}
                  title={t("projects.browse")}
                >
                  <FolderOpen className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div>
                <label className="text-xs font-medium block mb-1">{t("projects.originUrl")}</label>
                <Input
                  value={originUrl}
                  onChange={(e) => setOriginUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo.git"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">{t("projects.destParent")}</label>
                <div className="flex gap-2">
                  <Input
                    value={destParent}
                    onChange={(e) => setDestParent(e.target.value)}
                    placeholder="/Users/you/code"
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => handleSelectDirectory(setDestParent)}
                    disabled={selectingDir}
                    title={t("projects.browse")}
                  >
                    <FolderOpen className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} type="button">
            {t("projects.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit || submitting} type="button">
            {t("projects.createSubmit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
