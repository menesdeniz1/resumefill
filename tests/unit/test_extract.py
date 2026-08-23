import io

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from resumefill.cv.extract import extract_from_pdf, extract_from_txt, load_cv_file


def _build_pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.drawString(72, 700, text)
    c.save()
    return buf.getvalue()


def test_extract_from_txt_decodes_utf8():
    result = extract_from_txt("Mücahid – İstanbul".encode())
    assert "Mücahid" in result.text
    assert "-" in result.text  # en dash normalized
    assert result.warnings == []


def test_extract_from_txt_reports_replacement_chars():
    broken = "Mücahid \ufffd Deniz"
    result = extract_from_txt(broken.encode("utf-8"))
    assert result.warnings, "corrupted input must produce a warning"


def test_extract_from_pdf_returns_text():
    pdf_bytes = _build_pdf("Mücahid Enes Deniz - Software Engineer")
    result = extract_from_pdf(io.BytesIO(pdf_bytes))
    assert "Mücahid Enes Deniz" in result.text


def test_load_cv_file_routes_by_extension(tmp_path):
    txt = tmp_path / "cv.txt"
    txt.write_text("hello CV", encoding="utf-8")
    assert load_cv_file(txt).text == "hello CV"

    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(_build_pdf("PDF CV"))
    assert "PDF CV" in load_cv_file(pdf).text


def test_empty_pages_warning():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.drawString(72, 700, "page one")
    c.showPage()
    c.showPage()  # second page left completely empty
    c.save()

    result = extract_from_pdf(io.BytesIO(buf.getvalue()))
    assert any("no extractable text" in w for w in result.warnings)
    assert "page one" in result.text
