import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runBrowserRuntimeParityFixture } from "../src/features/prototype/runtime/browserParity";

describe("prototype browser runtime parity fixture", () => {
  it("keeps the browser probe pinned to the runtime compatibility evidence", async () => {
    const evidence = await runBrowserRuntimeParityFixture();

    assert.equal(evidence.matchesPinnedFixture, true);
    assert.equal(evidence.runtimeCoreVersion, "0.1.0-spike");
    assert.match(evidence.runtimeCoreSourceHash, /^sha256:[0-9a-f]{64}$/u);
    assert.equal(evidence.stateMachineKernelVersion, "5.32.4");
    assert.equal(evidence.entityId, "d1a600e6-855f-5ad0-8b8b-56e87a48de90");
    assert.equal(evidence.transitions.length, 3);
  });
});
