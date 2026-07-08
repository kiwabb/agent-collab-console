import test from "node:test";
import assert from "node:assert/strict";

import { getProjectResume, importProjectResumePdf, saveProjectResume } from "../src/lib/api";
import { jsonRequestBody, withMockJsonFetch } from "./fetchTestUtils";
import { at } from "./testAssertions";

test("getProjectResume hits the project resume endpoint", async () => {
  await withMockJsonFetch(
    {
      project_id: "project-1",
      markdown: "# Jane",
      exists: true,
      relative_path: ".agent-collab/resume.md",
      updated_at: null,
      size_bytes: 6,
    },
    async (calls) => {
      const result = await getProjectResume("project-1");

      assert.equal(result.markdown, "# Jane");
      assert.equal(calls.length, 1);
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/projects/project-1/resume");
      assert.equal(call.init, undefined);
    },
  );
});

test("saveProjectResume sends markdown with PUT", async () => {
  await withMockJsonFetch(
    {
      project_id: "project-1",
      markdown: "# Jane",
      exists: true,
      relative_path: ".agent-collab/resume.md",
      updated_at: null,
      size_bytes: 6,
    },
    async (calls) => {
      const result = await saveProjectResume("project-1", "# Jane");

      assert.equal(result.exists, true);
      assert.equal(calls.length, 1);
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/projects/project-1/resume");
      assert.equal(call.init?.method, "PUT");
      assert.deepEqual(jsonRequestBody(call), { markdown: "# Jane" });
    },
  );
});

test("importProjectResumePdf posts multipart form data", async () => {
  await withMockJsonFetch(
    {
      project_id: "project-1",
      markdown: "# Imported",
      source_filename: "resume.pdf",
      page_count: 1,
      extracted_pages: 1,
      size_bytes: 4,
      warnings: [],
    },
    async (calls) => {
      const file = new File(["%PDF"], "resume.pdf", { type: "application/pdf" });
      const result = await importProjectResumePdf("project-1", file);

      assert.equal(result.source_filename, "resume.pdf");
      assert.equal(calls.length, 1);
      const call = at(calls, 0, "fetch call");
      assert.equal(call.input, "/api/projects/project-1/resume/import-pdf");
      assert.equal(call.init?.method, "POST");
      assert.ok(call.init?.body instanceof FormData);
      assert.equal((call.init?.body as FormData).get("file"), file);
    },
  );
});
