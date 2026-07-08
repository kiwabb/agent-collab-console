import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

import { alertSeverityFor, describeAlert } from "../src/features/issues/hooks/useConductorAlerts";

test("severity maps terminal failures to danger and stalls to warn", () => {
  assert.equal(alertSeverityFor("conductor_relaunch_exhausted"), "danger");
  assert.equal(alertSeverityFor("executor_failed_to_start"), "danger");
  assert.equal(alertSeverityFor("artifact_validation_failed"), "warn");
  assert.equal(alertSeverityFor("stall_detected"), "warn");
  assert.equal(alertSeverityFor("conductor_heartbeat_degraded"), "warn");
  assert.equal(alertSeverityFor("something_else"), "info");
});

test("describeAlert builds i18n key + params per event type", () => {
  assert.deepEqual(describeAlert({ type: "conductor_relaunch_exhausted", relaunch_attempts: 3 }), {
    titleKey: "issue.command.alert.relaunchExhausted",
    params: { attempts: 3 },
  });
  assert.deepEqual(
    describeAlert({ type: "executor_failed_to_start", executor: "codex", reason: "exited" }),
    {
      titleKey: "issue.command.alert.executorFailedToStart",
      params: { executor: "codex", reason: "exited" },
    },
  );
  assert.deepEqual(describeAlert({ type: "artifact_validation_failed", role: "engineer" }), {
    titleKey: "issue.command.alert.artifactInvalid",
    params: { role: "engineer" },
  });
  assert.deepEqual(describeAlert({ type: "stall_detected", role: "qa", silence_s: 200.4 }), {
    titleKey: "issue.command.alert.stallDetected",
    params: { role: "qa", silence: 200 },
  });
});

test("describeAlert falls back to sensible defaults on missing fields", () => {
  const { titleKey, params } = describeAlert({ type: "executor_failed_to_start" });
  assert.equal(titleKey, "issue.command.alert.executorFailedToStart");
  assert.equal(params["executor"], "executor");
  assert.equal(params["reason"], "unknown");
});

test("ConductorAlerts marks operational warnings with semantic motion", () => {
  const source = readSource("features/issues/components/ConductorAlerts.tsx");

  assert.match(source, /const isOperationalConductorAlert = alert\.severity !== "info"/);
  assert.match(
    source,
    /data-density=\{isOperationalConductorAlert \? "conductor-alert-operational" : "conductor-alert-info"\}/,
  );
  assert.match(source, /isOperationalConductorAlert && "motion-essential/);
  assert.match(source, /isOperationalConductorAlert && \(/);
  assert.match(source, /animate-shimmer-sweep/);
  assert.doesNotMatch(source, /animate-pulse/);
});
