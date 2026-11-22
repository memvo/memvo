"""Text layer of a PDF, with the standard library only.

The goal is narrow: recover the printed lines of a text-based bank statement,
each with its page and line number, so an entry can point back at where it
was printed. Glyphs are placed with the text and graphics matrices, grouped
into lines by baseline, and split into words by the gaps between them.

Supported: classic and compressed object streams, FlateDecode, ASCIIHex and
ASCII85 streams, simple fonts (WinAnsi, MacRoman, Standard, /Differences),
composite fonts with a ToUnicode CMap, and form XObjects. Not supported, and
reported as such: encrypted files, scanned pages (no text), other filters.

Extraction is deterministic: the same bytes always give the same lines, which
is what lets `memvo audit` re-check a PDF entry later.
"""

from __future__ import annotations

import base64
import re
import zlib
from dataclasses import dataclass, field
from typing import NamedTuple


class PdfError(ValueError):
    pass


def looks_like_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


# ---------------------------------------------------------------- objects

class Ref(NamedTuple):
    num: int
    gen: int


class Name(str):
    pass


class Op(str):
    """An operator keyword inside a content stream."""


@dataclass
class Stream:
    dict: dict
    raw: bytes


_WS = b" \t\r\n\x0c\x00"
_DELIM = b"()<>[]{}/%"
_NUM = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


class _Lexer:
    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.i, self.n = data, pos, len(data)

    def skip(self) -> None:
        d, n = self.d, self.n
        while self.i < n:
            c = d[self.i]
            if c in _WS:
                self.i += 1
            elif c == 0x25:  # % comment
                while self.i < n and d[self.i] not in b"\r\n":
                    self.i += 1
            else:
                return

    def token(self):
        """Next object or operator; raises EOFError at the end."""
        self.skip()
        d = self.d
        if self.i >= self.n:
            raise EOFError
        c = d[self.i]
        if c == 0x2F:  # /Name
            j = self.i + 1
            while j < self.n and d[j] not in _WS and d[j] not in _DELIM:
                j += 1
            raw = d[self.i + 1 : j]
            self.i = j
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
            return Name(raw.decode("latin-1"))
        if c == 0x28:  # (literal string)
            return self._literal()
        if c == 0x3C:
            if d[self.i : self.i + 2] == b"<<":
                self.i += 2
                return self._dict()
            j = d.find(b">", self.i)
            if j < 0:
                raise PdfError("unterminated hex string")
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", d[self.i + 1 : j])
            self.i = j + 1
            if len(hexs) % 2:
                hexs += b"0"
            return bytes.fromhex(hexs.decode())
        if c == 0x5B:  # [
            self.i += 1
            out = []
            while True:
                self.skip()
                if self.i < self.n and d[self.i] == 0x5D:
                    self.i += 1
                    return self._refs(out)
                out.append(self.token())
        if c in b"])>}{":
            self.i += 1
            return Op(chr(c))
        m = _NUM.match(d, self.i)
        if m and (m.end() >= self.n or d[m.end()] in _WS or d[m.end()] in _DELIM):
            self.i = m.end()
            s = m.group(0)
            return float(s) if b"." in s else int(s)
        j = self.i
        while j < self.n and d[j] not in _WS and d[j] not in _DELIM:
            j += 1
        if j == self.i:
            j += 1
        word = d[self.i : j].decode("latin-1")
        self.i = j
        if word == "true":
            return True
        if word == "false":
            return False
        if word == "null":
            return None
        return Op(word)

    def _literal(self) -> bytes:
        d, i, depth, out = self.d, self.i + 1, 1, bytearray()
        while i < self.n:
            c = d[i]
            if c == 0x5C:  # backslash
                i += 1
                if i >= self.n:
                    break
                e = d[i]
                if e in _ESC:
                    out.append(_ESC[e])
                elif 0x30 <= e <= 0x37:
                    j = i
                    while j < i + 3 and j < self.n and 0x30 <= d[j] <= 0x37:
                        j += 1
                    out.append(int(d[i:j], 8) & 0xFF)
                    i = j - 1
                elif e == 0x0D:
                    if i + 1 < self.n and d[i + 1] == 0x0A:
                        i += 1
                elif e != 0x0A:
                    out.append(e)
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    self.i = i + 1
                    return bytes(out)
                out.append(c)
            else:
                out.append(c)
            i += 1
        raise PdfError("unterminated string")

    def _dict(self) -> dict:
        items = []
        while True:
            self.skip()
            if self.d[self.i : self.i + 2] == b">>":
                self.i += 2
                break
            if self.i >= self.n:
                raise PdfError("unterminated dictionary")
            items.append(self.token())
        items = self._refs(items)
        out = {}
        for k in range(0, len(items) - 1, 2):
            if isinstance(items[k], Name):
                out[str(items[k])] = items[k + 1]
        return out

    @staticmethod
    def _refs(items: list) -> list:
        out: list = []
        for x in items:
            if isinstance(x, Op) and x == "R" and len(out) >= 2 and isinstance(out[-1], int) and isinstance(out[-2], int):
                gen, num = out.pop(), out.pop()
                out.append(Ref(num, gen))
            else:
                out.append(x)
        return out


_OBJ = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")


class Document:
    def __init__(self, data: bytes):
        if not looks_like_pdf(data):
            raise PdfError("not a PDF file")
        self.data = data
        self.objects: dict[int, object] = {}
        self._load()
        trailer = self._trailer()
        if "Encrypt" in trailer:
            raise PdfError("the PDF is encrypted; save an unprotected copy first")
        root = self.get(trailer.get("Root"))
        if not isinstance(root, dict):
            root = next((o for o in self.objects.values() if isinstance(o, dict) and o.get("Type") == "Catalog"), None)
        if not isinstance(root, dict):
            raise PdfError("no document catalog")
        self.pages: list[tuple[dict, dict]] = []
        self._walk(self.get(root.get("Pages")), {}, 0, set())

    def _load(self) -> None:
        d = self.data
        compressed: list[Stream] = []
        for m in _OBJ.finditer(d):
            lex = _Lexer(d, m.end())
            try:
                obj = lex.token()
                if isinstance(obj, dict):
                    lex.skip()
                    if d.startswith(b"stream", lex.i):
                        obj = self._stream(obj, lex.i + 6)
            except (PdfError, EOFError, IndexError, ValueError):
                continue
            self.objects[int(m.group(1))] = obj
            if isinstance(obj, Stream) and obj.dict.get("Type") == "ObjStm":
                compressed.append(obj)
        direct = set(self.objects)
        for s in compressed:
            try:
                data = decode_stream(s, self)
                count, first = int(self.get(s.dict.get("N", 0))), int(self.get(s.dict.get("First", 0)))
                lex = _Lexer(data)
                header = [lex.token() for _ in range(count * 2)]
                for k in range(count):
                    num, off = header[2 * k], header[2 * k + 1]
                    if num in direct:
                        continue
                    self.objects[num] = _Lexer(data, first + off).token()
            except (PdfError, EOFError, IndexError, ValueError, TypeError):
                continue

    def _stream(self, sdict: dict, pos: int) -> Stream:
        d = self.data
        if d[pos : pos + 2] == b"\r\n":
            pos += 2
        elif d[pos : pos + 1] in (b"\n", b"\r"):
            pos += 1
        length = sdict.get("Length")
        if isinstance(length, int) and length >= 0:
            tail = d[pos + length : pos + length + 32].lstrip(_WS)
            if tail.startswith(b"endstream"):
                return Stream(sdict, d[pos : pos + length])
        end = d.find(b"endstream", pos)
        if end < 0:
            raise PdfError("unterminated stream")
        raw = d[pos:end]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith((b"\n", b"\r")):
            raw = raw[:-1]
        return Stream(sdict, raw)

    def _trailer(self) -> dict:
        best: dict = {}
        for m in re.finditer(rb"trailer\s*<<", self.data):
            try:
                t = _Lexer(self.data, m.end() - 2).token()
            except (PdfError, EOFError):
                continue
            if isinstance(t, dict):
                best = {**best, **t} if "Root" not in t else {**t, **({"Encrypt": best["Encrypt"]} if "Encrypt" in best else {})}
        for obj in self.objects.values():
            if isinstance(obj, Stream) and obj.dict.get("Type") == "XRef":
                if "Encrypt" in obj.dict:
                    best["Encrypt"] = obj.dict["Encrypt"]
                if "Root" in obj.dict and "Root" not in best:
                    best["Root"] = obj.dict["Root"]
        return best

    def get(self, obj, depth: int = 0):
        while isinstance(obj, Ref) and depth < 32:
            obj = self.objects.get(obj.num)
            depth += 1
        return obj

    def _walk(self, node, inherited: dict, depth: int, seen: set) -> None:
        if not isinstance(node, dict) or depth > 64 or id(node) in seen:
            return
        seen.add(id(node))
        attrs = dict(inherited)
        if "Resources" in node:
            attrs["Resources"] = node["Resources"]
        kids = self.get(node.get("Kids"))
        if isinstance(kids, list):
            for k in kids:
                self._walk(self.get(k), attrs, depth + 1, seen)
        elif node.get("Type") == "Page" or "Contents" in node:
            self.pages.append((node, attrs))


def decode_stream(s: Stream, doc: Document | None = None) -> bytes:
    get = doc.get if doc else (lambda x: x)
    filters = get(s.dict.get("Filter"))
    params = get(s.dict.get("DecodeParms"))
    if filters is None:
        return s.raw
    if not isinstance(filters, list):
        filters, params = [filters], [params]
    elif not isinstance(params, list):
        params = [params] * len(filters)
    data = s.raw
    for f, p in zip(filters, params):
        f = get(f)
        if f in ("FlateDecode", "Fl"):
            data = _inflate(data)
            p = get(p)
            if isinstance(p, dict) and int(get(p.get("Predictor", 1)) or 1) >= 10:
                data = _png_unpredict(data, int(get(p.get("Columns", 1)) or 1) * int(get(p.get("Colors", 1)) or 1))
        elif f in ("ASCIIHexDecode", "AHx"):
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            data = bytes.fromhex((hexs + b"0" * (len(hexs) % 2)).decode())
        elif f in ("ASCII85Decode", "A85"):
            body = data.strip()
            body = body[2:] if body.startswith(b"<~") else body
            body = body if body.endswith(b"~>") else body + b"~>"
            data = base64.a85decode(b"<~" + body, adobe=True)
        else:
            raise PdfError(f"unsupported stream filter {f}")
    return data


def _inflate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        d = zlib.decompressobj()
        try:
            return d.decompress(data) + d.flush()
        except zlib.error as exc:
            raise PdfError(f"corrupt compressed stream: {exc}") from exc


def _png_unpredict(data: bytes, columns: int) -> bytes:
    row, out, prev = columns + 1, bytearray(), bytearray(columns)
    for k in range(0, len(data) - row + 1, row):
        kind, line = data[k], bytearray(data[k + 1 : k + row])
        if kind == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif kind == 1:
            for j in range(1, len(line)):
                line[j] = (line[j] + line[j - 1]) & 0xFF
        out += line
        prev = line
    return bytes(out)


# ------------------------------------------------------------------ fonts

_GLYPHS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "quoteright": "'", "quoteleft": "'", "parenleft": "(",
    "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-", "minus": "-",
    "endash": "-", "emdash": "-", "period": ".", "slash": "/", "colon": ":", "semicolon": ";",
    "less": "<", "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_", "grave": "`",
    "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~", "nbspace": " ",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "Euro": "€", "sterling": "£", "yen": "¥",
}


def _glyph(name: str) -> str:
    base = name.split(".")[0]
    if len(base) == 1:
        return base
    if base in _GLYPHS:
        return _GLYPHS[base]
    if m := re.fullmatch(r"uni([0-9A-Fa-f]{4})+", base):
        return "".join(chr(int(base[i : i + 4], 16)) for i in range(3, len(base), 4))
    if m := re.fullmatch(r"u([0-9A-Fa-f]{4,6})", base):
        return chr(int(m.group(1), 16))
    return "�"


def _utf16(b: bytes) -> str:
    return b.decode("utf-16-be", errors="replace") if len(b) >= 2 else b.decode("latin-1")


def _parse_cmap(data: bytes) -> tuple[dict[int, str], int]:
    cmap: dict[int, str] = {}
    width = 0
    for m in re.finditer(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
        for lo in re.findall(rb"<([0-9A-Fa-f]+)>\s*<[0-9A-Fa-f]+>", m.group(1)):
            width = max(width, len(lo) // 2)
    for m in re.finditer(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", m.group(1)):
            cmap[int(src, 16)] = _utf16(bytes.fromhex(dst.decode()))
            width = width or len(src) // 2
    for m in re.finditer(rb"beginbfrange(.*?)endbfrange", data, re.S):
        body = m.group(1)
        for lo, hi, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", body):
            a, b = int(lo, 16), int(hi, 16)
            width = width or len(lo) // 2
            if b - a > 0xFFFF:
                continue
            if rest.startswith(b"["):
                for k, dst in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                    cmap[a + k] = _utf16(bytes.fromhex(dst.decode()))
            else:
                start = bytes.fromhex(rest[1:-1].decode())
                if len(start) < 2:
                    continue
                head, last = start[:-2], int.from_bytes(start[-2:], "big")
                for k in range(b - a + 1):
                    cmap[a + k] = _utf16(head + ((last + k) & 0xFFFF).to_bytes(2, "big"))
    return cmap, width or 1


class Font:
    def __init__(self, doc: Document, fdict: dict):
        g = doc.get
        self.subtype = g(fdict.get("Subtype"))
        self.composite = self.subtype == "Type0"
        self.bytes = 2 if self.composite else 1
        self.cmap: dict[int, str] = {}
        tu = g(fdict.get("ToUnicode"))
        if isinstance(tu, Stream):
            try:
                self.cmap, w = _parse_cmap(decode_stream(tu, doc))
                if self.composite:
                    self.bytes = w if w in (1, 2, 3, 4) else 2
            except PdfError:
                self.cmap = {}
        self.base: dict[int, str] = {}
        if not self.composite:
            enc = g(fdict.get("Encoding"))
            name = enc if isinstance(enc, str) else (g(enc.get("BaseEncoding")) if isinstance(enc, dict) else None)
            codec = {"MacRomanEncoding": "mac_roman"}.get(name or "", "cp1252")
            for c in range(256):
                try:
                    self.base[c] = bytes([c]).decode(codec)
                except UnicodeDecodeError:
                    self.base[c] = bytes([c]).decode("latin-1")
            if isinstance(enc, dict):
                code = 0
                for item in g(enc.get("Differences")) or []:
                    item = g(item)
                    if isinstance(item, int):
                        code = item
                    elif isinstance(item, str):
                        self.base[code] = _glyph(item)
                        code += 1
        self.widths: dict[int, float] = {}
        self.default_width = 500.0
        if self.composite:
            desc = g((g(fdict.get("DescendantFonts")) or [None])[0])
            if isinstance(desc, dict):
                self.default_width = float(g(desc.get("DW", 1000)) or 1000)
                w = g(desc.get("W")) or []
                k = 0
                while k < len(w) - 1:
                    a, b = g(w[k]), g(w[k + 1])
                    if isinstance(b, list):
                        for j, val in enumerate(b):
                            self.widths[int(a) + j] = float(g(val))
                        k += 2
                    elif k + 2 < len(w):
                        for c in range(int(a), int(b) + 1):
                            self.widths[c] = float(g(w[k + 2]))
                        k += 3
                    else:
                        break
        else:
            first, ws = g(fdict.get("FirstChar")), g(fdict.get("Widths"))
            if isinstance(first, int) and isinstance(ws, list):
                for j, val in enumerate(ws):
                    val = g(val)
                    if isinstance(val, (int, float)):
                        self.widths[first + j] = float(val)
            base = str(g(fdict.get("BaseFont")) or "")
            if "Courier" in base:
                self.default_width = 600.0

    def codes(self, s: bytes):
        n = self.bytes
        for k in range(0, len(s) - n + 1, n):
            code = int.from_bytes(s[k : k + n], "big")
            text = self.cmap.get(code)
            if text is None:
                text = self.base.get(code, "") if not self.composite else "�"
            yield code, text, self.widths.get(code, self.default_width) / 1000.0


_FALLBACK = None


def _fallback_font() -> Font:
    global _FALLBACK
    if _FALLBACK is None:
        _FALLBACK = Font.__new__(Font)
        _FALLBACK.composite, _FALLBACK.bytes, _FALLBACK.cmap = False, 1, {}
        _FALLBACK.base = {c: bytes([c]).decode("cp1252", errors="replace") for c in range(256)}
        _FALLBACK.widths, _FALLBACK.default_width = {}, 500.0
    return _FALLBACK


# ------------------------------------------------------------ interpreter

def _mul(a, b):
    return (
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5],
    )


_ID = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass
class Glyph:
    x: float
    y: float
    end: float
    size: float
    text: str


class _Page:
    def __init__(self, doc: Document):
        self.doc = doc
        self.glyphs: list[Glyph] = []
        self.fonts: dict[int, Font] = {}

    def font(self, resources: dict, name: str) -> Font:
        g = self.doc.get
        fonts = g(g(resources).get("Font")) if isinstance(g(resources), dict) else None
        ref = fonts.get(name) if isinstance(fonts, dict) else None
        key = ref.num if isinstance(ref, Ref) else id(ref)
        if key not in self.fonts:
            fdict = g(ref)
            self.fonts[key] = Font(self.doc, fdict) if isinstance(fdict, dict) else _fallback_font()
        return self.fonts[key]

    def run(self, content: bytes, resources, ctm=_ID, depth: int = 0) -> None:
        g = self.doc.get
        resources = g(resources) if isinstance(g(resources), dict) else {}
        lex = _Lexer(content)
        stack: list = []
        gs: list = []
        tc = tw = ts = 0.0
        th, tl, size = 1.0, 0.0, 0.0
        font = _fallback_font()
        tm = tlm = _ID

        def show(s: bytes) -> None:
            nonlocal tm
            for code, text, w0 in font.codes(s):
                m = _mul(tm, ctm)
                trm = _mul((size * th, 0, 0, size, 0, ts), m)
                adv = (w0 * size + tc + (tw if code == 32 and font.bytes == 1 else 0)) * th
                eff = abs(trm[3]) or abs(size)
                if abs(trm[1]) < 0.01 * eff and abs(trm[2]) < 0.01 * eff and trm[0] > 0 and text:
                    x, y = trm[4], trm[5]
                    end = x + adv * (m[0] if m[0] else 1.0)
                    self.glyphs.append(Glyph(x, y, end, eff, text))
                tm = _mul((1, 0, 0, 1, adv, 0), tm)

        while True:
            try:
                tok = lex.token()
            except EOFError:
                break
            except PdfError:
                break
            if not isinstance(tok, Op):
                stack.append(tok)
                continue
            op = str(tok)
            try:
                if op == "BI":
                    end = re.compile(rb"\sEI(?=[\s]|$)").search(content, lex.i)
                    lex.i = end.end() if end else lex.n
                elif op == "q":
                    gs.append(ctm)
                elif op == "Q":
                    ctm = gs.pop() if gs else ctm
                elif op == "cm" and len(stack) >= 6:
                    ctm = _mul(tuple(float(v) for v in stack[-6:]), ctm)
                elif op == "BT":
                    tm = tlm = _ID
                elif op == "Tf" and len(stack) >= 2:
                    font, size = self.font(resources, str(stack[-2])), float(stack[-1])
                elif op == "Tc" and stack:
                    tc = float(stack[-1])
                elif op == "Tw" and stack:
                    tw = float(stack[-1])
                elif op == "Tz" and stack:
                    th = float(stack[-1]) / 100.0
                elif op == "TL" and stack:
                    tl = float(stack[-1])
                elif op == "Ts" and stack:
                    ts = float(stack[-1])
                elif op in ("Td", "TD") and len(stack) >= 2:
                    tx, ty = float(stack[-2]), float(stack[-1])
                    if op == "TD":
                        tl = -ty
                    tm = tlm = _mul((1, 0, 0, 1, tx, ty), tlm)
                elif op == "Tm" and len(stack) >= 6:
                    tm = tlm = tuple(float(v) for v in stack[-6:])
                elif op == "T*":
                    tm = tlm = _mul((1, 0, 0, 1, 0, -tl), tlm)
                elif op == "Tj" and stack and isinstance(stack[-1], bytes):
                    show(stack[-1])
                elif op == "'" and stack and isinstance(stack[-1], bytes):
                    tm = tlm = _mul((1, 0, 0, 1, 0, -tl), tlm)
                    show(stack[-1])
                elif op == '"' and len(stack) >= 3 and isinstance(stack[-1], bytes):
                    tw, tc = float(stack[-3]), float(stack[-2])
                    tm = tlm = _mul((1, 0, 0, 1, 0, -tl), tlm)
                    show(stack[-1])
                elif op == "TJ" and stack and isinstance(stack[-1], list):
                    for part in stack[-1]:
                        if isinstance(part, bytes):
                            show(part)
                        elif isinstance(part, (int, float)):
                            tm = _mul((1, 0, 0, 1, -float(part) / 1000.0 * size * th, 0), tm)
                elif op == "Do" and stack and depth < 8:
                    xobjs = g(resources.get("XObject"))
                    xo = g(xobjs.get(str(stack[-1]))) if isinstance(xobjs, dict) else None
                    if isinstance(xo, Stream) and g(xo.dict.get("Subtype")) == "Form":
                        matrix = g(xo.dict.get("Matrix")) or list(_ID)
                        sub = _mul(tuple(float(g(v)) for v in matrix), ctm)
                        self.run(decode_stream(xo, self.doc), xo.dict.get("Resources", resources), sub, depth + 1)
            except (ValueError, TypeError, IndexError, PdfError, OverflowError):
                # A malformed operator (wrong operand types, a broken form) is
                # dropped on its own; the rest of the page is still read.
                stack.clear()
                continue
            stack.clear()


# ------------------------------------------------------------------ lines

@dataclass
class Word:
    x0: float
    x1: float
    text: str


@dataclass
class Line:
    page: int
    number: int
    words: list[Word] = field(default_factory=list)
    size: float = 0.0

    @property
    def text(self) -> str:
        out, prev = "", None
        for w in self.words:
            if prev is not None:
                out += "   " if w.x0 - prev.x1 > 1.2 * self.size else " "
            out += w.text
            prev = w
        return out


@dataclass
class PageText:
    number: int
    lines: list[Line]
    error: str | None = None


def _lines(page_no: int, glyphs: list[Glyph]) -> list[Line]:
    rows: list[list[Glyph]] = []
    for gl in sorted(glyphs, key=lambda q: (-round(q.y, 1), q.x)):
        if rows and abs(rows[-1][0].y - gl.y) <= 0.35 * max(gl.size, rows[-1][0].size):
            rows[-1].append(gl)
        else:
            rows.append([gl])
    lines: list[Line] = []
    for row in rows:
        row.sort(key=lambda q: q.x)
        size = max(q.size for q in row)
        words: list[Word] = []
        cur: Word | None = None
        last: Glyph | None = None
        for gl in row:
            if last is not None and gl.text == last.text and abs(gl.x - last.x) < 0.15 * size:
                continue  # overprinted glyph (fake bold)
            blank = not gl.text.strip()
            gap = gl.x - last.end if last is not None else 0.0
            if blank or cur is None or gap > 0.18 * size:
                if cur is not None and cur.text:
                    words.append(cur)
                cur = None if blank else Word(gl.x, gl.end, gl.text)
            else:
                cur.text += gl.text
                cur.x1 = max(cur.x1, gl.end)
            last = gl
        if cur is not None and cur.text:
            words.append(cur)
        if words:
            lines.append(Line(page_no, len(lines) + 1, words, size))
    return lines


def extract(data: bytes) -> list[PageText]:
    """Every page of the PDF as numbered lines of words."""
    doc = Document(data)
    if not doc.pages:
        raise PdfError("the PDF has no pages")
    pages: list[PageText] = []
    for k, (page, attrs) in enumerate(doc.pages, start=1):
        p = _Page(doc)
        error = None
        try:
            contents = doc.get(page.get("Contents"))
            parts = contents if isinstance(contents, list) else [contents]
            body = b""
            for part in parts:
                part = doc.get(part)
                if isinstance(part, Stream):
                    body += decode_stream(part, doc) + b"\n"
            p.run(body, attrs.get("Resources", {}))
        except PdfError as exc:
            error = str(exc)
        lines = _lines(k, p.glyphs)
        if not lines and error is None:
            error = "no text on this page (scanned image?)"
        pages.append(PageText(k, lines, error))
    return pages
