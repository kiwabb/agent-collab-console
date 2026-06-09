import { readFileSync } from "node:fs";
import { join } from "node:path";
import assert from "node:assert/strict";
import test from "node:test";

const SRC_ROOT = join(process.cwd(), "src");

test("settings runtime catalog loading uses tool motion", () => {
  const source = readFileSync(
    join(SRC_ROOT, "features/settings/SettingsPage.tsx"),
    "utf8",
  );

  assert.match(
    source,
    /import \{ AgentThinkingIndicator \} from "@\/components\/ui\/AgentThinkingIndicator";/,
  );
  assert.match(source, /data-density="settings-runtime-tool-loading"/);
  assert.match(
    source,
    /className="motion-essential relative flex min-h-\[220px\] flex-col items-center justify-center gap-3 overflow-hidden text-xs font-semibold text-text-muted"/,
  );
  assert.match(source, /animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool\/70 to-transparent/);
  assert.match(source, /<AgentThinkingIndicator phase="tool" size=\{24\} \/>/);
  assert.match(source, /t\("settings\.syncingCatalog"\)/);
  assert.doesNotMatch(source, /border-t-brand rounded-full animate-spin/);
  assert.doesNotMatch(source, /text-brand animate-pulse/);
});
