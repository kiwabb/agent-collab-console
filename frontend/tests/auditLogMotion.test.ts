import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("audit log initial loading uses tool motion while syncing trace records", () => {
  const source = readSource("features/audit/AuditLogPage.tsx");

  assert.match(source, /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/);
  assert.match(source, /data-density="audit-log-tool-loading"/);
  assert.match(source, /className="motion-essential relative flex items-center gap-2 overflow-hidden rounded-2xl border border-border-subtle bg-surface-input\/40 px-6 py-12 text-sm text-text-muted"/);
  assert.match(source, /animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool\/70 to-transparent/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{15\} \/>/);
  assert.match(source, /\{t\("auditLog\.loading"\)\}/);
  assert.doesNotMatch(source, /<Loader2 size=\{15\} className="animate-spin" \/> \{t\("auditLog\.loading"\)\}/);
});
