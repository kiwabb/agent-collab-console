import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  runProcurementApprovalScenario,
  selectedRequestRef,
} from "./fixtures/procurementRuntimeFixture";
import { RUNTIME_CORE_SOURCE_HASH } from "../src/features/prototype/runtime/runtimeBuildIdentity";
import {
  RUNTIME_CORE_VERSION,
  XSTATE_KERNEL_VERSION,
} from "../src/features/prototype/runtime/runtimeCore";

const EXPECTED_TRANSITIONS = [
  {
    stateHash: "sha256:f7eb738c805681198cd30fb38584dc1e35f0ee3455b4e6e2f8211ff8d07c3e12",
    viewModelHash: "sha256:8a08372298a0bffdc8540c54e5f00f83baeda4e17f6c02337cf27cb478dfcb6c",
  },
  {
    stateHash: "sha256:54313544292c2fa496a0877499337b4bd359680b1bc668320f6e001fa8462061",
    viewModelHash: "sha256:9bbcc45f6f923ece4e461f3ec96af5e6a6a9a4201a46e0d229effa8fc0d7fd43",
  },
  {
    stateHash: "sha256:a2bbff2041ae041f31701277b637e21767b5b8a86c48fd645879934ad4c64e7f",
    viewModelHash: "sha256:83ad5001aa21d47d77b6e521263fd8754d040305dee8f89bfd20612b693e7646",
  },
] as const;

const EXPECTED_ENTITY_ID = "d1a600e6-855f-5ad0-8b8b-56e87a48de90";

describe("prototype browser runtime parity fixture", () => {
  it("keeps the browser probe pinned to the runtime compatibility evidence", async () => {
    const results = await runProcurementApprovalScenario("compatibility-runtime-session", true);
    const transitions = results.map((result) => ({
      stateHash: result.report.resultStateHash,
      viewModelHash: result.report.resultViewModelHash,
    }));
    const finalResult = results.at(-1);
    const entityId = finalResult ? (selectedRequestRef(finalResult.state)?.entityId ?? null) : null;
    const matchesPinnedFixture =
      RUNTIME_CORE_VERSION === "0.2.0-spike" &&
      /^sha256:[0-9a-f]{64}$/u.test(RUNTIME_CORE_SOURCE_HASH) &&
      XSTATE_KERNEL_VERSION === "5.32.4" &&
      entityId === EXPECTED_ENTITY_ID &&
      transitions.length === EXPECTED_TRANSITIONS.length &&
      transitions.every((transition, index) => {
        const expected = EXPECTED_TRANSITIONS[index];
        return (
          expected !== undefined &&
          transition.stateHash === expected.stateHash &&
          transition.viewModelHash === expected.viewModelHash
        );
      });

    assert.equal(matchesPinnedFixture, true);
    assert.equal(RUNTIME_CORE_VERSION, "0.2.0-spike");
    assert.match(RUNTIME_CORE_SOURCE_HASH, /^sha256:[0-9a-f]{64}$/u);
    assert.equal(XSTATE_KERNEL_VERSION, "5.32.4");
    assert.equal(entityId, EXPECTED_ENTITY_ID);
    assert.equal(transitions.length, 3);
  });
});
