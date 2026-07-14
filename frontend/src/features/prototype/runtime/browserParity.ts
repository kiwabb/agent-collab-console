import { runProcurementApprovalScenario, selectedRequestRef } from "./procurementFixture";
import { RUNTIME_CORE_SOURCE_HASH } from "./runtimeBuildIdentity";
import { RUNTIME_CORE_VERSION, XSTATE_KERNEL_VERSION } from "./runtimeCore";

const EXPECTED_TRANSITIONS = [
  {
    stateHash: "sha256:dc52aef9d3b808020a4eee0156d53fe83d280dafacbcf22024b86d4b14d46194",
    viewModelHash: "sha256:8a08372298a0bffdc8540c54e5f00f83baeda4e17f6c02337cf27cb478dfcb6c",
  },
  {
    stateHash: "sha256:0f746c88f7b4aa7226047f6ac7e3f6c08d4f031a8e40a1d70c555e074af4be54",
    viewModelHash: "sha256:9bbcc45f6f923ece4e461f3ec96af5e6a6a9a4201a46e0d229effa8fc0d7fd43",
  },
  {
    stateHash: "sha256:fdfa2274b2a58f387a527cabd5517e7b5d33cdb5373c168d3e6d5a79da66ff4c",
    viewModelHash: "sha256:83ad5001aa21d47d77b6e521263fd8754d040305dee8f89bfd20612b693e7646",
  },
] as const;

const EXPECTED_ENTITY_ID = "d1a600e6-855f-5ad0-8b8b-56e87a48de90";

export interface BrowserRuntimeParityTransition {
  stateHash: string;
  viewModelHash: string;
}

export interface BrowserRuntimeParityEvidence {
  runtimeCoreVersion: string;
  runtimeCoreSourceHash: string;
  stateMachineKernelVersion: string;
  entityId: string | null;
  transitions: BrowserRuntimeParityTransition[];
  matchesPinnedFixture: boolean;
}

export async function runBrowserRuntimeParityFixture(): Promise<BrowserRuntimeParityEvidence> {
  const results = await runProcurementApprovalScenario("compatibility-runtime-session", true);
  const transitions = results.map((result) => ({
    stateHash: result.report.resultStateHash,
    viewModelHash: result.report.resultViewModelHash,
  }));
  const finalResult = results.at(-1);
  const entityId = finalResult ? (selectedRequestRef(finalResult.state)?.entityId ?? null) : null;
  const matchesPinnedFixture =
    RUNTIME_CORE_VERSION === "0.1.0-spike" &&
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
  return {
    runtimeCoreVersion: RUNTIME_CORE_VERSION,
    runtimeCoreSourceHash: RUNTIME_CORE_SOURCE_HASH,
    stateMachineKernelVersion: XSTATE_KERNEL_VERSION,
    entityId,
    transitions,
    matchesPinnedFixture,
  };
}
