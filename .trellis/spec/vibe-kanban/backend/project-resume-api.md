# Project Resume API Contract

## Scenario: Project Resume Markdown + PDF Import

### 1. Scope / Trigger

- Trigger: adding or changing project-level resume storage, resume API
  payloads, PDF import behavior, or the frontend resume API client.
- The resume is a human-editable project artifact, not a database row.

### 2. Signatures

- Storage path: `<project.repo_path>/.agent-collab/resume.md`.
- API: `GET /api/projects/{project_id}/resume` returns `ResumeResponse`.
- API: `PUT /api/projects/{project_id}/resume` accepts
  `{ "markdown": string }` and returns `ResumeResponse`.
- API: `POST /api/projects/{project_id}/resume/import-pdf` accepts
  multipart field `file` and returns `ResumeImportResponse`.
- Frontend API: `getProjectResume`, `saveProjectResume`,
  `importProjectResumePdf` are explicitly re-exported from `@/lib/api`.

### 3. Contracts

- `ResumeResponse`: `project_id`, `markdown`, `exists`, `relative_path`,
  `updated_at`, `size_bytes`.
- `ResumeImportResponse`: `project_id`, `markdown`, `source_filename`,
  `page_count`, `extracted_pages`, `size_bytes`, `warnings`.
- `relative_path` is always `.agent-collab/resume.md`.
- PDF import returns an editable markdown draft only. It must not write
  `.agent-collab/resume.md`; saving requires a later explicit `PUT`.
- PDF parsing uses `pypdf` text extraction. OCR, layout recreation,
  section classification, and PDF export are out of scope.
- Resume and PDF contents are user personal data. Do not log file bodies,
  extracted text, or markdown contents.

### 4. Validation & Error Matrix

- `project_service is None` -> HTTP `503`.
- Unknown project id -> HTTP `404`.
- Missing or inaccessible `project.repo_path` -> HTTP `400`.
- Existing resume path is not a file -> HTTP `400`.
- Saved or submitted markdown exceeds the service byte limit -> HTTP `400`.
- Missing `pypdf` dependency -> HTTP `503`.
- Non-PDF upload, empty upload, oversize upload, unreadable PDF, encrypted
  PDF, zero-page PDF, or PDF with no extractable text -> HTTP `400`.
- Pages that fail extraction may add warnings, as long as at least one page
  yields text.

### 5. Good/Base/Bad Cases

- Good: `PUT` writes markdown to `.agent-collab/resume.md`; a later `GET`
  returns the same markdown and updated metadata.
- Good: `POST import-pdf` returns `# Imported Resume` with `## Page N`
  separators and leaves the saved resume file untouched.
- Base: no saved resume returns `exists=false`, `markdown=""`,
  `updated_at=null`, and `size_bytes=0`.
- Bad: importing a PDF directly overwrites the saved resume.
- Bad: logging extracted resume text on validation or parsing errors.
- Bad: adding a database table for a single canonical markdown artifact.

### 6. Tests Required

- Backend endpoint test: empty then saved resume round-trips markdown and
  writes `.agent-collab/resume.md`.
- Backend endpoint test: unknown project returns `404`.
- Backend endpoint test: unavailable project service returns `503`.
- Backend endpoint test: PDF import returns a draft with page separators and
  does not save the file.
- Backend endpoint tests: non-PDF, empty PDF, and unextractable PDF return
  useful `400` errors.
- Frontend API test: typed functions call the expected URLs, methods, JSON
  body, and multipart body.
- Frontend source/i18n tests: sidebar/page keys exist in both locales and
  `@/lib/api` compatibility exports include the resume functions.

### 7. Wrong vs Correct

Wrong:

```python
draft = resume_service.extract_pdf_text(...)
resume_service.write(project.repo_path, draft.markdown)
return draft
```

Correct:

```python
draft = resume_service.extract_pdf_text(...)
return ResumeImportResponse(markdown=draft.markdown, ...)
```
