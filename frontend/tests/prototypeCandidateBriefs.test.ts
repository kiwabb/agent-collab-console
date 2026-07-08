import test from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";

import {
  buildCodeCandidateBriefOverrides,
  buildSelectedCodeCandidateInstructions,
  countModifiedCodeCandidateBriefs,
  isCodeCandidateBriefModified,
} from "../src/features/prototype/codeCandidateBriefs";
import type { PrototypeCodeCandidate } from "../src/lib/types";

function candidate(id: string, editableBrief: string): PrototypeCodeCandidate {
  return {
    id,
    title: id,
    route: `/${id}`,
    kind: "page",
    framework_hint: "next-app-router",
    source_paths: [`src/app/${id}/page.tsx`],
    primary_source_path: `src/app/${id}/page.tsx`,
    source_hash: `sha256:${id}`,
    source_excerpt: "export default function Page() { return <main /> }",
    editable_brief: editableBrief,
    signals: ["app-router-page"],
    action: "skip",
    prototype_id: `proto-${id}`,
    unsupported_reason: null,
  };
}

test("candidate brief helpers only count and send selected changed briefs", () => {
  const candidates = [
    candidate("agents", "Route: /agents\nDefault brief"),
    candidate("approvals", "Route: /approvals\nDefault brief"),
    candidate("settings", "Route: /settings\nDefault brief"),
  ];
  const briefs = {
    agents: "Route: /agents\nCustom edited brief",
    approvals: "Route: /approvals\nDefault brief",
    settings: "Route: /settings\nUnselected edit",
  };

  assert.equal(isCodeCandidateBriefModified(at(candidates, 0, "candidate"), briefs), true);
  assert.equal(isCodeCandidateBriefModified(at(candidates, 1, "candidate"), briefs), false);

  assert.deepEqual(buildCodeCandidateBriefOverrides(candidates, ["agents", "approvals"], briefs), {
    agents: "Route: /agents\nCustom edited brief",
  });
  assert.equal(countModifiedCodeCandidateBriefs(candidates, ["agents", "approvals"], briefs), 1);
});

test("candidate brief helpers ignore blank overrides", () => {
  const candidates = [candidate("agents", "Route: /agents\nDefault brief")];
  const briefs = { agents: "   " };

  assert.equal(isCodeCandidateBriefModified(at(candidates, 0, "candidate"), briefs), false);
  assert.deepEqual(buildCodeCandidateBriefOverrides(candidates, ["agents"], briefs), {});
  assert.equal(countModifiedCodeCandidateBriefs(candidates, ["agents"], briefs), 0);
});

test("candidate instruction helper only sends selected non-empty guidance", () => {
  assert.deepEqual(
    buildSelectedCodeCandidateInstructions(["agents", "settings"], {
      agents: "  keep card density  ",
      approvals: "unselected guidance",
      settings: "   ",
    }),
    { agents: "keep card density" },
  );
});
