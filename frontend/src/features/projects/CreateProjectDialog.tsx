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
import { createProject, selectDirectory } from "@/lib/api";
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
  }

  async function handleSubmit() {
    if (submitting) return;
    setSubmitting(true);
    try {
      const project = await createProject({
        name: name.trim(),
        source,
        repo_path: source === "local" ? repoPath.trim() : undefined,
        origin_url: source === "clone" ? originUrl.trim() : undefined,
        dest_parent: source === "clone" ? destParent.trim() : undefined,
      });
      reset();
      onCreated(project);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create project";
      addToast({ type: "error", title: msg });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSelectDirectory(setter: (val: string) => void) {
    try {
      const path = await selectDirectory();
      if (path) {
        setter(path);
        // If name is empty, try to auto-fill it from the folder name
        if (!name.trim()) {
          const parts = path.split(/[/\\]/);
          const lastPart = parts[parts.length - 1] || parts[parts.length - 2]; // handle trailing slash
          if (lastPart) {
            setName(lastPart);
          }
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to select directory";
      addToast({ type: "error", title: msg });
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
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="agent-collab-console" />
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
