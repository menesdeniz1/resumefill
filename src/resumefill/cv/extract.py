"""CV text extraction from TXT/PDF sources with quality reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from resumefill.text_utils import count_replacement_chars, sanitize_text


@dataclass
class CvExtraction:
    """Extracted CV text plus warnings surfaced to the user."""

    text: str
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text


def extract_from_txt(data: bytes | str) -> CvExtraction:
    raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    text = sanitize_text(raw)
    warnings: list[str] = []
    broken = count_replacement_chars(text)
    if broken:
        warnings.append(
            f"{broken} unreadable character(s) found in the file. "
            "Some words may be corrupted — verify filled fields before submitting."
        )
    return CvExtraction(text=text, warnings=warnings)


def extract_from_pdf(file_stream) -> CvExtraction:
    """Extract text from a PDF file-like object or path."""
    reader = PdfReader(file_stream)
    pages = [(page.extract_text() or "") for page in reader.pages]
    empty_pages = sum(1 for p in pages if not p.strip())
    joined = "\n".join(pages)
    text = sanitize_text(joined)

    warnings: list[str] = []
    if empty_pages:
        warnings.append(
            f"{empty_pages} of {len(pages)} PDF page(s) contained no extractable text "
            "(possibly scanned images)."
        )
    broken = count_replacement_chars(text)
    if broken:
        warnings.append(
            f"{broken} unreadable character(s) extracted from the PDF. "
            "Names or words may be corrupted — consider uploading a TXT version of your CV."
        )
    return CvExtraction(text=text, warnings=warnings)


def load_cv_file(path: Path) -> CvExtraction:
    """Load a CV from disk by extension."""
    if path.suffix.lower() == ".pdf":
        return extract_from_pdf(str(path))
    return extract_from_txt(path.read_bytes())
