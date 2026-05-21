import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { getDictionaryValue } from "../src/lib/i18n";

const SRC_ROOT = join(process.cwd(), "src");

function readSource(relativePath: string): string {
  return readFileSync(join(SRC_ROOT, relativePath), "utf-8");
}

test("settings views use i18n keys for newly added settings copy", () => {
  const page = readSource("features/settings/SettingsPage.tsx");
  const route = readSource("app/settings/page.tsx");
  const runtime = readSource("components/runtime/RuntimeCatalogEditor.tsx");
  const agents = readSource("features/workflow/AgentCatalogPanel.tsx");

  [
    't("settings.runtimeLoadFailed")',
    't("settings.agents")',
    't("settings.agentsDesc")',
    't("settings.state.on")',
    't("settings.state.off")',
    't("settings.saveFailed")',
  ].forEach((needle) => {
    assert.match(page, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  assert.match(route, /t\("settings\.title"\)/);

  [
    't("runtime.catalog.valid")',
    't("runtime.catalog.validationFailed")',
    't("runtime.catalog.unknownError")',
    't("runtime.catalog.validate")',
    't("runtime.catalog.test")',
  ].forEach((needle) => {
    assert.match(runtime, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  [
    't("settings.agents")',
    't("settings.agentsDesc")',
    't("settings.refresh")',
    't("settings.loadingCatalog")',
    't("settings.agentCount"',
    't("settings.agentTier.managed.title")',
    't("settings.agentTier.managed.desc")',
    't("settings.agentTier.specialist.title")',
    't("settings.agentTier.specialist.desc")',
    't("settings.agentTier.custom.title")',
    't("settings.agentTier.custom.desc")',
    't("settings.builtIn")',
    't("settings.agentMeta.executor")',
    't("settings.agentMeta.artifact")',
    't("settings.agentMeta.unset")',
    't("settings.agentMeta.none")',
  ].forEach((needle) => {
    assert.match(agents, new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });

  assert.match(agents, /settings\.agentTierEmpty\./);
  assert.match(agents, /settings\.agentRole\.managed\./);
  assert.match(agents, /settings\.agentRole\.specialist\./);
});

test("settings translation keys are available in English", () => {
  assert.equal(getDictionaryValue("en-US", "settings.agents"), "Agent Catalog");
  assert.equal(getDictionaryValue("en-US", "settings.agentsDesc"), "Browse managed workflow roles, predefined specialists, and custom agents available to Conductor.");
  assert.equal(getDictionaryValue("en-US", "settings.runtimeLoadFailed"), "Failed to load runtime catalog");
  assert.equal(getDictionaryValue("en-US", "settings.saveFailed"), "Save failed");
  assert.equal(getDictionaryValue("en-US", "settings.state.on"), "ON");
  assert.equal(getDictionaryValue("en-US", "settings.refresh"), "Refresh");
  assert.equal(getDictionaryValue("en-US", "settings.loadingCatalog"), "Loading catalog");
  assert.equal(getDictionaryValue("en-US", "settings.agentTier.managed.title"), "Managed core");
  assert.equal(getDictionaryValue("en-US", "settings.agentTier.specialist.title"), "Specialists");
  assert.equal(getDictionaryValue("en-US", "settings.agentTier.custom.title"), "Custom agents");
  assert.equal(getDictionaryValue("en-US", "settings.builtIn"), "built-in");
  assert.equal(getDictionaryValue("en-US", "settings.agentRole.managed.architect.name"), "Architect");
  assert.equal(getDictionaryValue("en-US", "settings.agentRole.specialist.code_reviewer.name"), "Code Reviewer");
  assert.equal(getDictionaryValue("en-US", "runtime.catalog.validate"), "Validate");
  assert.equal(getDictionaryValue("en-US", "runtime.catalog.test"), "Test");
});
