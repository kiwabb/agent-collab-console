import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("approvals refresh cta uses tool motion while syncing gates", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density=\{refreshing \? "approvals-refresh-tool" : "approvals-refresh"\}/);
  assert.match(source, /refreshing && "motion-essential"/);
  assert.match(source, /refreshing \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<RefreshCw size=\{12\} \/>/);
  assert.doesNotMatch(source, /<RefreshCw size=\{12\} className=\{cn\("mr-1\.5", refreshing && "animate-spin"\)\} \/>/);
});

test("approvals row approve action uses tool motion while resolving gates", () => {
  const source = readSource("features/approvals/ApprovalsPage.tsx");

  assert.match(source, /data-density=\{busy \? "approvals-row-approve-tool" : "approvals-row-approve"\}/);
  assert.match(source, /busy && "motion-essential"/);
  assert.match(source, /busy \? \(\s*<AgentThinkingIndicator phase="tool" size=\{12\} \/>/);
  assert.match(source, /<CheckCircle2 size=\{12\} \/>/);
  assert.doesNotMatch(source, /\{busy \? <Loader2 size=\{12\} className="animate-spin" \/> : <CheckCircle2 size=\{12\} \/>}/);
});
