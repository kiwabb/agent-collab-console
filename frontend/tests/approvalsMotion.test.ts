import test from "node:test";
import assert from "node:assert/strict";
import { readCompactSource as readSource } from "./sourceTestUtils";

test("approvals refresh cta uses tool motion while syncing gates", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(
    source,
    /data-density=\{refreshing \? "approvals-refresh-tool" : "approvals-refresh"\}/,
  );
  assert.match(source, /refreshing && "motion-essential"/);
  assert.match(source, /refreshing \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<RefreshCw size=\{12\} \/>/);
  assert.doesNotMatch(
    source,
    /<RefreshCw size=\{12\} className=\{cn\("mr-1\.5", refreshing && "animate-spin"\)\} \/>/,
  );
});

test("approvals row approve action uses tool motion while resolving gates", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(
    source,
    /data-density=\{busy \? "approvals-row-approve-tool" : "approvals-row-approve"\}/,
  );
  assert.match(source, /busy && "motion-essential"/);
  assert.match(source, /busy \? \(?\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<CheckCircle2 size=\{12\} \/>/);
  assert.doesNotMatch(
    source,
    /\{busy \? <Loader2 size=\{12\} className="animate-spin" \/> : <CheckCircle2 size=\{12\} \/>}/,
  );
});

test("approvals row reject action uses tool motion while resolving gates", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(
    source,
    /data-density=\{busy \? "approvals-row-reject-tool" : "approvals-row-reject"\}/,
  );
  assert.match(source, /className=\{cn\(busy && "motion-essential"\)\}/);
  assert.match(source, /busy \? \(?\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<XCircle size=\{12\} \/>/);
});

test("approvals clarification answer cta uses thinking motion while handing off", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(
    source,
    /data-density=\{disabled \? "approvals-answer-thinking" : "approvals-answer"\}/,
  );
  assert.match(source, /disabled && "motion-essential"/);
  assert.match(source, /disabled \? \(\s*<AgentThinkingIndicator phase="thinking" size=\{12\} \/>/);
  assert.match(source, /\) : \(\s*t\("approvals\.sendAnswer"\)\s*\)/);
  assert.doesNotMatch(
    source,
    /\{disabled \? <Loader2 size=\{12\} className="animate-spin" \/> : t\("approvals\.sendAnswer"\)\}/,
  );
});
