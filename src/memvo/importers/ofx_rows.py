"""OFX / QFX reader (both the 1.x SGML form and the 2.x XML form).

Each <STMTTRN>…</STMTTRN> block becomes one row. `raw` is the block exactly
as it appears in the file, so a receipt shows the bank's own record.
FITID, the bank's transaction id, is kept as `ref`; overlapping downloads of
the same account repeat it, which is how duplicates are recognised.
The statement's <LEDGERBAL> is kept so reconcile can check against it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..money import AmountError, parse_amount
from .csv_rows import ImportedRow

_BLOCK = re.compile(r"<STMTTRN>.*?</STMTTRN>", re.S | re.I)
_LEDGER = re.compile(r"<LEDGERBAL>(.*?)</LEDGERBAL>", re.S | re.I)
_CURDEF = re.compile(r"<CURDEF>\s*([A-Za-z]{3})", re.I)


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return html.unescape(m.group(1).strip()) if m else ""


def _ofx_date(value: str) -> date:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", value)
    if not m:
        raise ValueError(f"not an OFX date: {value!r}")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def looks_like_ofx(text: str) -> bool:
    head = text[:2048].upper()
    return "OFXHEADER" in head or "<OFX>" in head


@dataclass
class OfxResult:
    rows: list[ImportedRow]
    skipped: list[tuple[int, str]]
    currency: str | None
    ledger_balance: Decimal | None
    ledger_as_of: date | None


def read_ofx(text: str) -> OfxResult:
    currency = (m.group(1).upper() if (m := _CURDEF.search(text)) else None)
    rows: list[ImportedRow] = []
    skipped: list[tuple[int, str]] = []
    for m in _BLOCK.finditer(text):
        block = m.group(0)
        first = text.count("\n", 0, m.start()) + 1
        last = first + block.count("\n")
        try:
            when = _ofx_date(_tag(block, "DTPOSTED"))
            amount = parse_amount(_tag(block, "TRNAMT"))
        except (ValueError, AmountError) as exc:
            skipped.append((first, str(exc)))
            continue
        name, memo = _tag(block, "NAME") or _tag(block, "PAYEE"), _tag(block, "MEMO")
        rows.append(
            ImportedRow(
                first_line=first,
                last_line=last,
                raw=block,
                when=when,
                amount=amount,
                description=" · ".join(x for x in (name, memo) if x) or _tag(block, "TRNTYPE"),
                counterparty=name,
                currency=_tag(block, "CURRENCY") or currency,
                balance=None,
                ref=_tag(block, "FITID"),
                pos=m.start(),
            )
        )

    balance = as_of = None
    if lm := _LEDGER.search(text):
        try:
            balance = parse_amount(_tag(lm.group(1), "BALAMT"))
            as_of = _ofx_date(_tag(lm.group(1), "DTASOF"))
        except (ValueError, AmountError):
            balance = as_of = None
    return OfxResult(rows, skipped, currency, balance, as_of)
