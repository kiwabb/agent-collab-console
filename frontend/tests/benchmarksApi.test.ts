import test from "node:test";
import assert from "node:assert/strict";

import { setBaselineRun, triggerBenchmarkRun } from "../src/lib/api/benchmarks";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

test("triggerBenchmarkRun posts a typed JSON payload through the shared API helper", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          job_id: "job-1",
          status: "queued",
          status_url: "/api/codex/benchmark/jobs/job-1",
        }),
        { status: 200 },
      ),
    async (calls) => {
      const result = await triggerBenchmarkRun({
        label: "regression",
        epochs: 2,
        fixture_ids: ["fixture-a"],
        is_baseline: true,
        dry_run: false,
        project_id: "project-1",
        workspace_id: "workspace-1",
      });

      assert.deepEqual(result, {
        job_id: "job-1",
        status: "queued",
        status_url: "/api/codex/benchmark/jobs/job-1",
      });
      const call = at(calls, 0, "trigger benchmark fetch call");
      assert.equal(call.input, "/api/codex/benchmark/runs");
      assert.equal(call.init?.method, "POST");
      assert.deepEqual(call.init?.headers, { "Content-Type": "application/json" });
      assert.deepEqual(jsonRequestBody(call), {
        label: "regression",
        epochs: 2,
        fixture_ids: ["fixture-a"],
        is_baseline: true,
        dry_run: false,
        project_id: "project-1",
        workspace_id: "workspace-1",
      });
    },
  );
});

test("setBaselineRun returns true only when the backend confirms the baseline pin", async () => {
  await withMockFetch(
    () => new Response(JSON.stringify({ ok: true, run_id: "run-1" }), { status: 200 }),
    async (calls) => {
      const result = await setBaselineRun("run-1");

      assert.equal(result, true);
      const call = at(calls, 0, "set baseline fetch call");
      assert.equal(call.input, "/api/codex/benchmark/baseline/run-1");
      assert.equal(call.init?.method, "POST");
    },
  );
});

test("setBaselineRun preserves the soft-failure boolean contract", async () => {
  const originalConsoleError = console.error;
  const errors: string[] = [];
  console.error = (...data: unknown[]) => {
    errors.push(data.map(String).join(" "));
  };
  try {
    await withMockFetch(
      () => new Response(JSON.stringify({ detail: "missing run" }), { status: 404 }),
      async () => {
        const result = await setBaselineRun("missing");

        assert.equal(result, false);
        assert.deepEqual(errors, ["setBaselineRun(missing) failed: HTTP 404"]);
      },
    );
  } finally {
    console.error = originalConsoleError;
  }
});
