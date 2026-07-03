"""Project-level resume document storage and PDF text import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

RESUME_DIR_NAME = ".agent-collab"
RESUME_FILE_NAME = "resume.md"
MAX_RESUME_BYTES = 512_000
MAX_PDF_IMPORT_BYTES = 10 * 1024 * 1024


class ResumeError(RuntimeError):
    pass


class ResumeProjectPathError(ResumeError):
    pass


class ResumeValidationError(ResumeError):
    pass


class ResumeDependencyError(ResumeError):
    pass


@dataclass(frozen=True)
class ResumeDocument:
    markdown: str
    exists: bool
    relative_path: str
    updated_at: str | None
    size_bytes: int


@dataclass(frozen=True)
class ResumeImportDraft:
    markdown: str
    source_filename: str
    page_count: int
    extracted_pages: int
    size_bytes: int
    warnings: list[str]


class ResumeService:
    def resume_path(self, project_repo_path: str | None) -> Path:
        if not project_repo_path:
            raise ResumeProjectPathError("project repo path is missing")
        base = Path(project_repo_path).expanduser()
        if not base.exists() or not base.is_dir():
            raise ResumeProjectPathError(f"project repo path is not accessible: {base}")
        return base / RESUME_DIR_NAME / RESUME_FILE_NAME

    def read(self, project_repo_path: str | None) -> ResumeDocument:
        path = self.resume_path(project_repo_path)
        relative_path = f"{RESUME_DIR_NAME}/{RESUME_FILE_NAME}"
        if not path.exists():
            return ResumeDocument(
                markdown="",
                exists=False,
                relative_path=relative_path,
                updated_at=None,
                size_bytes=0,
            )
        if not path.is_file():
            raise ResumeValidationError(f"resume path is not a file: {relative_path}")
        raw = path.read_bytes()
        if len(raw) > MAX_RESUME_BYTES:
            raise ResumeValidationError("saved resume is too large to load")
        markdown = raw.decode("utf-8", errors="replace")
        stat = path.stat()
        return ResumeDocument(
            markdown=markdown,
            exists=True,
            relative_path=relative_path,
            updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            size_bytes=stat.st_size,
        )

    def write(self, project_repo_path: str | None, markdown: str) -> ResumeDocument:
        encoded = markdown.encode("utf-8")
        if len(encoded) > MAX_RESUME_BYTES:
            raise ResumeValidationError("resume markdown is too large")
        path = self.resume_path(project_repo_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        return self.read(project_repo_path)

    def extract_pdf_text(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        data: bytes,
    ) -> ResumeImportDraft:
        safe_filename = " ".join((filename or "resume.pdf").strip().split()) or "resume.pdf"
        lower_name = safe_filename.lower()
        declared_pdf = (content_type or "").split(";", 1)[0].strip().lower() in {
            "application/pdf",
            "application/x-pdf",
        }
        if not declared_pdf and not lower_name.endswith(".pdf"):
            raise ResumeValidationError("only PDF files can be imported")
        if not data:
            raise ResumeValidationError("uploaded PDF is empty")
        if len(data) > MAX_PDF_IMPORT_BYTES:
            raise ResumeValidationError("uploaded PDF is too large")

        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ResumeDependencyError("PDF import dependency is not installed: pypdf") from exc

        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            raise ResumeValidationError("uploaded file is not a readable PDF") from exc

        if getattr(reader, "is_encrypted", False):
            try:
                decrypted = reader.decrypt("")
            except Exception:
                decrypted = 0
            if not decrypted:
                raise ResumeValidationError("encrypted PDFs are not supported")

        page_count = len(reader.pages)
        if page_count == 0:
            raise ResumeValidationError("PDF has no pages")

        chunks: list[str] = []
        warnings: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                try:
                    extracted = page.extract_text(extraction_mode="layout") or ""
                except TypeError:
                    extracted = page.extract_text() or ""
            except Exception:
                warnings.append(f"Page {index} could not be extracted.")
                continue
            text = _normalize_extracted_text(extracted)
            if not text:
                warnings.append(f"Page {index} did not contain extractable text.")
                continue
            chunks.append(f"## Page {index}\n\n{text}")

        if not chunks:
            raise ResumeValidationError("PDF did not contain extractable text")

        markdown = (
            f"# Imported Resume\n\n_Source: {safe_filename}_\n\n"
            + "\n\n---\n\n".join(chunks)
            + "\n"
        )
        return ResumeImportDraft(
            markdown=markdown,
            source_filename=safe_filename,
            page_count=page_count,
            extracted_pages=len(chunks),
            size_bytes=len(data),
            warnings=warnings,
        )


def _normalize_extracted_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    blank_seen = False
    for line in lines:
        if line.strip():
            normalized.append(line)
            blank_seen = False
        elif not blank_seen:
            normalized.append("")
            blank_seen = True
    return "\n".join(normalized).strip()


resume_service = ResumeService()
