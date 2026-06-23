"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";

import {
  createPrototype,
  getPrototype,
  listPrototypes,
} from "@/lib/api";
import type { Project, Prototype, PrototypeDetail } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { Loader } from "@/components/ui/loader";
import { cn } from "@/lib/utils";

import { PrototypeCanvas } from "./PrototypeCanvas";

interface Props {
  projectId: string;
  project: Project | null;
}

/**
 * Project-level prototype design tool page (PRD 06-23).
 *
 * Layout: thin wrapper that hosts the sidebar (prototype list) and the
 * canvas (PrototypeCanvas). State is local — there's no real-time
 * collaboration channel for this surface, so a single fetch on mount
 * plus imperative refetches after mutations is plenty.
 *
 * Refresh strategy: after `createPrototype` we eagerly insert the new
 * prototype so the sidebar updates without a full refetch, then refetch
 * the list to pick up any server-side derived fields (timestamps).
 */
export function ProjectPrototypesPage({ projectId, project }: Props) {
  const { t } = useI18n();
  const { addToast } = useToast();

  const [prototypes, setPrototypes] = useState<Prototype[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PrototypeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBrief, setDraftBrief] = useState("");

  const refetchList = useCallback(async () => {
    try {
      const list = await listPrototypes(projectId);
      setPrototypes(list);
      return list;
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.toast.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
      return [];
    }
  }, [projectId, addToast, t]);

  // Initial list load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const list = await refetchList();
      if (cancelled) return;
      if (list.length > 0 && !activeId) {
        setActiveId(list[0].id);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refetchList, activeId]);

  // Load detail (prototype + versions) whenever the active selection changes.
  useEffect(() => {
    if (!activeId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getPrototype(activeId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) {
          addToast({
            type: "error",
            title: t("prototype.toast.createFailed"),
            message: err instanceof Error ? err.message : String(err),
          });
          setDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, addToast, t]);

  const handleCreate = useCallback(async () => {
    const title = draftTitle.trim();
    const brief = draftBrief.trim();
    if (!title || !brief) return;
    try {
      const created = await createPrototype(projectId, { title, brief });
      addToast({ type: "success", title: t("prototype.toast.created") });
      setCreating(false);
      setDraftTitle("");
      setDraftBrief("");
      // Optimistic insert so the new prototype appears immediately.
      setPrototypes((prev) => [created, ...(prev ?? [])]);
      setActiveId(created.id);
    } catch (err) {
      addToast({
        type: "error",
        title: t("prototype.toast.createFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, [draftTitle, draftBrief, projectId, addToast, t]);

  const handleVersionsChanged = useCallback(async () => {
    // Re-fetch both list (for current_version chip) and detail (new version row).
    const list = await refetchList();
    if (activeId) {
      try {
        const d = await getPrototype(activeId);
        setDetail(d);
      } catch {
        // The detail fetch may race with the user navigating away;
        // a stale detail is preferable to a noisy toast here.
      }
    }
    if (list.length === 0) setActiveId(null);
  }, [refetchList, activeId]);

  const handlePrototypeDeleted = useCallback(async () => {
    const list = await refetchList();
    if (list.length > 0) setActiveId(list[0].id);
    else setActiveId(null);
    setDetail(null);
  }, [refetchList]);

  return (
    <section className="flex h-full flex-col gap-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">{t("prototype.title")}</h1>
        <p className="text-sm text-text-muted">{t("prototype.subtitle")}</p>
        {project?.repo_path && (
          <p className="font-mono text-[11px] text-text-muted/70">{project.repo_path}</p>
        )}
      </header>

      <div className="grid min-h-[640px] flex-1 grid-cols-[280px_minmax(0,1fr)] gap-4">
        <aside className="flex flex-col gap-2 rounded-xl border border-border-subtle bg-surface-raised/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              {t("prototype.title")}
            </span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setCreating((v) => !v)}
            >
              <Plus size={14} />
              {t("prototype.newTitle")}
            </Button>
          </div>

          {creating && (
            <div className="flex flex-col gap-2 rounded-lg border border-border-subtle bg-surface-base p-2">
              <Input
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder={t("prototype.titlePlaceholder")}
              />
              <Textarea
                rows={3}
                value={draftBrief}
                onChange={(e) => setDraftBrief(e.target.value)}
                placeholder={t("prototype.briefPlaceholder")}
              />
              <div className="flex items-center justify-end gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setCreating(false);
                    setDraftTitle("");
                    setDraftBrief("");
                  }}
                >
                  {t("prototype.createCancel")}
                </Button>
                <Button
                  size="sm"
                  onClick={handleCreate}
                  disabled={!draftTitle.trim() || !draftBrief.trim()}
                >
                  {t("prototype.createButton")}
                </Button>
              </div>
            </div>
          )}

          <div className="flex-1 overflow-auto">
            {prototypes === null ? (
              <div className="flex h-32 items-center justify-center">
                <Loader variant="card" label="Loading…" />
              </div>
            ) : prototypes.length === 0 ? (
              <EmptyState title={t("prototype.empty")} />
            ) : (
              <ul className="flex flex-col gap-1">
                {prototypes.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setActiveId(p.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                        activeId === p.id
                          ? "border-brand bg-brand/15 text-foreground"
                          : "border-transparent bg-surface-base text-text-muted hover:text-foreground",
                      )}
                    >
                      <div className="truncate font-semibold">{p.title}</div>
                      <div className="text-[11px] text-text-muted/80">
                        {p.current_version > 0
                          ? `v${p.current_version}`
                          : t("prototype.noVersionsYet")}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <main className="flex min-h-0 flex-col rounded-xl border border-border-subtle bg-surface-raised/40 p-3">
          {!activeId ? (
            <EmptyState title={t("prototype.empty")} />
          ) : detailLoading || !detail ? (
            <div className="flex h-full items-center justify-center">
              <Loader variant="card" label="Loading…" />
            </div>
          ) : (
            <PrototypeCanvas
              projectId={projectId}
              prototype={detail.prototype}
              versions={detail.versions}
              onVersionsChanged={handleVersionsChanged}
              onPrototypeDeleted={handlePrototypeDeleted}
            />
          )}
        </main>
      </div>
    </section>
  );
}