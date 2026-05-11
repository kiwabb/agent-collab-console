"use client";

import { useState } from "react";

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
import { createProject } from "@/lib/api";
import type { Project } from "@/lib/types";

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
              <Input
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/Users/you/code/agent-collab-console"
              />
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
                <Input
                  value={destParent}
                  onChange={(e) => setDestParent(e.target.value)}
                  placeholder="/Users/you/code"
                />
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
