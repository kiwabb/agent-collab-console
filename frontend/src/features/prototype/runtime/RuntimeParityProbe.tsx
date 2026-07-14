"use client";

import { useEffect, useState } from "react";

import { type BrowserRuntimeParityEvidence, runBrowserRuntimeParityFixture } from "./browserParity";

type ProbeStatus = "running" | "passed" | "failed";

export function RuntimeParityProbe() {
  const [status, setStatus] = useState<ProbeStatus>("running");
  const [evidence, setEvidence] = useState<BrowserRuntimeParityEvidence | null>(null);

  useEffect(() => {
    let active = true;
    void runBrowserRuntimeParityFixture()
      .then((result) => {
        if (!active) return;
        setEvidence(result);
        setStatus(result.matchesPinnedFixture ? "passed" : "failed");
      })
      .catch(() => {
        if (!active) return;
        setStatus("failed");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main
      aria-hidden="true"
      data-runtime-parity-evidence={evidence ? JSON.stringify(evidence) : ""}
      data-runtime-parity-status={status}
      data-testid="runtime-parity-probe"
    />
  );
}
