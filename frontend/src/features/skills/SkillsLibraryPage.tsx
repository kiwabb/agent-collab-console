"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  Trash2,
  Pencil,
  Upload,
  Copy,
  ExternalLink,
  Search,
  FileText,
  FileSpreadsheet,
  X,
  Languages,
  ChevronDown,
} from "lucide-react";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import {
  createSkill,
  createSkillCategory,
  deleteSkill,
  deleteSkillCategory,
  fetchSkillContent,
  importSkillsExcel,
  importSkillsMarkdown,
  listSkillCategories,
  listSkills,
  translateSkillContent,
  updateSkill,
} from "@/lib/api";
import type { CreateSkillRequest, Skill, SkillImportResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { SkillMarkdown } from "./SkillMarkdown";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

const UNCATEGORIZED = "__uncategorized__";

export function SkillsLibraryPage() {
  const { addToast } = useToast();
  const { t } = useI18n();

  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [focusId, setFocusId] = useState<string | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Skill | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Skill | null>(null);
  const [busy, setBusy] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [newCatInput, setNewCatInput] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const reloadCategories = useCallback(async () => {
    try {
      const cats = await listSkillCategories();
      setAvailableCategories(cats);
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    void reloadCategories();
  }, [reloadCategories]);

  const commitNewCategory = async () => {
    const name = (newCatInput ?? "").trim();
    setNewCatInput(null);
    if (!name) return;
    try {
      await createSkillCategory(name);
      addToast({ type: "success", title: t("skills.toast.categoryAdded"), message: name });
      await reloadCategories();
    } catch (err) {
      addToast({
        type: "error",
        title: t("skills.toast.categoryAddFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const removeCategory = async (name: string) => {
    try {
      await deleteSkillCategory(name);
      addToast({ type: "success", title: t("skills.toast.categoryRemoved"), message: name });
      if (activeCategory === name) setActiveCategory(null);
      await reloadCategories();
    } catch (err) {
      addToast({
        type: "error",
        title: t("skills.toast.categoryRemoveFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const handleDropOnGroup = async (groupKey: string, skillId: string) => {
    setDropTarget(null);
    setDraggingId(null);
    if (!skillId) return;
    const cur = skills.find((s) => s.id === skillId);
    if (!cur) return;
    const targetCat = groupKey === UNCATEGORIZED ? "" : groupKey;
    if ((cur.category ?? "") === targetCat) return;
    try {
      await updateSkill(skillId, { category: targetCat });
      addToast({
        type: "success",
        title: t("skills.toast.moved"),
        message: targetCat || t("skills.category.uncategorized"),
      });
      await reload();
    } catch (err) {
      addToast({
        type: "error",
        title: t("skills.toast.moveFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const reload = useCallback(async () => {
    try {
      const rows = await listSkills();
      setSkills(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const categories = useMemo(() => {
    // Backend returns the union of (skill.category values) ∪ (user-defined
    // empty categories), so we just use that list verbatim.
    const set = new Set<string>(availableCategories);
    for (const s of skills) {
      if (s.category) set.add(s.category);
    }
    return Array.from(set).sort();
  }, [skills, availableCategories]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return skills.filter((s) => {
      if (activeCategory && s.category !== activeCategory) return false;
      if (!q) return true;
      const hay = [
        s.name,
        s.description ?? "",
        s.link,
        s.category ?? "",
        (s.tags ?? []).join(" "),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [skills, search, activeCategory]);

  const grouped = useMemo(() => {
    const map = new Map<string, Skill[]>();
    // Seed every known category (including empty user-defined ones) so the
    // user has a drop target even before any skill lives there.
    for (const cat of availableCategories) {
      map.set(cat, []);
    }
    for (const s of filtered) {
      const key = s.category?.trim() || UNCATEGORIZED;
      const arr = map.get(key);
      if (arr) arr.push(s);
      else map.set(key, [s]);
    }
    const entries = Array.from(map.entries()).filter(([key, items]) => {
      if (key === UNCATEGORIZED) return items.length > 0;
      if (items.length > 0) return true;
      // Empty user-defined category — only hide it when an unrelated chip filter is active.
      return activeCategory === null || activeCategory === key;
    });
    return entries.sort((a, b) => {
      if (a[0] === UNCATEGORIZED) return 1;
      if (b[0] === UNCATEGORIZED) return -1;
      return a[0].localeCompare(b[0]);
    });
  }, [filtered, availableCategories, activeCategory]);

  const focused = useMemo(
    () => filtered.find((s) => s.id === focusId) ?? filtered[0] ?? null,
    [filtered, focusId],
  );

  useEffect(() => {
    if (focused && focusId !== focused.id) {
      setFocusId(focused.id);
    }
  }, [focused, focusId]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedSkills = useMemo(
    () => skills.filter((s) => selectedIds.has(s.id)),
    [skills, selectedIds],
  );

  const handleCopyText = async () => {
    if (selectedSkills.length === 0) return;
    const text = selectedSkills.map((s) => `${s.name}\t${s.link}`).join("\n");
    await navigator.clipboard.writeText(text);
    addToast({ type: "success", title: t("skills.toast.copiedText"), message: `${selectedSkills.length}` });
  };

  const handleCopyJson = async () => {
    if (selectedSkills.length === 0) return;
    const payload = selectedSkills.map((s) => ({ name: s.name, link: s.link }));
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    addToast({ type: "success", title: t("skills.toast.copiedJson"), message: `${selectedSkills.length}` });
  };

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) return;
    setBusy(true);
    try {
      await deleteSkill(confirmDelete.id);
      addToast({ type: "success", title: t("skills.toast.deleted") });
      setConfirmDelete(null);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(confirmDelete.id);
        return next;
      });
      await reload();
    } catch (err) {
      addToast({
        type: "error",
        title: t("skills.toast.deleteFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }, [confirmDelete, addToast, reload, t]);

  return (
    <WorkbenchShell breadcrumbs={[{ label: t("skills.pageTitle") }]}>
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border-subtle flex items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("skills.pageTitle")}</h1>
            <p className="text-[12px] text-text-muted mt-1">{t("skills.pageSubtitle")}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setImportOpen(true)}
              className="gap-1"
            >
              <Upload size={14} /> {t("skills.btn.import")}
            </Button>
            <Button
              size="sm"
              onClick={() => setPasteOpen(true)}
              className="gap-1 bg-brand hover:bg-brand-strong text-black font-semibold"
            >
              <Plus size={14} /> {t("skills.btn.new")}
            </Button>
          </div>
        </div>

        {/* Selection bar */}
        {selectedSkills.length > 0 && (
          <div className="px-6 py-2 border-b border-border-subtle bg-brand/5 flex items-center justify-between gap-3 text-[12px]">
            <div className="text-text-secondary">
              {t("skills.selected.prefix")} <span className="font-semibold text-foreground">{selectedSkills.length}</span> {t("skills.selected.suffix")}
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={handleCopyText} className="gap-1">
                <Copy size={12} /> {t("skills.btn.copyText")}
              </Button>
              <Button size="sm" variant="outline" onClick={handleCopyJson} className="gap-1">
                <Copy size={12} /> {t("skills.btn.copyJson")}
              </Button>
              <button
                type="button"
                onClick={() => setSelectedIds(new Set())}
                className="text-text-muted hover:text-foreground text-[11px] underline-offset-2 hover:underline"
              >
                {t("skills.btn.clearSelection")}
              </button>
            </div>
          </div>
        )}

        {/* Body: left list + right preview */}
        <div className="flex-1 min-h-0 grid grid-cols-[minmax(360px,400px)_1fr]">
          {/* LEFT: list */}
          <div className="border-r border-border-subtle flex flex-col min-h-0">
            <div className="px-3 py-2 border-b border-border-subtle space-y-2">
              <div className="relative">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
                <Input
                  placeholder={t("skills.searchPlaceholder")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-7 h-8 text-[12px]"
                />
              </div>
              <div className="flex items-center gap-1 flex-wrap">
                <button
                  type="button"
                  onClick={() => setActiveCategory(null)}
                  className={cn(
                    "text-[11px] px-2 py-0.5 rounded-full border transition-colors",
                    activeCategory === null
                      ? "border-brand bg-brand/10 text-brand"
                      : "border-border-subtle text-text-muted hover:text-foreground hover:border-border",
                  )}
                >
                  {t("skills.category.all")}
                </button>
                {categories.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setActiveCategory(activeCategory === c ? null : c)}
                    className={cn(
                      "text-[11px] px-2 py-0.5 rounded-full border transition-colors",
                      activeCategory === c
                        ? "border-brand bg-brand/10 text-brand"
                        : "border-border-subtle text-text-muted hover:text-foreground hover:border-border",
                    )}
                  >
                    {c}
                  </button>
                ))}
                {newCatInput === null ? (
                  <button
                    type="button"
                    onClick={() => setNewCatInput("")}
                    className="text-[11px] px-2 py-0.5 rounded-full border border-dashed border-border-subtle text-text-muted hover:text-foreground hover:border-border transition-colors"
                    title={t("skills.category.addNew")}
                  >
                    + {t("skills.category.addNew")}
                  </button>
                ) : (
                  <input
                    autoFocus
                    value={newCatInput}
                    onChange={(e) => setNewCatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void commitNewCategory();
                      else if (e.key === "Escape") setNewCatInput(null);
                    }}
                    onBlur={() => void commitNewCategory()}
                    placeholder={t("skills.category.newPlaceholder")}
                    className="text-[11px] px-2 py-0.5 rounded-full border border-brand bg-transparent w-28 outline-none"
                  />
                )}
              </div>
            </div>

            <div className="flex-1 overflow-auto">
              {loading && (
                <div data-density="skills-list-loading-tool" className="motion-essential px-4 py-6 text-[12px] text-text-muted flex items-center gap-2">
                  <AgentThinkingIndicator phase="tool" size={12} /> {t("skills.loading")}
                </div>
              )}
              {error && (
                <div className="m-3 rounded-md border border-error/40 bg-error/10 text-error text-[12px] p-2">
                  {error}
                </div>
              )}
              {!loading && !error && filtered.length === 0 && (
                <div className="px-4 py-6 text-[12px] text-text-muted">{t("skills.empty")}</div>
              )}
              <div>
                {grouped.map(([groupKey, items]) => {
                  const isUncat = groupKey === UNCATEGORIZED;
                  const label = isUncat ? t("skills.category.uncategorized") : groupKey;
                  const isCollapsed = collapsedGroups.has(groupKey);
                  const isDropTarget = dropTarget === groupKey;
                  const isUserDefined = !isUncat && availableCategories.includes(groupKey);
                  return (
                    <div
                      key={groupKey}
                      onDragOver={(e) => {
                        if (!draggingId) return;
                        e.preventDefault();
                        e.dataTransfer.dropEffect = "move";
                        if (dropTarget !== groupKey) setDropTarget(groupKey);
                      }}
                      onDragLeave={(e) => {
                        // Only clear when leaving the entire group container
                        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                          setDropTarget((cur) => (cur === groupKey ? null : cur));
                        }
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        const id = e.dataTransfer.getData("text/plain") || draggingId || "";
                        void handleDropOnGroup(groupKey, id);
                      }}
                      className={cn(
                        "transition-colors",
                        isDropTarget && "ring-2 ring-inset ring-brand/60 bg-brand/5",
                      )}
                    >
                      <div
                        className={cn(
                          "sticky top-0 z-[1] flex items-center gap-1.5 bg-surface-raised/80 backdrop-blur border-b border-border-subtle text-[10px] font-bold uppercase tracking-widest text-text-muted",
                          "px-3 py-1.5",
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => toggleGroup(groupKey)}
                          className="flex items-center gap-1.5 flex-1 min-w-0 hover:text-foreground transition-colors"
                        >
                          <ChevronDown
                            size={10}
                            className={cn(
                              "transition-transform shrink-0",
                              isCollapsed && "-rotate-90",
                            )}
                          />
                          <span className="truncate">{label}</span>
                          <span className="ml-auto normal-case tracking-normal text-[10px] text-text-muted/80">
                            {items.length}
                          </span>
                        </button>
                        {isUserDefined && items.length === 0 && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void removeCategory(groupKey);
                            }}
                            className="size-4 rounded hover:bg-status-failed/15 text-text-muted hover:text-status-failed flex items-center justify-center shrink-0"
                            title={t("skills.category.remove")}
                          >
                            <X size={10} />
                          </button>
                        )}
                      </div>
                      {!isCollapsed && (
                        <>
                          {items.length === 0 && !isUncat && (
                            <div className="px-3 py-3 text-[11px] text-text-muted italic">
                              {t("skills.category.dropHint")}
                            </div>
                          )}
                          <ul className="divide-y divide-border-subtle">
                            {items.map((s) => {
                              const isFocused = focused?.id === s.id;
                              const isChecked = selectedIds.has(s.id);
                              const isBeingDragged = draggingId === s.id;
                              return (
                                <li
                                  key={s.id}
                                  draggable
                                  onDragStart={(e) => {
                                    setDraggingId(s.id);
                                    e.dataTransfer.effectAllowed = "move";
                                    e.dataTransfer.setData("text/plain", s.id);
                                  }}
                                  onDragEnd={() => {
                                    setDraggingId(null);
                                    setDropTarget(null);
                                  }}
                                  className={cn(
                                    "px-3 py-2 cursor-pointer hover:bg-surface-hover transition-colors group",
                                    isFocused && "bg-surface-hover",
                                    isBeingDragged && "opacity-40",
                                  )}
                                  onClick={() => setFocusId(s.id)}
                                >
                                  <div className="flex items-start gap-2">
                                    <input
                                      type="checkbox"
                                      checked={isChecked}
                                      onChange={() => toggleSelect(s.id)}
                                      onClick={(e) => e.stopPropagation()}
                                      className="mt-1 accent-brand"
                                      aria-label={`select ${s.name}`}
                                    />
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-2">
                                        <span className="text-[13px] font-semibold truncate">{s.name}</span>
                                      </div>
                                      {s.description && (
                                        <div className="text-[11px] text-text-muted line-clamp-2 mt-0.5">{s.description}</div>
                                      )}
                                      {s.tags && s.tags.length > 0 && (
                                        <div className="flex flex-wrap gap-1 mt-1">
                                          {s.tags.map((tag) => (
                                            <span
                                              key={tag}
                                              className="text-[9px] text-text-muted bg-surface-input rounded px-1 py-0.5"
                                            >
                                              #{tag}
                                            </span>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* RIGHT: preview */}
          <div className="flex flex-col min-h-0">
            {focused ? (
              <SkillDetailPanel
                skill={focused}
                onEdit={() => {
                  setEditing(focused);
                  setEditorOpen(true);
                }}
                onDelete={() => setConfirmDelete(focused)}
              />
            ) : (
              <div className="h-full flex items-center justify-center text-[12px] text-text-muted">
                {t("skills.preview.empty")}
              </div>
            )}
          </div>
        </div>
      </div>

      <SkillEditorDialog
        open={editorOpen}
        editing={editing}
        onClose={() => setEditorOpen(false)}
        onSaved={async () => {
          setEditorOpen(false);
          await reload();
        }}
      />

      <SkillPasteDialog
        open={pasteOpen}
        onClose={() => setPasteOpen(false)}
        onSaved={async (created, failed) => {
          setPasteOpen(false);
          addToast({
            type: failed > 0 ? "warning" : "success",
            title: t("skills.toast.pasted"),
            message: `+${created}${failed ? `  failed ${failed}` : ""}`,
          });
          await reload();
        }}
      />

      <SkillImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={async (res) => {
          addToast({
            type: res.skipped.length > 0 ? "warning" : "success",
            title: t("skills.toast.imported"),
            message: `+${res.created.length}${res.skipped.length ? `  skipped ${res.skipped.length}` : ""}`,
          });
          await reload();
        }}
      />

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
        title={t("skills.confirm.deleteTitle")}
        description={confirmDelete ? confirmDelete.name : ""}
        confirmText={t("skills.btn.delete")}
        isLoading={busy}
        onConfirm={handleDelete}
      />
    </WorkbenchShell>
  );
}

function SkillDetailPanel({
  skill,
  onEdit,
  onDelete,
}: {
  skill: Skill;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchErr, setFetchErr] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  // Translation state — cached per target so toggling doesn't re-call the LLM.
  const [translations, setTranslations] = useState<{ zh?: string; en?: string }>({});
  const [viewLang, setViewLang] = useState<"original" | "zh" | "en">("original");
  const [translating, setTranslating] = useState<"zh" | "en" | null>(null);
  const [translateErr, setTranslateErr] = useState<string | null>(null);
  const [truncatedNotice, setTruncatedNotice] = useState(false);

  useEffect(() => {
    const myId = ++requestIdRef.current;
    setBody(null);
    setFetchErr(null);
    setLoading(true);
    setTranslations({});
    setViewLang("original");
    setTranslating(null);
    setTranslateErr(null);
    setTruncatedNotice(false);
    (async () => {
      try {
        const text = await fetchSkillContent(skill.link);
        if (myId === requestIdRef.current) setBody(text);
      } catch (err) {
        if (myId === requestIdRef.current) {
          setFetchErr(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (myId === requestIdRef.current) setLoading(false);
      }
    })();
  }, [skill.id, skill.link]);

  const copyLink = async () => {
    await navigator.clipboard.writeText(skill.link);
    addToast({ type: "success", title: t("skills.toast.linkCopied") });
  };

  const handleTranslate = async (target: "zh" | "en") => {
    if (!body) return;
    if (translations[target]) {
      setViewLang(target);
      return;
    }
    setTranslating(target);
    setTranslateErr(null);
    try {
      const res = await translateSkillContent(body, target);
      setTranslations((prev) => ({ ...prev, [target]: res.translated }));
      setViewLang(target);
      setTruncatedNotice(res.truncated);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTranslateErr(msg);
      addToast({ type: "error", title: t("skills.toast.translateFailed"), message: msg });
    } finally {
      setTranslating(null);
    }
  };

  const displayBody =
    viewLang === "original" ? body : translations[viewLang] ?? body;

  return (
    <>
      <div className="px-6 py-4 border-b border-border-subtle">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-bold tracking-tight truncate">{skill.name}</h2>
              {skill.category && (
                <span className="text-[10px] uppercase tracking-wider bg-brand/15 text-brand rounded px-1.5 py-0.5">
                  {skill.category}
                </span>
              )}
            </div>
            {skill.description && (
              <p className="text-[12px] text-text-muted mt-1">{skill.description}</p>
            )}
            <div className="mt-2 flex items-center gap-2 text-[11px] text-text-muted">
              <a
                href={skill.link}
                target="_blank"
                rel="noreferrer"
                className="text-brand hover:underline truncate max-w-[480px] inline-flex items-center gap-1"
                title={skill.link}
              >
                <ExternalLink size={11} />
                {skill.link}
              </a>
              <button
                type="button"
                onClick={copyLink}
                className="text-text-muted hover:text-foreground"
                title={t("skills.btn.copyLink")}
              >
                <Copy size={11} />
              </button>
            </div>
            {skill.tags && skill.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {skill.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] text-text-muted bg-surface-input rounded px-1.5 py-0.5"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={onEdit}
              className="size-8 rounded-md hover:bg-surface-input text-text-muted hover:text-foreground flex items-center justify-center transition-colors"
              title={t("skills.btn.edit")}
            >
              <Pencil size={14} />
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="size-8 rounded-md hover:bg-status-failed/10 text-text-muted hover:text-status-failed flex items-center justify-center transition-colors"
              title={t("skills.btn.delete")}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      </div>
      {/* Translation toolbar — sits between header and body. */}
      {!loading && !fetchErr && body !== null && (
        <div className="px-6 py-1.5 border-b border-border-subtle flex items-center gap-2 bg-surface-raised/30 text-[11px]">
          <Languages size={12} className="text-text-muted" />
          <span className="text-text-muted mr-1">{t("skills.translate.label")}</span>
          <div className="inline-flex rounded-md border border-border-subtle overflow-hidden">
            <button
              type="button"
              onClick={() => setViewLang("original")}
              className={cn(
                "px-2 py-0.5 transition-colors",
                viewLang === "original"
                  ? "bg-brand/15 text-brand font-semibold"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
            >
              {t("skills.translate.original")}
            </button>
            <button
              type="button"
              disabled={translating !== null}
              onClick={() => handleTranslate("zh")}
              className={cn(
                "px-2 py-0.5 border-l border-border-subtle transition-colors disabled:opacity-50",
                viewLang === "zh"
                  ? "bg-brand/15 text-brand font-semibold"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
              title={t("skills.translate.toZh")}
            >
              {translating === "zh" ? (
                <AgentThinkingIndicator phase="tool" size={11} className="inline" />
              ) : (
                t("skills.translate.zh")
              )}
            </button>
            <button
              type="button"
              disabled={translating !== null}
              onClick={() => handleTranslate("en")}
              className={cn(
                "px-2 py-0.5 border-l border-border-subtle transition-colors disabled:opacity-50",
                viewLang === "en"
                  ? "bg-brand/15 text-brand font-semibold"
                  : "text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
              title={t("skills.translate.toEn")}
            >
              {translating === "en" ? (
                <AgentThinkingIndicator phase="tool" size={11} className="inline" />
              ) : (
                t("skills.translate.en")
              )}
            </button>
          </div>
          {translating && (
            <span className="text-text-muted ml-1">{t("skills.translate.inProgress")}</span>
          )}
          {truncatedNotice && viewLang !== "original" && (
            <span className="text-warning ml-auto" title={t("skills.translate.truncatedHint")}>
              {t("skills.translate.truncated")}
            </span>
          )}
          {translateErr && !translating && (
            <span className="text-error ml-auto truncate" title={translateErr}>
              {translateErr}
            </span>
          )}
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto px-6 py-4">
        {loading && (
          <div
            data-density="skills-preview-loading-tool"
            className="motion-essential flex items-center gap-2 text-[12px] text-text-muted"
          >
            <AgentThinkingIndicator phase="tool" size={12} /> {t("skills.preview.loading")}
          </div>
        )}
        {fetchErr && (
          <div className="rounded-md border border-error/40 bg-error/10 text-error text-[12px] p-3">
            {t("skills.preview.fetchFailed")}: {fetchErr}
          </div>
        )}
        {!loading && !fetchErr && displayBody !== null && (
          <SkillMarkdown content={displayBody} />
        )}
      </div>
    </>
  );
}

function SkillEditorDialog({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: Skill | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [form, setForm] = useState<CreateSkillRequest>({
    name: "",
    link: "",
    description: "",
    category: "",
    tags: [],
  });
  const [tagsText, setTagsText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      if (editing) {
        setForm({
          name: editing.name,
          link: editing.link,
          description: editing.description ?? "",
          category: editing.category ?? "",
          tags: editing.tags ?? [],
        });
        setTagsText((editing.tags ?? []).join(", "));
      } else {
        setForm({ name: "", link: "", description: "", category: "", tags: [] });
        setTagsText("");
      }
    }
  }, [open, editing]);

  const submit = async () => {
    if (!form.name.trim() || !form.link.trim()) {
      addToast({ type: "error", title: t("skills.toast.missingFields") });
      return;
    }
    const tags = tagsText.split(",").map((s) => s.trim()).filter(Boolean);
    setSubmitting(true);
    try {
      if (editing) {
        await updateSkill(editing.id, { ...form, tags });
      } else {
        await createSkill({ ...form, tags });
      }
      addToast({ type: "success", title: editing ? t("skills.toast.updated") : t("skills.toast.created") });
      await onSaved();
    } catch (err) {
      addToast({ type: "error", title: t("skills.toast.saveFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t("skills.editor.editTitle") : t("skills.editor.newTitle")}</DialogTitle>
          <DialogDescription>{t("skills.editor.subtitle")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-[12px] text-text-muted block mb-1">{t("skills.field.name")} *</label>
            <Input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. PDF Extractor"
            />
          </div>
          <div>
            <label className="text-[12px] text-text-muted block mb-1">{t("skills.field.link")} *</label>
            <Input
              value={form.link}
              onChange={(e) => setForm((f) => ({ ...f, link: e.target.value }))}
              placeholder="https://raw.githubusercontent.com/..."
            />
          </div>
          <div>
            <label className="text-[12px] text-text-muted block mb-1">{t("skills.field.description")}</label>
            <Textarea
              value={form.description ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              rows={2}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[12px] text-text-muted block mb-1">{t("skills.field.category")}</label>
              <Input
                value={form.category ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder="engineering"
              />
            </div>
            <div>
              <label className="text-[12px] text-text-muted block mb-1">{t("skills.field.tags")}</label>
              <Input
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
                placeholder="pdf, parsing"
              />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            {t("skills.btn.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={submitting}
            data-density={submitting ? "skills-editor-save-tool" : "skills-editor-save"}
            className={cn("gap-1", submitting && "motion-essential")}
          >
            {submitting && <AgentThinkingIndicator phase="tool" size={12} />}
            {t("skills.btn.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SkillImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: (res: SkillImportResult) => Promise<void>;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [busy, setBusy] = useState(false);
  const mdRef = useRef<HTMLInputElement>(null);
  const xlsxRef = useRef<HTMLInputElement>(null);

  const handleMd = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const res = await importSkillsMarkdown(Array.from(files));
      await onImported(res);
      onClose();
    } catch (err) {
      addToast({ type: "error", title: t("skills.toast.importFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
      if (mdRef.current) mdRef.current.value = "";
    }
  };

  const handleXlsx = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const res = await importSkillsExcel(files[0]);
      await onImported(res);
      onClose();
    } catch (err) {
      addToast({ type: "error", title: t("skills.toast.importFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
      if (xlsxRef.current) xlsxRef.current.value = "";
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("skills.import.title")}</DialogTitle>
          <DialogDescription>{t("skills.import.subtitle")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => mdRef.current?.click()}
            className="w-full border-2 border-dashed border-border-subtle rounded-lg p-4 text-left hover:border-brand hover:bg-brand/5 transition-colors disabled:opacity-50"
          >
            <div className="flex items-center gap-3">
              <FileText size={20} className="text-brand" />
              <div className="min-w-0">
                <div className="text-[13px] font-semibold">{t("skills.import.md.title")}</div>
                <div className="text-[11px] text-text-muted">{t("skills.import.md.hint")}</div>
              </div>
            </div>
          </button>
          <input
            ref={mdRef}
            type="file"
            accept=".md,text/markdown"
            multiple
            className="hidden"
            onChange={(e) => handleMd(e.target.files)}
          />

          <button
            type="button"
            disabled={busy}
            onClick={() => xlsxRef.current?.click()}
            className="w-full border-2 border-dashed border-border-subtle rounded-lg p-4 text-left hover:border-brand hover:bg-brand/5 transition-colors disabled:opacity-50"
          >
            <div className="flex items-center gap-3">
              <FileSpreadsheet size={20} className="text-brand" />
              <div className="min-w-0">
                <div className="text-[13px] font-semibold">{t("skills.import.excel.title")}</div>
                <div className="text-[11px] text-text-muted">{t("skills.import.excel.hint")}</div>
              </div>
            </div>
          </button>
          <input
            ref={xlsxRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            onChange={(e) => handleXlsx(e.target.files)}
          />

          {busy && (
            <div
              data-density="skills-import-processing-tool"
              className="motion-essential flex items-center justify-center gap-2 text-[12px] text-text-muted"
            >
              <AgentThinkingIndicator phase="tool" size={12} /> {t("skills.import.processing")}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {t("skills.btn.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --- Paste parser --------------------------------------------------------

interface ParsedSkill {
  name: string;
  link: string;
  description?: string;
}

function deriveNameFromUrl(url: string): string {
  try {
    const u = new URL(url);
    const segs = u.pathname.split("/").filter(Boolean);
    if (segs.length === 0) return u.hostname;
    let last = decodeURIComponent(segs[segs.length - 1]);
    last = last.replace(/\.(md|markdown|txt|html?|json|ya?ml)$/i, "");
    return last || u.hostname;
  } catch {
    return url;
  }
}

function parseSkillsText(input: string): ParsedSkill[] {
  const trimmed = input.trim();
  if (!trimmed) return [];

  // JSON array of {name?, link|url, description?}
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed);
      const arr: unknown[] = Array.isArray(parsed) ? parsed : [parsed];
      const out: ParsedSkill[] = [];
      for (const item of arr) {
        if (!item || typeof item !== "object") continue;
        const obj = item as Record<string, unknown>;
        const link =
          typeof obj.link === "string"
            ? obj.link
            : typeof obj.url === "string"
              ? obj.url
              : null;
        if (!link) continue;
        const name =
          typeof obj.name === "string" && obj.name.trim()
            ? obj.name.trim()
            : typeof obj.title === "string" && obj.title.trim()
              ? obj.title.trim()
              : deriveNameFromUrl(link);
        const desc =
          typeof obj.description === "string"
            ? obj.description.trim() || undefined
            : typeof obj.desc === "string"
              ? obj.desc.trim() || undefined
              : undefined;
        out.push({ name, link: link.trim(), description: desc });
      }
      if (out.length > 0) return dedupe(out);
    } catch {
      // fall through to line-by-line
    }
  }

  const out: ParsedSkill[] = [];
  for (const rawLine of input.split(/\r?\n/)) {
    const line = rawLine
      .trim()
      .replace(/^[-*•·]\s+/, "")
      .replace(/^\d+[.)]\s+/, "");
    if (!line) continue;

    let name = "";
    let link = "";
    let description: string | undefined;

    // Markdown link: [name](url) [- desc]?
    const md = line.match(/^\[([^\]]+)\]\(([^)\s]+)\)\s*(?:[-:—–|]\s*)?(.*)$/);
    if (md) {
      name = md[1].trim();
      link = md[2].trim();
      description = md[3].trim() || undefined;
    } else {
      const urlMatch = line.match(/https?:\/\/[^\s)<>"']+/);
      if (!urlMatch) continue;
      link = urlMatch[0].replace(/[),.;:]+$/, "");
      const before = line
        .slice(0, urlMatch.index!)
        .trim()
        .replace(/[\t:|\-—–]+$/, "")
        .trim();
      const after = line
        .slice(urlMatch.index! + urlMatch[0].length)
        .trim()
        .replace(/^[\t:|\-—–]+/, "")
        .trim();
      if (before) {
        name = before;
        description = after || undefined;
      } else {
        name = deriveNameFromUrl(link);
        description = after || undefined;
      }
    }
    if (!link || !name) continue;
    out.push({ name, link, description });
  }
  return dedupe(out);
}

function dedupe(items: ParsedSkill[]): ParsedSkill[] {
  const seen = new Set<string>();
  const out: ParsedSkill[] = [];
  for (const it of items) {
    if (seen.has(it.link)) continue;
    seen.add(it.link);
    out.push(it);
  }
  return out;
}

// --- Paste dialog --------------------------------------------------------

function SkillPasteDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (created: number, failed: number) => Promise<void>;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [text, setText] = useState("");
  const [category, setCategory] = useState("");
  const [rows, setRows] = useState<ParsedSkill[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // Reset when dialog opens
  useEffect(() => {
    if (open) {
      setText("");
      setCategory("");
      setRows([]);
      setSubmitting(false);
    }
  }, [open]);

  // Re-parse whenever text changes
  useEffect(() => {
    setRows(parseSkillsText(text));
  }, [text]);

  const updateRow = (idx: number, patch: Partial<ParsedSkill>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const removeRow = (idx: number) => {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  };

  const submit = async () => {
    if (rows.length === 0) return;
    setSubmitting(true);
    let created = 0;
    let failed = 0;
    for (const r of rows) {
      if (!r.name.trim() || !r.link.trim()) {
        failed++;
        continue;
      }
      try {
        await createSkill({
          name: r.name.trim(),
          link: r.link.trim(),
          description: r.description?.trim() || "",
          category: category.trim() || "",
          tags: [],
        });
        created++;
      } catch (err) {
        failed++;
        addToast({
          type: "error",
          title: t("skills.toast.saveFailed"),
          message: `${r.name}: ${err instanceof Error ? err.message : String(err)}`,
        });
      }
    }
    setSubmitting(false);
    await onSaved(created, failed);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("skills.paste.title")}</DialogTitle>
          <DialogDescription>{t("skills.paste.subtitle")}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 overflow-y-auto -mx-4 px-4 space-y-3">
          <Textarea
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("skills.paste.placeholder")}
            className="font-mono text-[12px]"
          />

          <div>
            <label className="text-[12px] text-text-muted block mb-1">
              {t("skills.paste.commonCategory")}
            </label>
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder={t("skills.paste.commonCategoryHint")}
            />
          </div>

          {rows.length > 0 && (
            <div className="border border-border-subtle rounded-lg overflow-hidden">
              <div className="px-3 py-1.5 bg-surface-raised/40 border-b border-border-subtle text-[11px] text-text-muted flex items-center justify-between sticky top-0 z-10">
                <span>
                  {t("skills.paste.previewPrefix")}{" "}
                  <span className="font-semibold text-foreground">{rows.length}</span>{" "}
                  {t("skills.paste.previewSuffix")}
                </span>
              </div>
              <div className="divide-y divide-border-subtle">
                {rows.map((r, i) => (
                  <div key={`${r.link}-${i}`} className="px-3 py-2 flex items-start gap-2">
                    <span className="text-[10px] text-text-muted shrink-0 mt-1.5 w-5 text-right">
                      {i + 1}.
                    </span>
                    <div className="min-w-0 flex-1 space-y-1">
                      <Input
                        value={r.name}
                        onChange={(e) => updateRow(i, { name: e.target.value })}
                        className="h-7 text-[12.5px] font-semibold"
                        placeholder={t("skills.field.name")}
                      />
                      <div className="text-[11px] text-text-muted truncate" title={r.link}>
                        {r.link}
                      </div>
                      <Input
                        value={r.description ?? ""}
                        onChange={(e) => updateRow(i, { description: e.target.value })}
                        className="h-6 text-[11px]"
                        placeholder={t("skills.field.description")}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      className="size-6 rounded hover:bg-status-failed/10 text-text-muted hover:text-status-failed flex items-center justify-center shrink-0"
                      title={t("skills.paste.removeRow")}
                    >
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {text.trim() && rows.length === 0 && (
            <div className="text-[11px] text-text-muted">{t("skills.paste.noneParsed")}</div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            {t("skills.btn.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={rows.length === 0 || submitting}
            data-density={submitting ? "skills-paste-saveall-tool" : "skills-paste-saveall"}
            className={cn("gap-1 bg-brand hover:bg-brand-strong text-black font-semibold", submitting && "motion-essential")}
          >
            {submitting && <AgentThinkingIndicator phase="tool" size={12} />}
            {t("skills.paste.saveAll")} ({rows.length})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
