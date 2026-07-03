# Resume Maintenance + PDF Import E2E Validation

Date: 2026-07-03  
Updated: 2026-07-04 01:40 CST  
Frontend: `http://127.0.0.1:4000`  
Backend: `http://127.0.0.1:9000`  
LLM baseurl: `http://127.0.0.1:8317/v1`  
LLM key: `sk-cliproxy-c94c...e965bc`  
LLM model: `gpt-5.5`

## Result

Status: passed on fresh rerun `rerun-20260704-012828`.

The original requested runtime path recovered and passed:

- `GET http://127.0.0.1:8317/v1/models`: 200, includes `gpt-5.5`.
- Backend `/api/runtime-catalog/test` using persisted catalog values: 200 with `success: true`, latency `21271.3ms` during the resumed probe.
- Browser settings page runtime test for `Codex OpenAI GPT-5.5`: success, visible latency `4530ms` on the rerun screenshot.
- Endpoint remains `http://127.0.0.1:8317/v1`.
- Model remains `gpt-5.5`.
- Protocol remains `openai`.
- Stored API key remains masked in the browser/API response.

The resume maintenance and PDF import flow passed the fresh browser/API validation:

- `/resume` renders with the E2E project selected.
- Empty resume state loads correctly.
- PDF import endpoint extracts a draft and does not write `.agent-collab/resume.md`.
- Browser edit/save writes the markdown to disk.
- Reload loads the saved markdown.
- Unsaved project switch guard appears and keeps the project unchanged.
- Mobile 375px layout has no horizontal overflow, 44px controls, usable editor, and working nav drawer.

The fresh rerun used marker `PDF_IMPORT_BROWSER_RERUN_2026_07_04_012828` and final browser-save marker `FINAL_BROWSER_SAVE_RERUN_2026_07_04_012828`.

## Historical Recovery Notes

Earlier in the same validation session, the local `cli-proxy` completion endpoint was blocked:

- `POST /v1/chat/completions` with `gpt-5.5` timed out with no bytes after 60s.
- A longer `POST /v1/chat/completions` probe with `gpt-5.5` and `max_tokens: 1` waited 600s and still received 0 bytes (`HTTP:000`, curl timeout).
- The matching `cli-proxy` log recorded the request from `2026-07-04T00:02:40+08:00` to `2026-07-04T00:12:41+08:00`, then returned `500` with `context canceled`.
- `POST /v1/completions` timed out with no bytes after 30s.
- `POST /v1/responses` is not advertised by the proxy and also timed out.
- A later resumed probe and browser rerun succeeded, so this is no longer a remaining blocker.

Alternative MiniMax endpoint probe:

- Base URL: `https://api.minimaxi.com/v1`
- Key: `sk-cp-zU...x4Dpxs`
- `GET /v1/models`: 200 in 0.759s; returned models include `MiniMax-M3`, `MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, `MiniMax-M2.5`, and related variants.
- Direct `POST /v1/chat/completions` with `MiniMax-M3`: 200 in 4.304s; returned visible content ending in `pong`.
- Backend `/api/runtime-catalog/test` using the existing OpenAI-protocol executor plus endpoint/key/model overrides: 200 with `success: true`, backend latency `2334.3ms`.
- The runtime catalog was not persisted to this alternative endpoint during this probe.

## Issues Found And Actions Taken

1. Frontend formatting check failed for:
   - `frontend/src/lib/types.ts`
   - `frontend/src/lib/i18n.ts`
   - `frontend/src/components/runtime/RuntimeCatalogEditor.tsx`

   Action: ran Prettier on those files and re-ran the focused checks.

2. Runtime catalog test endpoint had a hard-coded 10s timeout.

   Action: changed `backend/app/interfaces/api.py` to use the runtime catalog conductor timeout, clamped to 10s-120s. Updated `backend/tests/test_runtime_catalog_api_contract.py` to assert the 120s timeout.

3. `cli-proxy` completion requests timed out after the app timeout fix during the first validation attempt.

   Action: restarted the local proxy attempt. A new proxy process took port 8317, but `chat/completions` still timed out. Per follow-up request, ran a longer 600s probe; curl received no bytes and the proxy log recorded a final `500 context canceled`. On the resumed run, the same requested `gpt-5.5` runtime path recovered and passed both backend and browser runtime tests.

## Verification Commands

- Backend focused tests:
  `backend/.venv/bin/python -m pytest tests/test_resume_api.py tests/test_runtime_catalog_api_contract.py -v`
  Result: 10 passed on 2026-07-04 01:38 CST.

- Frontend focused tests:
  `node --import tsx --test tests/resumeStats.test.ts tests/resumeApi.test.ts tests/resumeI18n.test.ts tests/apiCompatibilityExports.test.ts`
  Result: 13 passed on 2026-07-04 01:37 CST.

- Frontend focused Prettier:
  `npx prettier --check src/lib/types.ts src/lib/i18n.ts src/components/runtime/RuntimeCatalogEditor.tsx tests/resumeI18n.test.ts tests/apiCompatibilityExports.test.ts src/features/resume/ResumePage.tsx src/features/resume/ResumeSidebar.tsx`
  Result: passed on 2026-07-04 01:37 CST.

- Frontend focused lint:
  `npx next lint --file ...`
  Result: no ESLint warnings or errors for the resume/runtime touched files on 2026-07-04 01:38 CST.

- Full frontend lint:
  `npm run lint`
  Result: exit 0, with existing `WorkbenchPage.tsx` hook warnings outside this validation path.

- Full frontend type check:
  `npx tsc --noEmit --pretty false`
  Result: failed on broad baseline issues outside this validation path, including benchmark/audit/conductor/workspace missing exports and i18n key typing errors.

- Runtime long-wait probe:
  `POST http://127.0.0.1:8317/v1/chat/completions` with masked bearer key, model `gpt-5.5`, and `max_tokens: 1`
  Historical result: curl timed out after 600.008644s with 0 bytes received (`HTTP:000`). Matching proxy log returned `500 context canceled` after roughly 601s.

- Runtime resumed backend test:
  `POST http://127.0.0.1:9000/api/runtime-catalog/test` with persisted executor `codex-openai-gpt55` and model `gpt-5.5`
  Result: 200, `success: true`, latency `21271.3ms`.

- Runtime resumed browser test:
  Settings → 运行时配置 → `Codex OpenAI GPT-5.5` → 测试
  Result: visible success latency `4530ms`.

- Alternative MiniMax direct model list:
  `GET https://api.minimaxi.com/v1/models` with masked bearer key
  Result: 200 in 0.759s; includes `MiniMax-M3`.

- Alternative MiniMax direct chat:
  `POST https://api.minimaxi.com/v1/chat/completions` with masked bearer key, model `MiniMax-M3`, and `max_tokens: 64`
  Result: 200 in 4.304s; response produced visible `pong` content.

- Alternative MiniMax backend runtime test:
  `POST http://127.0.0.1:9000/api/runtime-catalog/test` with `api_endpoint`, `api_key`, and `model_id` overrides
  Result: 200, `success: true`, latency `2334.3ms`.

## Fresh Rerun Browser Evidence

Rerun artifact directory:
`/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/`

### Rerun PDF Fixture

Generated PDF text extraction:

- pages: 1
- contains `E2E Resume Candidate Rerun`: yes
- contains `PDF_IMPORT_BROWSER_RERUN_2026_07_04_012828`: yes
- rendered PNG visually checked: clear text, no clipping or overlap

![Rerun PDF render](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/pdf-render-1.png)

### Rerun Runtime Settings

Browser verified:

- `Codex OpenAI GPT-5.5` executor visible.
- endpoint/model/protocol values correct.
- API key is not visible.
- no untranslated runtime keys.
- no horizontal overflow.
- runtime test succeeded and displayed `4530ms`.

![Rerun OpenAI runtime test success](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-03c-settings-gpt55-test-success-viewport.png)

### Rerun Clean Resume Start

Browser verified:

- E2E project selected.
- textarea empty after deleting the previous saved E2E resume.
- save disabled.
- import enabled.
- no horizontal overflow.

![Rerun clean resume start](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-04-resume-clean-start.png)

### Rerun PDF Import Contract

Real multipart request:

- `POST /api/projects/df4ab95a-a081-4e30-998f-a4dbbe73eab5/resume/import-pdf`
- status: 200
- response time: 0.065317s
- page_count: 1
- extracted_pages: 1
- source_filename: `resume-import-rerun.pdf`
- markdown contains `E2E Resume Candidate Rerun`
- markdown contains `PDF_IMPORT_BROWSER_RERUN_2026_07_04_012828`
- `.agent-collab/resume.md` was absent immediately after import

Browser upload limitation remains: the in-app browser exposes no `setInputFiles` method for the hidden file input, and native macOS file picker automation is not available through the current browser surface. The import was therefore validated by a real multipart request to the same backend endpoint, then the returned draft was edited/saved in the browser.

### Rerun Draft Editing

Browser verified:

- imported draft placed in textarea.
- marker present.
- unsaved state visible.
- save enabled.
- stats updated to 578 characters / 67 words / 21 lines.
- no horizontal overflow.

![Rerun unsaved imported draft](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-05-resume-draft-unsaved.png)

### Rerun Save

Browser verified:

- save action completed.
- page shows synced/saved document state.
- save disabled afterward.
- API and disk both contain `PDF_IMPORT_BROWSER_RERUN_2026_07_04_012828`.
- API and disk both contain `FINAL_BROWSER_SAVE_RERUN_2026_07_04_012828`.

![Rerun saved resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-06-resume-saved.png)

### Rerun Reload

Browser verified:

- saved content reloads into textarea.
- marker and final note still present.
- synced/saved state remains.
- save disabled.

![Rerun reloaded resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-07-resume-reloaded.png)

### Rerun Unsaved Switch Guard

Browser verified:

- unsaved edit made.
- selecting another project opens discard dialog.
- selected project remains `df4ab95a-a081-4e30-998f-a4dbbe73eab5`.
- unsaved marker remains in the editor.

![Rerun unsaved switch guard](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-08-resume-unsaved-switch-guard.png)

### Rerun Mobile 375px

Browser verified:

- viewport: 375x812.
- no horizontal overflow.
- project select height: 44px.
- refresh button height: 44px.
- save button height: 44px.
- import button height: 44px.
- textarea height: 1082px.
- saved marker present.

![Rerun mobile resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-09-resume-mobile-375.png)

### Rerun Mobile Drawer

Browser verified:

- nav drawer opens.
- nav items visible.
- close overlay/button exists.
- no horizontal overflow.

![Rerun mobile drawer](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/rerun-10-resume-mobile-drawer.png)

## Historical Browser Flow Evidence

### PDF Fixture

Generated PDF text extraction:

- pages: 1
- contains `E2E Resume Candidate`: yes
- contains `PDF_IMPORT_BROWSER_E2E_2026_07_03`: yes

![PDF render](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/pdf-render-1.png)

### Runtime Settings

Browser verified:

- OpenAI executor visible.
- endpoint/model/protocol values correct.
- API key is not visible.
- no untranslated runtime keys.
- no horizontal overflow.

![OpenAI runtime executor](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/12-settings-openai-executor-visible.png)

### Clean Resume Start

Browser verified:

- E2E project selected.
- textarea empty.
- save disabled.
- import enabled.
- no horizontal overflow.

![Clean resume start](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/04-resume-start-clean.png)

### PDF Import Contract

Real multipart request:

- `POST /api/projects/df4ab95a-a081-4e30-998f-a4dbbe73eab5/resume/import-pdf`
- status: 200
- page_count: 1
- extracted_pages: 1
- source_filename: `resume-import-e2e.pdf`
- markdown contains `E2E Resume Candidate`
- markdown contains `PDF_IMPORT_BROWSER_E2E_2026_07_03`
- `.agent-collab/resume.md` was absent immediately after import

Browser upload limitation: the in-app browser exposes no `setInputFiles` method for the hidden file input, and native macOS file picker automation is not available through the current browser surface. The import was therefore validated by a real multipart request to the same backend endpoint, then the returned draft was edited/saved in the browser.

### Draft Editing

Browser verified:

- imported draft placed in textarea.
- marker present.
- unsaved state visible.
- save enabled.
- stats updated.
- no horizontal overflow.

![Unsaved imported draft](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/05-resume-draft-unsaved.png)

### Save

Browser verified:

- save action completed.
- page shows synced/saved document state.
- save disabled afterward.
- API and disk both contain the marker and final E2E note.

![Saved resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/06-resume-saved.png)

### Reload

Browser verified:

- saved content reloads into textarea.
- marker and final note still present.
- synced/saved state remains.

![Reloaded resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/07-resume-reloaded.png)

### Unsaved Switch Guard

Browser verified:

- unsaved edit made.
- selecting another project opens discard dialog.
- selected project remains `df4ab95a-a081-4e30-998f-a4dbbe73eab5`.

![Unsaved switch guard](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/08-resume-unsaved-switch-guard.png)

### Mobile 375px

Browser verified:

- viewport: 375x812.
- no horizontal overflow.
- project select height: 44px.
- refresh button height: 44px.
- save button height: 44px.
- import button height: 44px.
- textarea height: 746px.
- saved marker present.

![Mobile resume](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/09-resume-mobile-375.png)

### Mobile Drawer

Browser verified:

- nav drawer opens.
- nav items visible.
- close overlay/button exists.
- no horizontal overflow.

![Mobile drawer](/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/10-resume-mobile-drawer.png)

## Artifacts

- Fresh rerun directory: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/`
- Fresh rerun PDF: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/resume-import-rerun.pdf`
- Fresh rerun PDF import response: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/import-response.json`
- Fresh rerun saved resume API response: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/saved-resume-response.json`
- Fresh rerun screenshots: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/rerun-20260704-012828/screenshots/`
- PDF: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/resume-import-e2e.pdf`
- PDF import response: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/import-response.json`
- Saved resume API response: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/saved-resume-response.json`
- Saved resume file: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/resume-e2e-project/.agent-collab/resume.md`
- Screenshots: `/Users/zhoujiaangyao/zhoujiangyao/AI/jackmouse-ai/agent-collab-console/.trellis/tasks/07-03-resume-maintenance-pdf-import/e2e-artifacts/screenshots/`

## Remaining Blocker

None for the requested validation scope on the fresh rerun.

The requested `baseurl/key/model` completed successfully after the resumed probe:

- `GET /v1/models`: 200, model is listed.
- Backend `/api/runtime-catalog/test`: 200, `success: true`, latency `21271.3ms`.
- Browser runtime test: success, visible latency `4530ms`.

Historical timeout evidence remains below for auditability:

- `POST /v1/chat/completions`: timeout, no bytes after 60s.
- `POST /v1/chat/completions` long-wait retry: timeout, no bytes after 600.008644s; matching proxy log ended with `500 context canceled`.
- `POST /v1/completions`: timeout, no bytes after 30s.

The app-side timeout bug was fixed earlier in the session. The alternative MiniMax OpenAI-compatible endpoint is also usable with `MiniMax-M3`, but the final rerun did not depend on it.
