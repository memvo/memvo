"""Text layer of PDF files: objects, filters, fonts and text operators.

statement-chrome.pdf and statement-quartz.pdf are made-up statements printed
by two real PDF writers (Skia in headless Chrome, and the macOS Quartz text
filter). The other PDFs are written by tests/pdfgen.py.
"""

import random
from pathlib import Path

import pytest
from pdfgen import make_pdf

from memvo.importers.pdf_text import PdfError, extract

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = [(40, 760, "Date"), (100, 760, "Description"), (330, 760, "Debit"), (400, 760, "Credit"), (480, 760, "Balance")]
PAGE = [
    (40, 800, "Sample statement, 01/11/2026 to 30/11/2026"),
    *HEADER,
    (100, 745, "Opening balance"), (480, 745, "4,149.81"),
    (40, 730, "05/11/2026"), (100, 730, "STREAMLY SUBSCRIPTION"), (330, 730, "17.99"), (480, 730, "4,131.82"),
    (40, 715, "06/11/2026"), (100, 715, "SALARY ACME (PT)"), (400, 715, "2,500.00"), (480, 715, "6,631.82"),
    (100, 703, "REF 7781"),
    (40, 690, "Page 1 of 1"),
]
TEXT = [
    "Sample statement, 01/11/2026 to 30/11/2026",
    "Date   Description   Debit   Credit   Balance",
    "Opening balance   4,149.81",
    "05/11/2026   STREAMLY SUBSCRIPTION   17.99   4,131.82",
    "06/11/2026   SALARY ACME (PT)   2,500.00   6,631.82",
    "REF 7781",
    "Page 1 of 1",
]


def _texts(data: bytes) -> list[list[str]]:
    return [[ln.text for ln in p.lines] for p in extract(data)]


@pytest.mark.parametrize(
    "opts",
    [
        {}, {"compress": False}, {"objstm": True}, {"kern": True}, {"cm": True},
        {"font": "differences"}, {"font": "type0", "objstm": True, "kern": True, "cm": True},
    ],
)
def test_same_lines_whatever_the_writer_does(opts):
    pages = _texts(make_pdf([PAGE, PAGE], **opts))
    if opts.get("font") == "type0":  # composite widths differ, so word gaps do too
        pages = [[" ".join(t.split()) for t in p] for p in pages]
        expected = [" ".join(t.split()) for t in TEXT]
    else:
        expected = TEXT
    assert pages == [expected, expected]


def test_errors_are_plain_messages():
    with pytest.raises(PdfError, match="not a PDF"):
        extract(b"date,amount\n")
    with pytest.raises(PdfError, match="encrypted"):
        extract(make_pdf([PAGE], encrypt=True))
    with pytest.raises(PdfError, match="no pages"):
        extract(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n")


def test_text_operators_forms_and_filters():
    import base64
    import zlib

    from pdfgen import raw_pdf

    content = (
        b"% a comment\nBT /F1 10 Tf 14 TL 40 800 Td (Line\\040one \\(a\\)) Tj T* (Line two) Tj\n"
        b"(Line three) ' 2 0 (Line four) \" 0 Tc 0 Tw 100 Tz 0 Ts\n"
        b"0 -20 TD [(Ker) -40 (ned)] TJ ET\n"
        b"BI /W 2 /H 1 /BPC 8 /CS /G ID \x00\xff\nEI\n"
        b"q 0 1 -1 0 300 300 cm BT /F1 30 Tf 0 0 Td (WATERMARK) Tj ET Q\n"
        b"BT /F1 10 Tf 1 0 0 1 40 600 Tm (Bold) Tj 1 0 0 1 40.3 600 Tm (Bold) Tj ET\n"
        b"/X1 Do\n"
    )
    form = b"BT /F1 10 Tf 40 600 Td (From a form) Tj ET"
    expected = ["Line one (a)", "Line two", "Line three", "Line four", "Kerned", "Bold", "From a form"]
    assert _texts(raw_pdf(content, xobject=form)) == [expected]

    hexed = content.hex().encode() + b">"
    assert _texts(raw_pdf(hexed, xobject=form, filters=b" /Filter /ASCIIHexDecode")) == [expected]
    a85 = base64.a85encode(content, adobe=True)
    assert _texts(raw_pdf(a85, xobject=form, filters=b" /Filter /A85")) == [expected]
    chained = base64.a85encode(zlib.compress(content), adobe=True)
    assert _texts(raw_pdf(chained, xobject=form, filters=b" /Filter [/A85 /Fl]")) == [expected]

    # PNG "up" predictor, as some writers use on compressed streams
    cols = 8
    padded = content + b" " * (-len(content) % cols)
    rows, prev = b"", bytes(cols)
    for k in range(0, len(padded), cols):
        row = padded[k : k + cols]
        rows += b"\x02" + bytes((a - b) & 0xFF for a, b in zip(row, prev))
        prev = row
    pred = zlib.compress(rows)
    parms = b" /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns 8 >>"
    assert _texts(raw_pdf(pred, xobject=form, filters=parms)) == [expected]


def test_scanned_and_unsupported_pages_are_reported():
    assert extract(make_pdf([PAGE, []]))[1].error == "no text on this page (scanned image?)"
    odd = make_pdf([PAGE], compress=False).replace(b"<< /Length", b"<< /Filter /LZWDecode /Length", 1)
    assert "unsupported stream filter LZWDecode" in extract(odd)[0].error


def test_both_fixture_writers():
    chrome = [[" ".join(t.split()) for t in p] for p in _texts((FIXTURES / "pdf" / "statement-chrome.pdf").read_bytes())]
    assert len(chrome) == 2
    rent = chrome[0].index("07 Nov 2026 RENT NOVEMBER 1,450.00 2,674.83")
    assert chrome[0][rent + 1] == "STANDING ORDER 0042"
    quartz = _texts((FIXTURES / "pdf" / "statement-quartz.pdf").read_bytes())
    assert "04/11   PAYROLL NOV   2,800.00 CR   4,754.90" in quartz[0]


@pytest.mark.parametrize("seed", range(4))
def test_damaged_pdfs_never_crash(seed):
    rng = random.Random(seed)
    original = (FIXTURES / "pdf" / "statement-chrome.pdf").read_bytes()
    for _ in range(60):
        data = bytearray(original)
        for _ in range(rng.randint(1, 40)):
            k = rng.randrange(len(data))
            data[k] = rng.randrange(256)
        if rng.random() < 0.3:
            data = data[: rng.randrange(len(data))]
        try:
            pages = extract(bytes(data))
        except PdfError:
            continue
        for p in pages:
            assert all(isinstance(ln.text, str) for ln in p.lines)
