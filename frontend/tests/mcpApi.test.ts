import test from "node:test";
import assert from "node:assert/strict";
import { at } from "./testAssertions";
import { withMockJsonFetch } from "./fetchTestUtils";

import { getMcpCatalog } from "../src/lib/api/mcp";

test("getMcpCatalog loads the read-only MCP management projection", async () => {
  await withMockJsonFetch(
    {
      servers: [],
      recent_calls: [],
      audit_window_size: 500,
    },
    async (calls) => {
      const catalog = await getMcpCatalog();

      assert.deepEqual(catalog, {
        servers: [],
        recent_calls: [],
        audit_window_size: 500,
      });
      const call = at(calls, 0, "MCP catalog fetch");
      assert.equal(call.input, "/api/mcp/catalog");
      assert.equal(call.init, undefined);
    },
  );
});
