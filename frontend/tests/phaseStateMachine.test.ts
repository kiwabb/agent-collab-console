import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  canTransition,
  isVisible,
  type PhaseSignals,
} from "../src/features/issues/phase/PhaseStateMachine";

const base: PhaseSignals = {
  currentPhase: "requirements",
  hasActiveIssueTask: false,
  isPmTaskDone: false,
  hasArchitectureArtifacts: false,
  allEngineerTasksDone: false,
  isBusy: { to_architecture: false, to_development: false, to_testing: false },
};

describe("PhaseStateMachine", () => {
  it("to_architecture visible only at requirements", () => {
    assert.equal(isVisible("to_architecture", "requirements"), true);
    assert.equal(isVisible("to_architecture", "architecture"), false);
  });

  it("to_development visible at architecture or development", () => {
    assert.equal(isVisible("to_development", "architecture"), true);
    assert.equal(isVisible("to_development", "development"), true);
    assert.equal(isVisible("to_development", "requirements"), false);
  });

  it("to_testing visible at development or testing", () => {
    assert.equal(isVisible("to_testing", "development"), true);
    assert.equal(isVisible("to_testing", "testing"), true);
    assert.equal(isVisible("to_testing", "architecture"), false);
  });

  it("to_architecture requires pm task done and no active task", () => {
    assert.equal(canTransition("to_architecture", base), false);
    assert.equal(canTransition("to_architecture", { ...base, isPmTaskDone: true }), true);
    assert.equal(
      canTransition("to_architecture", { ...base, isPmTaskDone: true, hasActiveIssueTask: true }),
      false,
    );
  });

  it("to_development requires architecture artifacts", () => {
    const at: PhaseSignals = { ...base, currentPhase: "architecture" };
    assert.equal(canTransition("to_development", at), false);
    assert.equal(canTransition("to_development", { ...at, hasArchitectureArtifacts: true }), true);
  });

  it("to_testing requires all engineer tasks done", () => {
    const dev: PhaseSignals = { ...base, currentPhase: "development" };
    assert.equal(canTransition("to_testing", dev), false);
    assert.equal(canTransition("to_testing", { ...dev, allEngineerTasksDone: true }), true);
  });

  it("busy flag blocks own action only", () => {
    const s: PhaseSignals = {
      ...base,
      isPmTaskDone: true,
      isBusy: { to_architecture: true, to_development: false, to_testing: false },
    };
    assert.equal(canTransition("to_architecture", s), false);
  });
});
