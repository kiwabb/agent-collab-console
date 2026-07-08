"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pin, PinOff, Trash2, Undo2, RefreshCcw } from "lucide-react";
import {
  deleteTeamNotesBlock,
  getTeamNotes,
  pinTeamNotesBlock,
  restoreTeamNotesBlock,
  type TeamNoteBlock,
  type TeamNotesResponse,
} from "@/lib/api/knowledge";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { Loader } from "@/components/ui/loader";

interface Props {
  projects: Project[];
  projectId: string;
  onProjectChange: (id: string) => void;
}

export function TeamNotesEditor({ projects, projectId, onProjectChange }: Props) {
  const { t } = useI18n();
  const [data, setData] = useState<TeamNotesResponse | null>(null);
  const [showDeleted, setShowDeleted] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const result = await getTeamNotes(projectId, true);
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    if (!data) return [] as TeamNoteBlock[];
    const sorted = [...data.blocks].sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return (b.timestamp || "").localeCompare(a.timestamp || "");
    });
    return showDeleted ? sorted : sorted.filter((b) => !b.deleted_at);
  }, [data, showDeleted]);

  const handleDelete = async (blockId: string) => {
    if (!projectId) return;
    await deleteTeamNotesBlock(projectId, blockId);
    await load();
  };

  const handleRestore = async (blockId: string) => {
    if (!projectId) return;
    await restoreTeamNotesBlock(projectId, blockId);
    await load();
  };

  const handlePin = async (block: TeamNoteBlock) => {
    if (!projectId) return;
    await pinTeamNotesBlock(projectId, block.block_id, !block.pinned);
    await load();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={projectId}
          onChange={(e) => onProjectChange(e.target.value)}
          className="rounded-md border border-border bg-surface px-2 py-1.5 text-xs"
        >
          {projects.length === 0 && <option value="">{t("teamNotes.noProject")}</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-1 text-xs text-text-muted">
          <input
            type="checkbox"
            checked={showDeleted}
            onChange={(e) => setShowDeleted(e.target.checked)}
          />
          {t("teamNotes.showDeleted")}
        </label>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-xs hover:bg-surface-hover disabled:opacity-50"
        >
          <RefreshCcw size={12} className={loading ? "animate-spin" : ""} />
          {t("teamNotes.refresh")}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {!projectId ? (
          <Empty>{t("teamNotes.selectProject")}</Empty>
        ) : visible.length === 0 ? (
          loading ? (
            <Loader
              variant="card"
              label={t("teamNotes.loading")}
              className="h-64 min-h-0 border-0 bg-transparent"
            />
          ) : (
            <Empty>{t("teamNotes.empty")}</Empty>
          )
        ) : (
          <ul className="flex flex-col gap-2">
            {visible.map((b) => (
              <li
                key={b.block_id}
                className={
                  b.deleted_at
                    ? "rounded-md border border-border bg-surface/50 p-3 opacity-60"
                    : "rounded-md border border-border bg-surface p-3"
                }
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <span>{b.heading || b.block_id}</span>
                      {b.pinned && (
                        <span className="rounded bg-amber-500/15 px-1 py-px text-[10px] text-amber-400">
                          {t("teamNotes.pinned")}
                        </span>
                      )}
                      {b.deleted_at && (
                        <span className="rounded bg-red-500/15 px-1 py-px text-[10px] text-red-400">
                          {t("teamNotes.deleted")}
                        </span>
                      )}
                      {b.distilled && (
                        <span className="rounded bg-blue-500/15 px-1 py-px text-[10px] text-blue-400">
                          {t("teamNotes.distilled")}
                        </span>
                      )}
                    </div>
                    {b.timestamp && (
                      <div className="text-[11px] text-text-muted">{b.timestamp}</div>
                    )}
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-background/40 p-2 font-mono text-xs">
                      {b.body}
                    </pre>
                  </div>
                  <div className="flex flex-col gap-1">
                    {!b.deleted_at ? (
                      <>
                        <IconBtn
                          onClick={() => handlePin(b)}
                          title={b.pinned ? t("teamNotes.unpin") : t("teamNotes.pin")}
                        >
                          {b.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                        </IconBtn>
                        <IconBtn
                          onClick={() => handleDelete(b.block_id)}
                          title={t("teamNotes.softDelete")}
                          intent="danger"
                        >
                          <Trash2 size={13} />
                        </IconBtn>
                      </>
                    ) : (
                      <IconBtn
                        onClick={() => handleRestore(b.block_id)}
                        title={t("teamNotes.restore")}
                      >
                        <Undo2 size={13} />
                      </IconBtn>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function IconBtn({
  children,
  onClick,
  title,
  intent,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title?: string;
  intent?: "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={
        intent === "danger"
          ? "rounded-md border border-border bg-surface p-1 text-red-400 hover:bg-red-500/15"
          : "rounded-md border border-border bg-surface p-1 hover:bg-surface-hover"
      }
    >
      {children}
    </button>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-6 text-sm text-text-muted">
      {children}
    </div>
  );
}
