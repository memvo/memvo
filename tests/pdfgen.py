"""Writes small PDFs for the tests, the way real generators lay out text.

Three font set-ups cover what statement PDFs use in practice: a standard
WinAnsi font, a subset composite font that only a ToUnicode CMap can decode,
and a simple font with a /Differences encoding. Content can be compressed,
kerned with TJ, placed through a cm matrix, and stored in object streams.
"""

from __future__ import annotations

import zlib

Text = tuple[float, float, str]  # x, y (from bottom), text


def _esc(b: bytes) -> bytes:
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(
    pages: list[list[Text]],
    *,
    font: str = "winansi",
    compress: bool = True,
    objstm: bool = False,
    kern: bool = False,
    cm: bool = False,
    size: float = 9,
    encrypt: bool = False,
) -> bytes:
    chars = sorted({c for page in pages for _, _, t in page for c in t})
    codes = {c: i + 3 for i, c in enumerate(chars)}  # subset glyph ids, unrelated to Unicode
    objs: dict[int, bytes] = {}
    streams: dict[int, tuple[bytes, bytes]] = {}

    def encode(text: str) -> bytes:
        if font == "type0":
            return b"<" + b"".join(f"{codes[c]:04X}".encode() for c in text) + b">"
        if font == "differences":
            return b"<" + b"".join(f"{codes[c]:02X}".encode() for c in text) + b">"
        return b"(" + _esc(text.encode("cp1252")) + b")"

    def show(text: str) -> bytes:
        if kern and len(text) > 3:
            mid = len(text) // 2
            return b"[" + encode(text[:mid]) + b" -20 " + encode(text[mid:]) + b"] TJ"
        return encode(text) + b" Tj"

    font_id, page_ids, content_ids = 3, [], []
    next_id = 4
    if font == "type0":
        objs[3] = b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+Inter /Encoding /Identity-H /DescendantFonts [4 0 R] /ToUnicode 5 0 R >>"
        widths = b" ".join(f"{codes[c]} [{280 if c == ' ' else 560}]".encode() for c in chars)
        objs[4] = b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ABCDEF+Inter /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /DW 560 /W [" + widths + b"] >>"
        bf = b"\n".join(f"<{codes[c]:04X}> <{ord(c):04X}>".encode() for c in chars)
        cmap = (
            b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            + f"{len(chars)} beginbfchar\n".encode() + bf + b"\nendbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end"
        )
        streams[5] = (b"", cmap)
        next_id = 6
    elif font == "differences":
        diff = b" ".join(f"{codes[c]} /{_name(c)}".encode() for c in chars)
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding /Differences [" + diff + b"] >> >>"
    else:
        objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"

    for page in pages:
        lines = ([b"q 0.5 0 0 0.5 0 0 cm"] if cm else []) + [b"BT", f"/F1 {size} Tf".encode()]
        for x, y, text in page:
            if cm:
                lines += [f"1 0 0 1 {x * 2} {y * 2} Tm".encode(), f"/F1 {size * 2} Tf".encode(), show(text)]
            else:
                lines += [f"1 0 0 1 {x} {y} Tm".encode(), show(text)]
        lines.append(b"ET")
        if cm:
            lines.append(b"Q")
        body = b"\n".join(lines)
        cid, pid = next_id, next_id + 1
        next_id += 2
        streams[cid] = (b"", body)
        content_ids.append(cid)
        page_ids.append(pid)
    pages_id = next_id
    for cid, pid in zip(content_ids, page_ids):
        objs[pid] = f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Contents {cid} 0 R >>".encode()
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    objs[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} /Resources << /Font << /F1 3 0 R >> >> >>".encode()
    objs[1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objs[2] = b"<< /Producer (memvo tests) >>"

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}

    def stream_obj(num: int, extra: bytes, data: bytes) -> None:
        if compress:
            data = zlib.compress(data)
            extra += b" /Filter /FlateDecode"
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n<< /Length {len(data)}".encode() + extra + b" >>\nstream\n" + data + b"\nendstream\nendobj\n")

    for num, (extra, data) in streams.items():
        stream_obj(num, extra, data)
    if objstm:
        packed = sorted(objs)
        header, body = b"", b""
        for num in packed:
            header += f"{num} {len(body)} ".encode()
            body += objs[num] + b"\n"
        stm = max(list(objs) + list(streams)) + 1
        stream_obj(stm, f" /Type /ObjStm /N {len(packed)} /First {len(header)}".encode(), header + body)
        xref_id = stm + 1
        out.extend(f"{xref_id} 0 obj\n<< /Type /XRef /Size {xref_id + 1} /Root 1 0 R /Info 2 0 R >>\nstream\n\nendstream\nendobj\n".encode())
        out.extend(f"startxref\n{len(out)}\n%%EOF\n".encode())
        return bytes(out)
    for num in sorted(objs):
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n")
    size_ = max(offsets) + 1
    xref = len(out)
    out.extend(f"xref\n0 {size_}\n0000000000 65535 f \n".encode())
    for n in range(1, size_):
        out.extend(f"{offsets.get(n, 0):010d} 00000 n \n".encode())
    enc = b" /Encrypt << /Filter /Standard /V 1 /R 2 >>" if encrypt else b""
    out.extend(f"trailer\n<< /Size {size_} /Root 1 0 R /Info 2 0 R".encode() + enc + f" >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


_NAMES = {
    " ": "space", ".": "period", ",": "comma", "-": "hyphen", "/": "slash", ":": "colon", "(": "parenleft",
    ")": "parenright", "&": "ampersand", "'": "quotesingle", "*": "asterisk", "#": "numbersign",
}
_DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _name(c: str) -> str:
    if c.isdigit():
        return _DIGITS[int(c)]
    if c.isascii() and c.isalpha():
        return c
    return _NAMES.get(c, f"uni{ord(c):04X}")


def raw_pdf(content: bytes, *, xobject: bytes | None = None, filters: bytes = b"") -> bytes:
    """One page with a hand-written content stream; `xobject` becomes form /X1."""
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >>"
        + (b" /XObject << /X1 6 0 R >>" if xobject is not None else b"") + b" >> >>",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /FirstChar 32 /Widths [600 600] >>",
    }
    out = bytearray(b"%PDF-1.4\n")
    for num in sorted(objs):
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    out += b"4 0 obj\n<< /Length " + str(len(content)).encode() + filters + b" >>\nstream\n" + content + b"\nendstream\nendobj\n"
    if xobject is not None:
        out += (b"6 0 obj\n<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] /Matrix [1 0 0 1 0 -100] /Resources << /Font << /F1 5 0 R >> >> /Length "
                + str(len(xobject)).encode() + b" >>\nstream\n" + xobject + b"\nendstream\nendobj\n")
    out += b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    return bytes(out)
