"""Statement rows from the text layer of a PDF.

A row is a printed line that starts with a date and ends with one or more
amounts. Which amount is the debit, the credit or the balance is decided,
in this order, by:

  1. the column header above it (Debit / Credit / Amount / Balance, also the
     Indonesian names), matched by horizontal position;
  2. a DB / DR / CR marker printed next to the amount, or a minus sign;
  3. the running balance: when an unsigned amount sits next to a balance,
     the sign is the one that makes the previous balance add up.

When none of these settles it the amount is kept as printed. A line that
starts with a date but cannot be read is listed as skipped, with its page and
line, never guessed. Lines under a row that hold only text (a reference, a
second line of the payee) are joined to that row, and its receipt covers
every line it was printed on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..dates import _MONTHS, DateError, parse_date, slash_order
from ..money import AmountError, parse_amount
from .csv_rows import ImportedRow
from .pdf_text import Line, PageText, Word

_MARKERS = {"CR": 1, "K": 1, "DR": -1, "DB": -1, "D": -1}
_MONEY = re.compile(
    r"^[(+\-]?(?:[A-Z]{3}|Rp\.?|[$€£¥])?[(\-]?"
    r"(?:\d{1,3}(?:[,.' ]\d{3})+(?:[.,]\d{1,2})?|\d+[.,]\d{2})"
    r"[)\-]?$"
)
_MARKED = re.compile(r"^(.*\d)(CR|DR|DB)$")

_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FULL_DATES = [
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"),
    re.compile(rf"\d{{1,2}}[ \-](?:{_MONTH})\.?[ \-,]+\d{{4}}", re.I),
    re.compile(rf"(?:{_MONTH})\.? \d{{1,2}},? \d{{4}}", re.I),
]
_SHORT_DATES = [
    re.compile(r"(\d{1,2})[/.\-](\d{1,2})"),
    re.compile(rf"(\d{{1,2}})[ \-]({_MONTH})\.?", re.I),
    re.compile(rf"({_MONTH})\.? (\d{{1,2}})", re.I),
]

_ROLES = {
    "debit": ("debit", "debet", "withdrawal", "withdrawals", "paid out", "money out", "charges", "debits"),
    "credit": ("credit", "kredit", "deposit", "deposits", "paid in", "money in", "payments", "credits"),
    "amount": ("amount", "jumlah", "nominal", "mutasi", "transaction amount"),
    "balance": ("balance", "saldo", "running balance"),
}
_DATE_HEAD = ("date", "tanggal", "tgl", "posted", "posting date", "transaction date", "trans date")
_OPENING = ("opening balance", "balance brought forward", "brought forward", "previous balance",
            "beginning balance", "starting balance", "saldo awal", "balance b/f")
_CLOSING = ("closing balance", "ending balance", "new balance", "saldo akhir", "balance carried forward",
            "carried forward", "balance c/f")


@dataclass
class PdfResult:
    rows: list[ImportedRow]
    skipped: list[tuple[str, str]]
    opening_balance: Decimal | None
    ledger_balance: Decimal | None
    ledger_as_of: date | None
    pages: int


@dataclass
class _Money:
    value: Decimal
    signed: bool  # sign printed or marked, not inferred
    x0: float
    x1: float


def _money(words: list[Word]) -> tuple[list[_Money], int]:
    """Amounts at the end of a line, left to right, and where they start."""
    items: list[_Money] = []
    k = len(words)
    marker = None
    while k > 0:
        w = words[k - 1]
        t = w.text.strip()
        if t.upper() in _MARKERS and marker is None and k > 1:
            marker = _MARKERS[t.upper()]
            k -= 1
            continue
        mark = marker
        m = _MARKED.match(t)
        if m:
            t, mark = m.group(1), _MARKERS[m.group(2)]
        if not _MONEY.match(t):
            break
        try:
            value = parse_amount(t)
        except AmountError:
            break
        signed = value < 0 or mark is not None
        if mark is not None:
            value = abs(value) * mark
        items.append(_Money(value, signed, w.x0, w.x1))
        marker = None
        k -= 1
    if marker is not None:
        k += 1
    items.reverse()
    return items, k


def _header(line: Line) -> list[tuple[str, float, float]] | None:
    words = [(w.text.lower().strip(":"), w.x0, w.x1) for w in line.words]
    cols: list[tuple[str, float, float]] = []
    has_date = False
    k = 0
    while k < len(words):
        matched = False
        for n in (2, 1):
            if k + n > len(words):
                continue
            phrase = " ".join(t for t, _, _ in words[k : k + n])
            if phrase in _DATE_HEAD:
                has_date, matched = True, True
            for role, names in _ROLES.items():
                if phrase in names:
                    cols.append((role, words[k][1], words[k + n - 1][2]))
                    matched = True
                    break
            if matched:
                k += n
                break
        if not matched:
            k += 1
    if not cols or (not has_date and len(cols) < 2):
        return None
    return cols


def _assign(items: list[_Money], cols: list[tuple[str, float, float]]) -> dict[str, _Money] | None:
    out: dict[str, _Money] = {}
    for it in items:
        best = min(cols, key=lambda c: min(abs(it.x1 - c[2]), abs((it.x0 + it.x1) / 2 - (c[1] + c[2]) / 2)))
        if best[0] in out:
            return None
        out[best[0]] = it
    return out


def _date_at_start(text: str):
    for rx in _FULL_DATES:
        m = rx.match(text)
        if m and (m.end() == len(text) or text[m.end()] == " "):
            return m.group(0), True
    for rx in _SHORT_DATES:
        m = rx.match(text)
        if m and (m.end() == len(text) or text[m.end()] == " "):
            return m.group(0), False
    return None, False


def _short_date(token: str, order: str, latest: date) -> date:
    m = _SHORT_DATES[0].fullmatch(token)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        day, month = (a, b) if order == "dmy" else (b, a)
    else:
        m = _SHORT_DATES[1].fullmatch(token)
        if m:
            day, month = int(m.group(1)), _MONTHS[m.group(2).lower()]
        else:
            m = _SHORT_DATES[2].fullmatch(token)
            if not m:
                raise DateError(f"not a date: {token!r}")
            month, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    try:
        when = date(latest.year, month, day)
        if when > latest + timedelta(days=45):
            when = date(latest.year - 1, month, day)
    except ValueError as exc:
        raise DateError(f"not a date: {token!r}") from exc
    return when


def _phrase(text: str, phrases: tuple[str, ...]) -> bool:
    low = " ".join(text.lower().split())
    return any(p in low for p in phrases)


def read_pdf_pages(pages: list[PageText]) -> PdfResult:
    lines = [ln for p in pages for ln in p.lines]
    skipped: list[tuple[str, str]] = [(f"page {p.number}", p.error) for p in pages if p.error]

    tokens: list[str] = []
    full: list[str] = []
    for ln in lines:
        plain = " ".join(w.text for w in ln.words)
        for rx in _FULL_DATES:
            full += rx.findall(plain)
        tok, _ = _date_at_start(plain)
        if tok:
            tokens.append(tok)
    order = slash_order([t if t.count("/") + t.count(".") + t.count("-") >= 2 else t + "/2000" for t in tokens + full])
    parsed_full = []
    for t in full:
        try:
            parsed_full.append(parse_date(t, order))
        except DateError:
            # "31/02/2026" in a header is not a date; it only fails to give a year.
            continue
    latest = max(parsed_full) if parsed_full else None

    rows: list[ImportedRow] = []
    cols: list[tuple[str, float, float]] | None = None
    prev_balance: Decimal | None = None
    opening = ledger = None
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current:
            current.pop("_desc_x")
            rows.append(ImportedRow(**current))
        current = None

    for ln in lines:
        plain = " ".join(w.text for w in ln.words)
        where = f"page {ln.page} line {ln.number}"
        head = _header(ln)
        if head:
            flush()
            cols = head
            continue
        items, start = _money(ln.words)
        if items and (_phrase(plain, _OPENING) or _phrase(plain, _CLOSING)):
            flush()
            bal = items[-1].value
            if _phrase(plain, _OPENING):
                opening = opening if opening is not None else bal
                prev_balance = bal
            else:
                ledger = bal
            continue
        token, has_year = _date_at_start(plain)
        if token is None:
            if (
                current is not None and not items and current["page"] == ln.page
                and ln.number == current["last_line"] + 1 and len(current["raw"].split("\n")) < 5
                and ln.words[0].x0 >= current["_desc_x"] - 2
            ):
                current["raw"] += "\n" + ln.text
                current["description"] += " " + plain
                current["last_line"] = ln.number
                continue
            flush()
            continue
        flush()
        if not items:
            skipped.append((where, "starts with a date but has no amount"))
            continue
        try:
            if has_year:
                when = parse_date(token, order)
            elif latest is None:
                raise DateError(f"{token!r} has no year and the statement prints no full date")
            else:
                when = _short_date(token, order, latest)
        except DateError as exc:
            skipped.append((where, str(exc)))
            continue

        n_date = len(token.split())
        desc_words = ln.words[n_date:start]
        balance: Decimal | None = None
        amount: _Money | None = None
        if cols:
            got = _assign(items, cols)
            if got is None:
                skipped.append((where, "two amounts under one column"))
                continue
            if "balance" in got:
                balance = got["balance"].value
            debit, credit = got.get("debit"), got.get("credit")
            if debit and credit:
                skipped.append((where, "both a debit and a credit"))
                continue
            if debit or credit:
                v = debit or credit
                amount = _Money(abs(v.value) * (-1 if debit else 1), True, v.x0, v.x1)
            elif "amount" in got:
                amount = got["amount"]
            else:
                skipped.append((where, "no amount under a Debit, Credit or Amount column"))
                continue
        else:
            if len(items) == 1:
                amount = items[0]
            elif len(items) == 2:
                amount, balance = items[0], items[1].value
            else:
                skipped.append((where, f"{len(items)} amounts and no column header to tell them apart"))
                continue

        value = amount.value
        if not amount.signed and balance is not None and prev_balance is not None:
            a = abs(value)
            if prev_balance + a == balance:
                value = a
            elif prev_balance - a == balance:
                value = -a
        if balance is not None:
            prev_balance = balance
        current = {
            "first_line": ln.number, "last_line": ln.number, "raw": ln.text, "when": when,
            "amount": value, "description": " ".join(w.text for w in desc_words), "counterparty": "",
            "currency": None, "balance": balance, "page": ln.page,
            "pos": ln.page * 100_000 + ln.number,
            "_desc_x": desc_words[0].x0 if desc_words else ln.words[0].x1,
        }
    flush()
    as_of = max((r.when for r in rows), default=None) if ledger is not None else None
    return PdfResult(rows, skipped, opening, ledger, as_of, len(pages))
