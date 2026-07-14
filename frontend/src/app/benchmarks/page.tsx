"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalibrationPanel,
  Leaderboard,
  RunDiffPanel,
  ScoreCostFrontier,
  TriggerForm,
  useBenchmarkJob,
  type BenchmarkTab,
} from "@/features/benchmarks/BenchmarksPage";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { useI18n } from "@/providers/I18nProvider";
import {
  getBaselineRun,
  getBenchmarkRunDiff,
  getCalibrationReport,
  listBenchmarkRuns,
  setBaselineRun,
} from "@/lib/api/benchmarks";
import type {
  BenchmarkDiff,
  BenchmarkJobStatus,
  BenchmarkRun,
  CalibrationReport,
} from "@/lib/types";

export default function BenchmarksRoutePage() {
  const { t } = useI18n();
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [baseline, setBaseline] = useState<BenchmarkRun | null>(null);
  const [diff, setDiff] = useState<BenchmarkDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [calibration, setCalibration] = useState<CalibrationReport | null>(null);
  const [tab, setTab] = useState<BenchmarkTab>("leaderboard");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const refreshLeaderboard = useCallback(async () => {
    const [r, b] = await Promise.all([listBenchmarkRuns(), getBaselineRun()]);
    setRuns(r);
    setBaseline(b);
  }, []);

  const refreshCalibration = useCallback(async () => {
    const c = await getCalibrationReport(0.7);
    setCalibration(c);
  }, []);

  useEffect(() => {
    void refreshLeaderboard();
    void refreshCalibration();
  }, [refreshLeaderboard, refreshCalibration]);

  const handleSetBaseline = useCallback(
    async (runId: string) => {
      setError("");
      const ok = await setBaselineRun(runId);
      if (!ok) {
        setError("setBaselineRun failed");
        return;
      }
      await refreshLeaderboard();
    },
    [refreshLeaderboard],
  );

  const handleViewDiff = useCallback(async (runId: string) => {
    setSelectedRunId(runId);
    setTab("diff");
    setDiffLoading(true);
    setError("");
    const d = await getBenchmarkRunDiff(runId);
    setDiff(d);
    setDiffLoading(false);
  }, []);

  const handlePickFromFrontier = useCallback(
    (runId: string) => {
      void handleViewDiff(runId);
    },
    [handleViewDiff],
  );

  const handleStarted = useCallback(
    (res: { job_id: string; status: BenchmarkJobStatus; status_url: string }) => {
      setActiveJobId(res.job_id);
    },
    [],
  );

  const handleError = useCallback((message: string) => {
    setError(message);
  }, []);

  const handleViewJob = useCallback((jobId: string) => {
    setActiveJobId(jobId);
  }, []);

  // Poll the active job. When it completes and surfaces a run id,
  // refresh the leaderboard and fetch the new run's diff (if
  // the run is also the user's current selection).
  const { job: activeJob, resultRef: completedRunId } = useBenchmarkJob(activeJobId);
  useEffect(() => {
    if (activeJob?.status === "completed" && completedRunId) {
      void refreshLeaderboard();
      if (selectedRunId === completedRunId) {
        void handleViewDiff(completedRunId);
      }
    }
  }, [activeJob?.status, completedRunId, selectedRunId, refreshLeaderboard, handleViewDiff]);

  const tabs: { id: BenchmarkTab; label: string }[] = useMemo(
    () => [
      { id: "leaderboard", label: "benchmark.tab.leaderboard" },
      { id: "frontier", label: "benchmark.tab.frontier" },
      { id: "diff", label: "benchmark.tab.diff" },
      { id: "calibration", label: "benchmark.tab.calibration" },
    ],
    [],
  );

  return (
    <PageFrame
      eyebrow="benchmarks"
      title={t("benchmark.page.title")}
      description={t("benchmark.page.subtitle")}
    >
      <div className="flex gap-1.5 mb-5">
        {tabs.map((tt) => (
          <button
            key={tt.id}
            type="button"
            onClick={() => setTab(tt.id)}
            className={
              "px-3 py-1.5 rounded-md text-[11.5px] font-mono font-bold tracking-wider uppercase " +
              (tt.id === tab
                ? "bg-brand text-white"
                : "bg-surface-input/50 text-text-muted hover:text-foreground border border-border-subtle/40")
            }
          >
            {t(tt.label)}
          </button>
        ))}
      </div>

      {tab === "leaderboard" && (
        <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-5">
          <div className="space-y-5">
            <TriggerForm
              onStarted={handleStarted}
              onError={handleError}
              onViewJob={handleViewJob}
            />
            {error && (
              <div className="px-4 py-3 rounded-md bg-status-failed/10 border border-status-failed/30 text-[12px] text-status-failed font-mono">
                {error}
              </div>
            )}
            {activeJob && (
              <div className="px-4 py-3 rounded-md bg-surface-input/30 border border-border-subtle/40 text-[12px] font-mono">
                job <span className="text-brand">{activeJob.id}</span> ·{" "}
                {t(`benchmark.status.${activeJob.status}` as Parameters<typeof t>[0])} ·{" "}
                {Math.round(activeJob.progress * 100)}%
              </div>
            )}
            <Leaderboard
              runs={runs}
              baseline={baseline}
              onRefresh={refreshLeaderboard}
              onSetBaseline={handleSetBaseline}
              onViewDiff={handleViewDiff}
            />
          </div>
          <div className="space-y-5">
            <ScoreCostFrontier runs={runs} baseline={baseline} onPickRun={handlePickFromFrontier} />
          </div>
        </div>
      )}

      {tab === "frontier" && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-5">
          <div className="space-y-5">
            <Leaderboard
              runs={runs}
              baseline={baseline}
              onRefresh={refreshLeaderboard}
              onSetBaseline={handleSetBaseline}
              onViewDiff={handleViewDiff}
            />
          </div>
          <div className="space-y-5">
            <ScoreCostFrontier runs={runs} baseline={baseline} onPickRun={handlePickFromFrontier} />
          </div>
        </div>
      )}

      {tab === "diff" && (
        <div className="space-y-5">
          {!selectedRunId && (
            <div className="border-y border-border-subtle bg-surface p-5 text-center text-[12px] text-text-muted">
              {"Pick a run from the leaderboard to view its diff against the current baseline."}
            </div>
          )}
          {selectedRunId && <RunDiffPanel diff={diff} loading={diffLoading} />}
        </div>
      )}

      {tab === "calibration" && (
        <div className="space-y-5">
          <CalibrationPanel report={calibration} />
        </div>
      )}
    </PageFrame>
  );
}
