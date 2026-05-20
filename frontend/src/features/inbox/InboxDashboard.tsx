"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Inbox as InboxIcon,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  GitMerge,
  Sparkles,
  TrendingUp,
  ArrowUpRight,
  GitBranch,
  Library,
} from "lucide-react";

import {
  getCodexIssues,
  getCodexStats,
  getTeamNotes,
  getWorkspaces,
  listProjects,
  type TeamNoteBlock,
} from "@/lib/api";
import type { CodexIssue, CodexStats, Project, Workspace } from "@/lib/types";
import { useDataEvent } from "@/lib/dataEvents";
import { useI18n } from "@/providers/I18nProvider";
import { StatusBadge, inferStatusKind } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";

/**
 * Console v2 Inbox dashboard — replaces the gray /projects landing page.
 *
 *   ┌───────────────────────────────────────────────────────────────┐
 *   │  Inbox                                                        │
 *   │  4 projects · 6 workspaces · last activity 2m ago             │
 *   │                                                               │
 *   │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐        │
 *   │  │Total │ │Run.. │ │Await.│ │Done  │ │Failed│ │Merged│        │
 *   │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘        │
 *   │                                                               │
 *   │  ┌─── Status Distribution ───┐  ┌─── 7-day activity ────┐    │
 *   │  │       ╭───────╮           │  │ ▆▂▄▇▃█▅                │    │
 *   │  │      donut + legend       │  │   bar chart            │    │
 *   │  └───────────────────────────┘  └────────────────────────┘    │
 *   │                                                               │
 *   │  ┌─── Recent issues ─────────────────────────────────────┐   │
 *   │  │ • title          Running   feat/auth   Codex     2m   │   │
 *   │  └───────────────────────────────────────────────────────┘   │
 *   └───────────────────────────────────────────────────────────────┘
 */
export function InboxDashboard() {
  const router = useRouter();
  const { t } = useI18n();
  const [stats, setStats] = useState<CodexStats | null>(null);
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [recentNotes, setRecentNotes] = useState<
    Array<{ block: TeamNoteBlock; projectId: string; projectName: string }>
  >([]);

  const reload = useCallback(async () => {
    const [s, iss, pr, ws] = await Promise.all([
      getCodexStats().catch(() => null),
      getCodexIssues(null, null),
      listProjects(),
      getWorkspaces(null).catch(() => []),
    ]);
    setStats(s);
    setIssues(iss);
    setProjects(pr);
    setWorkspaces(ws);

    // Knowledge: pull latest 5 team-notes blocks across all projects.
    try {
      const perProject = await Promise.all(
        pr.slice(0, 8).map(async (p) => {
          try {
            const tn = await getTeamNotes(p.id, false);
            return tn.blocks
              .filter((b) => !b.deleted_at && b.timestamp)
              .map((block) => ({ block, projectId: p.id, projectName: p.name }));
          } catch {
            return [] as Array<{ block: TeamNoteBlock; projectId: string; projectName: string }>;
          }
        }),
      );
      const flat = perProject.flat();
      flat.sort((a, b) => (b.block.timestamp || "").localeCompare(a.block.timestamp || ""));
      setRecentNotes(flat.slice(0, 5));
    } catch {
      setRecentNotes([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void reload().finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  // Refresh whenever any project/workspace mutation lands so the dashboard
  // doesn't drift away from what the rest of the app shows.
  useDataEvent("workspaces:changed", () => void reload());
  useDataEvent("projects:changed", () => void reload());

  const projectWorkspaceCount = useMemo(
    () => workspaces.filter((w) => w.project_id != null).length,
    [workspaces],
  );

  // Derive richer per-issue buckets locally so the dashboard always reflects
  // the real status mix even if the backend aggregate trails behind.
  const buckets = useMemo(() => computeBuckets(issues), [issues]);
  const sevenDay = useMemo(() => computeDailyActivity(issues, 7), [issues]);
  const projectSummaries = useMemo(
    () => computeProjectSummaries(issues, projects),
    [issues, projects],
  );

  const lastActivityRel = stats?.last_activity_at ? relTime(stats.last_activity_at) : "—";
  const recentIssues = useMemo(
    () =>
      [...issues]
        .sort((a, b) => {
          const ta = new Date(a.updated_at ?? a.created_at ?? 0).getTime();
          const tb = new Date(b.updated_at ?? b.created_at ?? 0).getTime();
          return tb - ta;
        })
        .slice(0, 8),
    [issues],
  );

  return (
    <div className="min-h-full">
      {/* Hero header with gradient backdrop */}
      <div className="relative overflow-hidden border-b border-border-subtle">
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            background:
              "radial-gradient(900px 300px at 12% -10%, rgba(230,149,82,0.30), transparent 60%), radial-gradient(700px 240px at 90% -10%, rgba(96,165,250,0.18), transparent 60%)",
          }}
        />
        <div className="relative px-8 pt-7 pb-6 max-w-[1280px] mx-auto">
          <div className="flex items-center gap-3 mb-2">
            <span className="size-9 rounded-xl bg-gradient-to-br from-brand to-brand-strong flex items-center justify-center shadow-lg shadow-brand/30">
              <InboxIcon size={18} className="text-black" />
            </span>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Inbox</h1>
              <p className="text-[12px] text-text-muted">
                {projects.length} project{projects.length === 1 ? "" : "s"} ·{" "}
                {projectWorkspaceCount} workspace
                {projectWorkspaceCount === 1 ? "" : "s"} · last activity {lastActivityRel}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="px-8 py-6 max-w-[1280px] mx-auto space-y-6">
        {/* First-run / empty-Inbox quickstart. Only renders when there's
            literally nothing yet, so it doesn't clutter the live dashboard. */}
        {!loading && issues.length === 0 && (
          <div className="rounded-2xl border border-brand/30 bg-brand/[0.04] p-6">
            <div className="flex items-start gap-4">
              <div className="size-10 rounded-xl bg-brand/15 text-brand flex items-center justify-center text-xl">
                ✦
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-bold mb-1">{t("inbox.firstRunTitle")}</h2>
                <p className="text-[12px] text-text-muted mb-3">
                  {t("inbox.firstRunDesc")}
                </p>
                <ol className="space-y-2 text-[13px] text-text-secondary">
                  <li className="flex items-start gap-2">
                    <span className="size-5 rounded-full bg-brand/15 text-brand text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">1</span>
                    <span>{t("inbox.firstRun.step1")}</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="size-5 rounded-full bg-brand/15 text-brand text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">2</span>
                    <span>{t("inbox.firstRun.step2")}</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="size-5 rounded-full bg-brand/15 text-brand text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">3</span>
                    <span>{t("inbox.firstRun.step3")}</span>
                  </li>
                </ol>
                <div className="flex gap-2 mt-4">
                  <button
                    onClick={() => router.push("/projects")}
                    className="px-3 py-1.5 rounded-md text-[12px] font-semibold bg-brand text-black hover:bg-brand-strong transition-colors"
                  >
                    {t("inbox.firstRun.openIssues")}
                  </button>
                  <button
                    onClick={() => router.push("/help")}
                    className="px-3 py-1.5 rounded-md text-[12px] text-text-secondary hover:bg-surface-hover transition-colors"
                  >
                    {t("inbox.firstRun.readGuide")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* KPI cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard
            icon={<Sparkles size={14} />}
            label="Total"
            value={buckets.total}
            tint="brand"
            loading={loading}
          />
          <KpiCard
            icon={<Activity size={14} />}
            label="Running"
            value={buckets.running}
            tint="running"
            pulse
            loading={loading}
          />
          <KpiCard
            icon={<Clock size={14} />}
            label="Awaiting"
            value={buckets.awaiting}
            tint="awaiting"
            pulse
            loading={loading}
          />
          <KpiCard
            icon={<CheckCircle2 size={14} />}
            label="Done"
            value={buckets.done}
            tint="done"
            loading={loading}
          />
          <KpiCard
            icon={<XCircle size={14} />}
            label="Failed"
            value={buckets.failed}
            tint="failed"
            loading={loading}
          />
          <KpiCard
            icon={<GitMerge size={14} />}
            label="Merged"
            value={buckets.merged}
            tint="info"
            loading={loading}
          />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <DonutCard buckets={buckets} loading={loading} />
          <ActivityCard data={sevenDay} loading={loading} />
        </div>

        {/* Project breakdown + recent issues */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <ProjectSummaryCard
            summaries={projectSummaries}
            onPick={(pid) => router.push(`/projects/${pid}`)}
            loading={loading}
          />
          <RecentIssuesCard
            issues={recentIssues}
            projects={projects}
            onOpen={(id) => router.push(`/issues/${id}`)}
            loading={loading}
          />
        </div>

        {/* Recent knowledge updates (team_notes blocks across projects) */}
        <RecentKnowledgeCard
          items={recentNotes}
          onOpenProject={(pid) => router.push(`/knowledge?project=${pid}`)}
          loading={loading}
          t={t}
        />
      </div>
    </div>
  );
}

function RecentKnowledgeCard({
  items,
  onOpenProject,
  loading,
  t,
}: {
  items: Array<{ block: TeamNoteBlock; projectId: string; projectName: string }>;
  onOpenProject: (projectId: string) => void;
  loading: boolean;
  t: (key: string) => string;
}) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-surface overflow-hidden">
      <div className="px-4 py-3 flex items-center gap-2 border-b border-border-subtle">
        <Library size={14} className="text-brand" />
        <span className="text-[13px] font-semibold">{t("inbox.recentKnowledge")}</span>
        <span className="ml-auto text-[11px] text-text-muted">{items.length}</span>
      </div>
      {loading ? (
        <div className="px-4 py-4 text-[12px] text-text-muted">…</div>
      ) : items.length === 0 ? (
        <div className="px-4 py-4 text-[12px] text-text-muted">
          {t("inbox.recentKnowledgeEmpty")}
        </div>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {items.map(({ block, projectId, projectName }) => (
            <li key={`${projectId}:${block.block_id}`}>
              <button
                type="button"
                onClick={() => onOpenProject(projectId)}
                className="w-full text-left px-4 py-2.5 hover:bg-surface-hover flex items-start gap-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-medium">{block.heading}</div>
                  <div className="text-[10.5px] text-text-muted font-mono">
                    {projectName} · {block.timestamp ?? ""}
                  </div>
                </div>
                {block.pinned && (
                  <span className="rounded bg-amber-500/15 px-1 py-px text-[10px] text-amber-400">
                    {t("teamNotes.pinned")}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ============================================================================
// KPI card
// ============================================================================

type Tint = "brand" | "running" | "awaiting" | "done" | "failed" | "info";

const TINT_TO_CSS: Record<Tint, { ring: string; dot: string; iconBg: string; text: string }> = {
  brand: {
    ring: "from-brand/30 to-transparent",
    dot: "bg-brand",
    iconBg: "bg-brand/15 text-brand",
    text: "text-brand",
  },
  running: {
    ring: "from-status-running/30 to-transparent",
    dot: "bg-status-running",
    iconBg: "bg-status-running/15 text-status-running",
    text: "text-status-running",
  },
  awaiting: {
    ring: "from-status-awaiting/30 to-transparent",
    dot: "bg-status-awaiting",
    iconBg: "bg-status-awaiting/15 text-status-awaiting",
    text: "text-status-awaiting",
  },
  done: {
    ring: "from-status-done/30 to-transparent",
    dot: "bg-status-done",
    iconBg: "bg-status-done/15 text-status-done",
    text: "text-status-done",
  },
  failed: {
    ring: "from-status-failed/30 to-transparent",
    dot: "bg-status-failed",
    iconBg: "bg-status-failed/15 text-status-failed",
    text: "text-status-failed",
  },
  info: {
    ring: "from-status-info/30 to-transparent",
    dot: "bg-status-info",
    iconBg: "bg-status-info/15 text-status-info",
    text: "text-status-info",
  },
};

function KpiCard({
  icon,
  label,
  value,
  tint,
  pulse,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tint: Tint;
  pulse?: boolean;
  loading?: boolean;
}) {
  const t = TINT_TO_CSS[tint];
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border border-border-subtle bg-surface-raised p-3 transition-all",
        "hover:border-border-strong hover:-translate-y-0.5 hover:shadow-lg",
      )}
    >
      <div
        aria-hidden
        className={cn("absolute -top-8 -right-8 size-24 rounded-full blur-2xl bg-gradient-radial", t.ring)}
        style={{
          background:
            tint === "brand"
              ? "radial-gradient(closest-side, rgba(230,149,82,0.35), transparent)"
              : tint === "running"
                ? "radial-gradient(closest-side, rgba(230,149,82,0.35), transparent)"
                : tint === "awaiting"
                  ? "radial-gradient(closest-side, rgba(234,179,8,0.30), transparent)"
                  : tint === "done"
                    ? "radial-gradient(closest-side, rgba(74,222,128,0.30), transparent)"
                    : tint === "failed"
                      ? "radial-gradient(closest-side, rgba(239,68,68,0.30), transparent)"
                      : "radial-gradient(closest-side, rgba(96,165,250,0.30), transparent)",
        }}
      />
      <div className="relative flex items-center justify-between mb-2">
        <span
          className={cn(
            "size-7 rounded-md inline-flex items-center justify-center",
            t.iconBg,
          )}
        >
          {icon}
        </span>
        {pulse && value > 0 && (
          <span className="relative inline-flex">
            <span className={cn("size-1.5 rounded-full", t.dot)} />
            <span
              className={cn("absolute inset-0 rounded-full animate-ping opacity-60", t.dot)}
            />
          </span>
        )}
      </div>
      <div className="relative">
        <div className="text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
        <div className="text-2xl font-bold tabular-nums mt-0.5">
          {loading ? "—" : value}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Donut card — status distribution
// ============================================================================

const DONUT_ORDER: { key: keyof Buckets; tint: Tint; label: string }[] = [
  { key: "running", tint: "running", label: "Running" },
  { key: "awaiting", tint: "awaiting", label: "Awaiting" },
  { key: "done", tint: "done", label: "Done" },
  { key: "failed", tint: "failed", label: "Failed" },
  { key: "merged", tint: "info", label: "Merged" },
  { key: "queued", tint: "brand", label: "Queued" },
];

const TINT_TO_HEX: Record<Tint, string> = {
  brand: "#e69552",
  running: "#e69552",
  awaiting: "#eab308",
  done: "#4ade80",
  failed: "#ef4444",
  info: "#60a5fa",
};

function DonutCard({ buckets, loading }: { buckets: Buckets; loading: boolean }) {
  const slices = DONUT_ORDER.map((d) => ({ ...d, value: buckets[d.key] })).filter((s) => s.value > 0);
  const total = slices.reduce((acc, s) => acc + s.value, 0);

  const radius = 50;
  const stroke = 18;
  const circ = 2 * Math.PI * radius;
  let offset = 0;
  const segments = slices.map((s) => {
    const fraction = total === 0 ? 0 : s.value / total;
    const len = fraction * circ;
    const dashArray = `${len} ${circ - len}`;
    const dashOffset = -offset;
    offset += len;
    return { ...s, dashArray, dashOffset };
  });

  return (
    <Card title="Status distribution" subtitle={`${total} issue${total === 1 ? "" : "s"}`} className="lg:col-span-1">
      {loading ? (
        <Skeleton h={180} />
      ) : (
        <div className="flex items-center gap-4">
          <svg viewBox="0 0 140 140" className="size-[140px] shrink-0 -rotate-90">
            {/* track */}
            <circle
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke="var(--color-border-subtle)"
              strokeWidth={stroke}
            />
            {total === 0 ? null : (
              segments.map((seg) => (
                <circle
                  key={seg.key}
                  cx="70"
                  cy="70"
                  r={radius}
                  fill="none"
                  stroke={TINT_TO_HEX[seg.tint]}
                  strokeWidth={stroke}
                  strokeDasharray={seg.dashArray}
                  strokeDashoffset={seg.dashOffset}
                  strokeLinecap="butt"
                />
              ))
            )}
            <g transform="translate(70 70) rotate(90)">
              <text textAnchor="middle" dominantBaseline="middle" className="fill-foreground" fontSize="22" fontWeight="700">
                {total}
              </text>
              <text textAnchor="middle" dominantBaseline="middle" dy="18" className="fill-text-muted" fontSize="9">
                ISSUES
              </text>
            </g>
          </svg>
          <ul className="flex-1 min-w-0 space-y-1.5">
            {DONUT_ORDER.map((d) => {
              const value = buckets[d.key];
              const pct = total === 0 ? 0 : Math.round((value / total) * 100);
              return (
                <li key={d.key} className="flex items-center gap-2 text-[12px]">
                  <span
                    className="size-2 rounded-full shrink-0"
                    style={{ background: TINT_TO_HEX[d.tint] }}
                  />
                  <span className="text-text-secondary flex-1 truncate">{d.label}</span>
                  <span className="tabular-nums text-foreground font-medium">{value}</span>
                  <span className="tabular-nums text-text-muted w-9 text-right">{pct}%</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}

// ============================================================================
// Activity card — 7 day bar chart
// ============================================================================

function ActivityCard({
  data,
  loading,
}: {
  data: { label: string; created: number; finished: number }[];
  loading: boolean;
}) {
  const max = Math.max(1, ...data.map((d) => Math.max(d.created, d.finished)));
  const totalCreated = data.reduce((acc, d) => acc + d.created, 0);
  const totalFinished = data.reduce((acc, d) => acc + d.finished, 0);
  const delta = totalCreated - totalFinished;

  return (
    <Card
      title="Activity — last 7 days"
      subtitle={
        <span className="flex items-center gap-1">
          <TrendingUp size={11} className={delta >= 0 ? "text-status-done" : "text-status-failed"} />
          <span className="text-text-secondary">{totalCreated} created · {totalFinished} finished</span>
        </span>
      }
      className="lg:col-span-2"
    >
      {loading ? (
        <Skeleton h={180} />
      ) : (
        <>
          <div className="flex items-end gap-3 h-[140px] px-1">
            {data.map((d, i) => {
              const hC = (d.created / max) * 100;
              const hF = (d.finished / max) * 100;
              return (
                <div key={i} className="flex-1 flex items-end justify-center gap-1 h-full group">
                  <div className="relative w-full max-w-[14px] h-full flex items-end">
                    <div
                      className="w-full bg-gradient-to-t from-brand to-brand-strong rounded-sm transition-all group-hover:opacity-90"
                      style={{ height: `${Math.max(hC, d.created > 0 ? 4 : 0)}%` }}
                      title={`${d.created} created`}
                    />
                  </div>
                  <div className="relative w-full max-w-[14px] h-full flex items-end">
                    <div
                      className="w-full bg-gradient-to-t from-status-done/70 to-status-done rounded-sm transition-all group-hover:opacity-90"
                      style={{ height: `${Math.max(hF, d.finished > 0 ? 4 : 0)}%` }}
                      title={`${d.finished} finished`}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-3 px-1 mt-1 text-[10px] text-text-muted">
            {data.map((d, i) => (
              <div key={i} className="flex-1 text-center">
                {d.label}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-4 pt-3 border-t border-border-subtle mt-3 text-[11px]">
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-sm bg-brand" />
              <span className="text-text-secondary">Created</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-sm bg-status-done" />
              <span className="text-text-secondary">Finished</span>
            </span>
          </div>
        </>
      )}
    </Card>
  );
}

// ============================================================================
// Project summary card
// ============================================================================

function ProjectSummaryCard({
  summaries,
  onPick,
  loading,
}: {
  summaries: ProjectSummary[];
  onPick: (id: string) => void;
  loading?: boolean;
}) {
  const top = summaries.slice(0, 5);
  const maxTotal = Math.max(1, ...top.map((s) => s.total));

  return (
    <Card title="By project" subtitle={`${summaries.length} project${summaries.length === 1 ? "" : "s"}`} className="lg:col-span-1">
      {loading ? (
        <Skeleton h={160} />
      ) : top.length === 0 ? (
        <Empty label="No projects yet" />
      ) : (
        <ul className="space-y-2.5">
          {top.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onPick(s.id)}
                className="w-full group text-left"
              >
                <div className="flex items-center justify-between text-[12px] mb-1">
                  <span className="truncate text-foreground group-hover:text-brand transition-colors">
                    {s.name}
                  </span>
                  <span className="tabular-nums text-text-muted shrink-0 ml-2">{s.total}</span>
                </div>
                <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-input">
                  <Bar tint="running" value={s.running} max={maxTotal} />
                  <Bar tint="awaiting" value={s.awaiting} max={maxTotal} />
                  <Bar tint="done" value={s.done} max={maxTotal} />
                  <Bar tint="failed" value={s.failed} max={maxTotal} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Bar({ tint, value, max }: { tint: Tint; value: number; max: number }) {
  if (value === 0) return null;
  const pct = (value / max) * 100;
  return (
    <span
      className="block h-full"
      style={{ width: `${pct}%`, background: TINT_TO_HEX[tint] }}
      title={`${tint}: ${value}`}
    />
  );
}

// ============================================================================
// Recent issues card
// ============================================================================

function RecentIssuesCard({
  issues,
  projects,
  onOpen,
  loading,
}: {
  issues: CodexIssue[];
  projects: Project[];
  onOpen: (id: string) => void;
  loading?: boolean;
}) {
  const projectMap = useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects]);
  return (
    <Card
      title="Recent issues"
      subtitle={`${issues.length} most recent`}
      className="lg:col-span-2"
    >
      {loading ? (
        <Skeleton h={200} />
      ) : issues.length === 0 ? (
        <Empty label="No issues yet — create one from any workspace" />
      ) : (
        <ul className="divide-y divide-border-subtle -mx-1">
          {issues.map((issue) => {
            const kind = inferStatusKind(issue.status);
            const label = humanLabel(issue.status);
            const project = issue.project_id ? projectMap.get(issue.project_id) : null;
            const updated = issue.updated_at ?? issue.created_at;
            return (
              <li key={issue.id}>
                <button
                  type="button"
                  onClick={() => onOpen(issue.id)}
                  className="w-full text-left px-1 py-2.5 hover:bg-surface-hover rounded transition-colors group flex items-center gap-3"
                >
                  <span className={cn(
                    "size-1.5 rounded-full shrink-0",
                    kind === "running" && "bg-status-running",
                    kind === "done" && "bg-status-done",
                    kind === "failed" && "bg-status-failed",
                    kind === "awaiting" && "bg-status-awaiting",
                    kind === "queued" && "bg-text-muted/40",
                    kind === "info" && "bg-status-info",
                  )} />
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] font-medium truncate group-hover:text-brand transition-colors">
                      {issue.title}
                    </div>
                    <div className="text-[11px] text-text-muted truncate flex items-center gap-2 mt-0.5">
                      {project && <span>{project.name}</span>}
                      {issue.git_branch && (
                        <>
                          <span className="text-text-muted/50">·</span>
                          <span className="flex items-center gap-1 font-mono">
                            <GitBranch size={10} />
                            {issue.git_branch}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <StatusBadge kind={kind} label={label} className="shrink-0" />
                  <span className="text-[11px] font-mono text-text-muted w-12 text-right shrink-0">
                    {updated ? relTime(updated) : "—"}
                  </span>
                  <ArrowUpRight
                    size={12}
                    className="text-text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

// ============================================================================
// Helpers
// ============================================================================

interface Buckets {
  total: number;
  running: number;
  awaiting: number;
  done: number;
  failed: number;
  merged: number;
  queued: number;
}

function emptyBuckets(): Buckets {
  return { total: 0, running: 0, awaiting: 0, done: 0, failed: 0, merged: 0, queued: 0 };
}

function computeBuckets(issues: CodexIssue[]): Buckets {
  const out = emptyBuckets();
  for (const i of issues) {
    out.total += 1;
    const merged = i.git_merge_status === "merged";
    const phaseDone = i.current_phase === "done" || i.current_phase === "completed";
    const s = i.status;
    // Merged is its own terminal bucket — it takes precedence so an issue
    // doesn't end up double-counted as both Done and Merged. Without this
    // the donut chart sums to more than `total`.
    if (merged) {
      out.merged += 1;
      continue;
    }
    if (s === "in_progress" || s === "running" || s === "responding") out.running += 1;
    else if (s === "awaiting_approval" || s === "review" || s === "ready") out.awaiting += 1;
    else if (s === "completed" || s === "done" || (s === "open" && phaseDone)) out.done += 1;
    else if (s === "failed" || s === "cancelled" || s === "error") out.failed += 1;
    else out.queued += 1;
  }
  return out;
}

interface ProjectSummary {
  id: string;
  name: string;
  total: number;
  running: number;
  awaiting: number;
  done: number;
  failed: number;
}

function computeProjectSummaries(issues: CodexIssue[], projects: Project[]): ProjectSummary[] {
  const map = new Map<string, ProjectSummary>();
  for (const p of projects) {
    map.set(p.id, { id: p.id, name: p.name, total: 0, running: 0, awaiting: 0, done: 0, failed: 0 });
  }
  for (const i of issues) {
    const pid = i.project_id;
    if (!pid) continue;
    let row = map.get(pid);
    if (!row) {
      row = { id: pid, name: pid.slice(0, 8), total: 0, running: 0, awaiting: 0, done: 0, failed: 0 };
      map.set(pid, row);
    }
    row.total += 1;
    const s = i.status;
    if (s === "in_progress" || s === "running") row.running += 1;
    else if (s === "awaiting_approval" || s === "review") row.awaiting += 1;
    else if (s === "completed" || s === "done") row.done += 1;
    else if (s === "failed" || s === "cancelled") row.failed += 1;
  }
  return Array.from(map.values())
    .filter((row) => row.total > 0)
    .sort((a, b) => b.total - a.total);
}

function computeDailyActivity(
  issues: CodexIssue[],
  days: number,
): { label: string; created: number; finished: number }[] {
  const out: { label: string; created: number; finished: number; date: Date }[] = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - i);
    const label = d.toLocaleDateString("en-US", { weekday: "short" }).slice(0, 3);
    out.push({ label, created: 0, finished: 0, date: d });
  }
  const bucketIndex = (iso: string | null | undefined): number | null => {
    if (!iso) return null;
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return null;
    const d = new Date(t);
    d.setHours(0, 0, 0, 0);
    const idx = out.findIndex((b) => b.date.getTime() === d.getTime());
    return idx >= 0 ? idx : null;
  };
  for (const issue of issues) {
    const ci = bucketIndex(issue.created_at);
    if (ci !== null) out[ci].created += 1;
    if (
      issue.status === "completed" ||
      issue.status === "done" ||
      issue.git_merge_status === "merged"
    ) {
      const fi = bucketIndex(issue.updated_at ?? issue.created_at);
      if (fi !== null) out[fi].finished += 1;
    }
  }
  return out.map(({ label, created, finished }) => ({ label, created, finished }));
}

function humanLabel(status: string | null | undefined): string {
  if (!status) return "Queued";
  const s = status.toLowerCase();
  if (s === "in_progress" || s === "running") return "Running";
  if (s === "completed" || s === "done") return "Done";
  if (s === "failed") return "Failed";
  if (s === "awaiting_approval") return "Awaiting";
  if (s === "open") return "Queued";
  return status;
}

function relTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const diff = Date.now() - t;
  if (diff < 60_000) return "now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h`;
  return `${Math.floor(diff / 86_400_000)}d`;
}

// ============================================================================
// Tiny presentational helpers
// ============================================================================

function Card({
  title,
  subtitle,
  children,
  className,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border border-border-subtle bg-surface-raised p-4",
        className,
      )}
    >
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
        {subtitle && (
          <span className="text-[11px] text-text-muted">{subtitle}</span>
        )}
      </header>
      {children}
    </section>
  );
}

function Skeleton({ h }: { h: number }) {
  return (
    <div
      className="rounded-md bg-gradient-to-r from-surface-input via-surface-hover to-surface-input animate-pulse"
      style={{ height: h }}
    />
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="py-8 text-center text-[12px] text-text-muted">{label}</div>
  );
}
