from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest

from app.application.project_service import ProjectError
from app.application.resume_service import ResumeImportDraft
from app.domain.models import Project


class FakeProjectService:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    async def get(self, project_id: str) -> Project:
        if project_id != "project-1":
            raise ProjectError(f"project not found: {project_id}")
        return Project(
            id="project-1",
            name="Resume Project",
            repo_path=str(self.repo_path),
            default_branch="main",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )


@pytest.fixture
def resume_project(monkeypatch, tmp_path: Path) -> Path:
    import app.interfaces.api as api_module

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(api_module, "project_service", FakeProjectService(repo))
    return repo


def test_project_resume_round_trips_markdown(client, resume_project: Path):
    initial = client.get("/api/projects/project-1/resume")
    assert initial.status_code == 200, initial.text
    assert initial.json()["exists"] is False
    assert initial.json()["markdown"] == ""

    saved = client.put(
        "/api/projects/project-1/resume",
        json={"markdown": "# Jane Doe\n\nBackend engineer"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["exists"] is True
    assert saved.json()["relative_path"] == ".agent-collab/resume.md"

    disk = resume_project / ".agent-collab" / "resume.md"
    assert disk.read_text(encoding="utf-8") == "# Jane Doe\n\nBackend engineer"

    loaded = client.get("/api/projects/project-1/resume")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["markdown"] == "# Jane Doe\n\nBackend engineer"
    assert loaded.json()["size_bytes"] > 0


def test_project_resume_unknown_project_returns_404(client, resume_project: Path):
    response = client.get("/api/projects/missing/resume")
    assert response.status_code == 404


def test_project_resume_service_unavailable_returns_503(client, monkeypatch):
    import app.interfaces.api as api_module

    monkeypatch.setattr(api_module, "project_service", None)

    response = client.get("/api/projects/project-1/resume")

    assert response.status_code == 503
    assert "Project service unavailable" in response.json()["detail"]


def test_project_resume_import_pdf_returns_draft_without_saving(
    client,
    monkeypatch,
    resume_project: Path,
):
    import app.interfaces.api as api_module

    def fake_extract_pdf_text(*, filename: str | None, content_type: str | None, data: bytes):
        assert filename == "resume.pdf"
        assert content_type == "application/pdf"
        assert data == b"%PDF fake"
        return ResumeImportDraft(
            markdown="# Imported Resume\n\nJane",
            source_filename="resume.pdf",
            page_count=1,
            extracted_pages=1,
            size_bytes=len(data),
            warnings=[],
        )

    monkeypatch.setattr(api_module.resume_service, "extract_pdf_text", fake_extract_pdf_text)

    response = client.post(
        "/api/projects/project-1/resume/import-pdf",
        files={"file": ("resume.pdf", b"%PDF fake", "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["markdown"] == "# Imported Resume\n\nJane"
    assert body["source_filename"] == "resume.pdf"
    assert not (resume_project / ".agent-collab" / "resume.md").exists()


def test_project_resume_import_extracts_pdf_text_with_page_separators(
    client,
    resume_project: Path,
):
    response = client.post(
        "/api/projects/project-1/resume/import-pdf",
        files={"file": ("resume.pdf", _pdf_with_text("Jane Doe"), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_filename"] == "resume.pdf"
    assert body["page_count"] == 1
    assert body["extracted_pages"] == 1
    assert "# Imported Resume" in body["markdown"]
    assert "## Page 1" in body["markdown"]
    assert "Jane Doe" in body["markdown"]
    assert not (resume_project / ".agent-collab" / "resume.md").exists()


def test_project_resume_import_rejects_non_pdf(client, resume_project: Path):
    response = client.post(
        "/api/projects/project-1/resume/import-pdf",
        files={"file": ("resume.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_project_resume_import_rejects_empty_pdf_upload(client, resume_project: Path):
    response = client.post(
        "/api/projects/project-1/resume/import-pdf",
        files={"file": ("resume.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_project_resume_import_rejects_unextractable_pdf(client, resume_project: Path):
    response = client.post(
        "/api/projects/project-1/resume/import-pdf",
        files={"file": ("resume.pdf", _blank_pdf(), "application/pdf")},
    )

    assert response.status_code == 400
    assert "extractable text" in response.json()["detail"]


def _blank_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _pdf_with_text(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
