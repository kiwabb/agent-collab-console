import test from "node:test";
import assert from "node:assert/strict";

import {
  buildPrototypeRouteTargets,
  injectPrototypeNavigationBridge,
  matchPrototypeRoute,
  readPrototypeRoutePatterns,
} from "../src/features/prototype/prototypeNavigation";
import type { Prototype } from "../src/lib/types";

function prototype(id: string, title: string, sourceMeta: string | null): Prototype {
  return {
    id,
    project_id: "project-1",
    title,
    framework: "html",
    current_version: 1,
    source_kind: "code",
    source_ref: `candidate-${id}`,
    source_hash: "sha256:test",
    source_meta_json: sourceMeta,
    created_at: null,
    updated_at: null,
  };
}

test("prototype routes are read from validated source metadata", () => {
  const page = prototype(
    "collections",
    "合集详情",
    JSON.stringify({ route_patterns: ["/collections/:id", 42, "settings"] }),
  );
  assert.deepEqual(readPrototypeRoutePatterns(page), ["/collections/:id"]);
  assert.deepEqual(readPrototypeRoutePatterns(prototype("bad", "Bad", "[1,2]")), []);
});

test("prototype route matching prefers a static route over a dynamic route", () => {
  const targets = buildPrototypeRouteTargets([
    prototype("dynamic", "合集详情", '{"route_patterns":["/collections/:id"]}'),
    prototype("new", "新建合集", '{"route_patterns":["/collections/new"]}'),
  ]);

  assert.equal(matchPrototypeRoute("/collections/42?tab=notes", targets)?.prototypeId, "dynamic");
  assert.equal(matchPrototypeRoute("/collections/new", targets)?.prototypeId, "new");
  assert.equal(matchPrototypeRoute("/missing", targets), null);
});

test("prototype navigation bridge intercepts internal navigation once", () => {
  const html = '<!doctype html><html><body><a href="/tasks">Tasks</a></body></html>';
  const injected = injectPrototypeNavigationBridge(html);
  assert.match(injected, /prototype:navigate/);
  assert.match(injected, /data-prototype-route/);
  assert.equal(injectPrototypeNavigationBridge(injected), injected);
  assert.ok(injected.indexOf("prototype:navigate") < injected.indexOf("</body>"));
});
