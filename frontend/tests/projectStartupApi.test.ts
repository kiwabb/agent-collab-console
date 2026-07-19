import test from "node:test";
import assert from "node:assert/strict";

import {
  isProjectRunStartError,
  startAllProjectServices,
  startProjectServiceRun,
} from "../src/lib/api/projects";
import { withMockFetch } from "./fetchTestUtils";

test("per-service start preserves the occupied-address refusal payload", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          detail: {
            reason: "service_address_occupied",
            service_id: "backend",
            url: "http://127.0.0.1:8080/api/health/ready",
            http_status: 200,
            readiness_state: "occupied_unknown",
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    async (calls) => {
      const result = await startProjectServiceRun("project id", "backend/service");

      assert.equal(calls.length, 1);
      assert.equal(calls[0]?.input, "/api/projects/project id/services/backend%2Fservice/run/start");
      assert.equal(calls[0]?.init?.method, "POST");
      assert.equal(isProjectRunStartError(result), true);
      if (!isProjectRunStartError(result)) assert.fail("expected a typed refusal");
      assert.deepEqual(result, {
        error: "service_address_occupied",
        service_id: "backend",
        url: "http://127.0.0.1:8080/api/health/ready",
        http_status: 200,
        readiness_state: "occupied_unknown",
      });
    },
  );
});

test("batch start preserves the regeneration-required refusal payload", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          detail: {
            reason: "startup_config_invalid",
            service_id: "frontend",
            message: "Re-analyze startup configuration.",
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    async () => {
      const result = await startAllProjectServices("project-1");

      assert.equal(isProjectRunStartError(result), true);
      if (!isProjectRunStartError(result)) assert.fail("expected a typed refusal");
      assert.equal(result.error, "startup_config_invalid");
      assert.equal(result.service_id, "frontend");
      assert.equal(result.message, "Re-analyze startup configuration.");
    },
  );
});
