import test from "node:test";
import assert from "node:assert/strict";

import { getProjectResume, importProjectResumePdf, saveProjectResume } from "../src/lib/api";

type FetchCall = {
  input: RequestInfo | URL;
  init?: RequestInit;
};

function withMockFetch(responseBody: unknown, run: (calls: FetchCall[]) => Promise<void>) {
  const originalFetch = globalThis.fetch;
  const calls: FetchCall[] = [];

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  return run(calls).finally(() => {
    globalThis.fetch = originalFetch;
  });
}

test("getProjectResume hits the project resume endpoint", async () => {
  await withMockFetch(
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
      assert.equal(String(calls[0].input), "/api/projects/project-1/resume");
      assert.equal(calls[0].init, undefined);
    },
  );
});

test("saveProjectResume sends markdown with PUT", async () => {
  await withMockFetch(
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
      assert.equal(String(calls[0].input), "/api/projects/project-1/resume");
      assert.equal(calls[0].init?.method, "PUT");
      assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { markdown: "# Jane" });
    },
  );
});

test("importProjectResumePdf posts multipart form data", async () => {
  await withMockFetch(
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
      assert.equal(String(calls[0].input), "/api/projects/project-1/resume/import-pdf");
      assert.equal(calls[0].init?.method, "POST");
      assert.ok(calls[0].init?.body instanceof FormData);
      assert.equal((calls[0].init?.body as FormData).get("file"), file);
    },
  );
});
