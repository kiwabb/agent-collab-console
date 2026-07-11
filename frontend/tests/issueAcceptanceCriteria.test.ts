import test from "node:test";
import assert from "node:assert/strict";

import { confirmIssueAcceptanceCriteria } from "../src/lib/api/issues";
import { parseAcceptanceCriteriaInput } from "../src/lib/acceptanceCriteria";
import { getDictionaryValue } from "../src/lib/i18n";
import { jsonRequestBody, withMockFetch } from "./fetchTestUtils";
import { readCompactSource } from "./sourceTestUtils";
import { at } from "./testAssertions";

test("acceptance criteria parsing is shared by create and confirm flows", () => {
  assert.deepEqual(parseAcceptanceCriteriaInput(" First \n\n Second\r\n"), ["First", "Second"]);

  const createSource = readCompactSource("features/workspaces/NewIssueDialog.tsx");
  const confirmSource = readCompactSource("features/issues/components/AcceptanceCriteriaCard.tsx");
  assert.match(createSource, /@\/lib\/acceptanceCriteria/);
  assert.match(confirmSource, /@\/lib\/acceptanceCriteria/);
});

test("issue detail exposes the immutable acceptance confirmation action", () => {
  const source = readCompactSource("features/issues/components/AcceptanceCriteriaCard.tsx");

  assert.match(source, /confirmIssueAcceptanceCriteria/);
  assert.match(source, /issue\?\.acceptance_criteria_confirmed === true/);
  assert.match(source, /issue && !confirmed/);
  assert.match(source, /role="alert"/);
  assert.match(source, /console\.error\("acceptance criteria confirmation failed:/);
});

test("acceptance confirmation copy is localized", () => {
  assert.equal(getDictionaryValue("en-US", "issue.side.acceptanceConfirm"), "Confirm criteria");
  assert.equal(getDictionaryValue("zh-CN", "issue.side.acceptanceConfirm"), "确认验收标准");
  assert.equal(getDictionaryValue("en-US", "issue.side.acceptancePending"), "Needs confirmation");
  assert.equal(getDictionaryValue("zh-CN", "issue.side.acceptancePending"), "待确认");
});

test("acceptance confirmation posts the complete immutable contract", async () => {
  await withMockFetch(
    () =>
      new Response(
        JSON.stringify({
          id: "issue-1",
          acceptance_criteria: ["Returns 401"],
          acceptance_criteria_confirmed: true,
        }),
        { status: 200 },
      ),
    async (calls) => {
      const result = await confirmIssueAcceptanceCriteria("issue-1", ["Returns 401"]);

      assert.equal(result.acceptance_criteria_confirmed, true);
      const call = at(calls, 0, "confirm acceptance criteria fetch call");
      assert.equal(call.input, "/api/codex/issues/issue-1/acceptance-criteria/confirm");
      assert.equal(call.init?.method, "POST");
      assert.deepEqual(jsonRequestBody(call), { acceptance_criteria: ["Returns 401"] });
    },
  );
});
