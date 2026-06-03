import test from "node:test";
import assert from "node:assert/strict";

import { deriveBudgetMeterState, type BudgetMeterDerived } from "../src/features/issues/components/BudgetMeter";
import type { IssueBudgetStatus } from "../src/lib/types";

function makeStatus(overrides: Partial<IssueBudgetStatus> = {}): IssueBudgetStatus {
  return {
    issue_id: "i-1",
    spent_usd: 0,
    budget_usd: 10,
    remaining_usd: 10,
    used_ratio: 0,
    soft_warn: false,
    over_budget: false,
    soft_warn_ratio: 0.8,
    has_ceiling: true,
    budget_source: "issue",
    ...overrides,
  };
}

function assertState(derived: BudgetMeterDerived, expected: BudgetMeterDerived["state"]) {
  assert.equal(derived.state, expected);
}

test("null status → empty state with zero fill", () => {
  const d = deriveBudgetMeterState(null);
  assertState(d, "empty");
  assert.equal(d.fillRatio, 0);
  assert.equal(d.percent, null);
});

test("unlimited issue (budget_usd=0) → unlimited state, no bar", () => {
  const d = deriveBudgetMeterState(
    makeStatus({ has_ceiling: false, budget_usd: 0, used_ratio: null, remaining_usd: null }),
  );
  assertState(d, "unlimited");
  assert.equal(d.fillRatio, 0);
  assert.equal(d.percent, null);
});

test("healthy: spent under soft_warn_ratio", () => {
  // spent=2, budget=10 → ratio 0.2, threshold 0.8 → healthy
  const d = deriveBudgetMeterState(
    makeStatus({ spent_usd: 2, budget_usd: 10, used_ratio: 0.2, remaining_usd: 8 }),
  );
  assertState(d, "healthy");
  assert.equal(d.fillRatio, 0.2);
  assert.equal(d.percent, 20);
});

test("soft_warn: spent at threshold trips flag", () => {
  // spent=8.5, budget=10 → ratio 0.85, threshold 0.8 → soft_warn
  const d = deriveBudgetMeterState(
    makeStatus({
      spent_usd: 8.5,
      budget_usd: 10,
      used_ratio: 0.85,
      remaining_usd: 1.5,
      soft_warn: true,
    }),
  );
  assertState(d, "soft_warn");
  assert.equal(d.fillRatio, 0.85);
  assert.equal(d.percent, 85);
});

test("soft_warn: ratio >= threshold but flag false still falls into soft_warn (defensive)", () => {
  // Some backend rollouts may forget to set soft_warn on the payload; the UI
  // should still render the warning band when the ratio hits the threshold.
  const d = deriveBudgetMeterState(
    makeStatus({
      spent_usd: 9,
      budget_usd: 10,
      used_ratio: 0.9,
      remaining_usd: 1,
      soft_warn: false,
    }),
  );
  assertState(d, "soft_warn");
});

test("over: spent at or over ceiling", () => {
  const d = deriveBudgetMeterState(
    makeStatus({
      spent_usd: 11,
      budget_usd: 10,
      used_ratio: 1.1,
      remaining_usd: -1,
      over_budget: true,
      soft_warn: true,
    }),
  );
  assertState(d, "over");
  // fill is clamped to 1.0 even when over_budget
  assert.equal(d.fillRatio, 1);
  assert.equal(d.percent, 100);
});

test("fillRatio is clamped to [0, 1] for out-of-range inputs", () => {
  // Negative spent (shouldn't happen, but defensive)
  const lo = deriveBudgetMeterState(
    makeStatus({ spent_usd: -2, used_ratio: -0.2, remaining_usd: 12 }),
  );
  assert.equal(lo.fillRatio, 0);

  // Excessive ratio (defensive)
  const hi = deriveBudgetMeterState(
    makeStatus({
      spent_usd: 999,
      used_ratio: 99,
      remaining_usd: -989,
      over_budget: true,
    }),
  );
  assert.equal(hi.fillRatio, 1);
});

test("toneClass reflects state", () => {
  const healthy = deriveBudgetMeterState(makeStatus({ used_ratio: 0.1 }));
  assert.match(healthy.toneClass, /done/);

  const warn = deriveBudgetMeterState(makeStatus({ used_ratio: 0.85, soft_warn: true }));
  assert.match(warn.toneClass, /awaiting/);

  const over = deriveBudgetMeterState(makeStatus({ over_budget: true, used_ratio: 1.0 }));
  assert.match(over.toneClass, /failed/);

  const unlim = deriveBudgetMeterState(makeStatus({ has_ceiling: false, used_ratio: null }));
  assert.match(unlim.toneClass, /muted/);
});
