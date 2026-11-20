"""CSV statement reader.

Each record keeps the exact source text it was parsed from (`raw`) and the
1-based line range it spans, so a receipt can point back at the file.
Quoted fields with embedded newlines span more than one line; that is why
the range is tracked instead of a single line number.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..dates import DateError, parse_date, slash_order
from ..money import AmountError, parse_amount

_ALIASES: dict[str, tuple[str, ...]] = {
    "date": (
        "date", "posted", "posting date", "transaction date", "trans date", "booking date",
        "value date", "tanggal", "tgl", "time", "timestamp", "datetime", "completed date",
    ),
    "amount": ("amount", "jumlah", "nominal", "value", "net amount", "total", "mutasi"),
    "debit": ("debit", "withdrawal", "withdrawals", "paid out", "money out", "out", "debet"),
    "credit": ("credit", "deposit", "deposits", "paid in", "money in", "in", "kredit"),
    "description": (
        "description", "memo", "details", "narrative", "keterangan", "transaction",
        "reference", "remarks", "particulars", "type",
    ),
    "counterparty": ("payee", "merchant", "counterparty", "name", "beneficiary", "to", "from"),
    "currency": ("currency", "ccy", "mata uang"),
    "balance": ("balance", "running balance", "saldo", "closing balance"),
}


@dataclass(frozen=True)
class ColumnMap:
    date: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    description: str | None = None
    counterparty: str | None = None
    currency: str | None = None
    balance: str | None = None

    @classmethod
    def detect(cls, header: list[str], overrides: dict[str, str] | None = None) -> ColumnMap:
        found: dict[str, str] = {}
        lowered = {h.strip().lower(): h for h in header}
        for role, names in _ALIASES.items():
            for name in names:
                if name in lowered and lowered[name] not in found.values():
                    found[role] = lowered[name]
                    break
        for role, col in (overrides or {}).items():
            if role not in _ALIASES:
                raise ValueError(f"unknown column role {role!r}")
            if col not in header:
                raise ValueError(f"column {col!r} not in header {header}")
            found[role] = col
        if "date" not in found:
            raise ValueError(f"no date column found in {header}; pass --map date=<column>")
        if "amount" not in found and not ({"debit", "credit"} & found.keys()):
            raise ValueError(f"no amount or debit/credit column in {header}; pass --map amount=<column>")
        return cls(**found)


@dataclass(frozen=True)
class ImportedRow:
    first_line: int
    last_line: int
    raw: str
    when: date
    amount: Decimal
    description: str
    counterparty: str
    currency: str | None
    balance: Decimal | None
    fields: dict[str, str] = field(default_factory=dict)
    ref: str = ""
    pos: int | None = None


@dataclass
class CsvResult:
    columns: ColumnMap
    rows: list[ImportedRow]
    skipped: list[tuple[int, str]]


def _records(text: str, dialect: type[csv.Dialect] | csv.Dialect):
    lines = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text), dialect)
    start = 1
    for record in reader:
        end = reader.line_num
        raw = "".join(lines[start - 1 : end]).rstrip("\r\n")
        yield start, end, raw, record
        start = end + 1


def read_csv(text: str, overrides: dict[str, str] | None = None) -> CsvResult:
    if text.startswith("﻿"):
        text = text[1:]
    sample = text[:8192]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    records = [r for r in _records(text, dialect) if any(c.strip() for c in r[3])]
    if not records:
        return CsvResult(ColumnMap(date=""), [], [])

    header = [h.strip() for h in records[0][3]]
    columns = ColumnMap.detect(header, overrides)
    idx = {h: i for i, h in enumerate(header)}

    def cell(rec: list[str], col: str | None) -> str:
        if col is None:
            return ""
        i = idx[col]
        return rec[i].strip() if i < len(rec) else ""

    order = slash_order([cell(r[3], columns.date) for r in records[1:]])
    rows: list[ImportedRow] = []
    skipped: list[tuple[int, str]] = []
    for first, last, raw, rec in records[1:]:
        try:
            when = parse_date(cell(rec, columns.date), order)
            amount = _amount(rec, columns, cell)
            bal_text = cell(rec, columns.balance)
            balance = parse_amount(bal_text) if bal_text else None
        except (DateError, AmountError) as exc:
            skipped.append((first, str(exc)))
            continue
        rows.append(
            ImportedRow(
                first_line=first,
                last_line=last,
                raw=raw,
                when=when,
                amount=amount,
                description=cell(rec, columns.description),
                counterparty=cell(rec, columns.counterparty),
                currency=cell(rec, columns.currency) or None,
                balance=balance,
                fields={h: (rec[i] if i < len(rec) else "") for h, i in idx.items()},
            )
        )
    return CsvResult(columns, rows, skipped)


def _amount(rec: list[str], columns: ColumnMap, cell) -> Decimal:
    if columns.amount:
        return parse_amount(cell(rec, columns.amount))
    debit, credit = cell(rec, columns.debit), cell(rec, columns.credit)
    if not debit and not credit:
        raise AmountError("row has neither debit nor credit")
    total = Decimal(0)
    if credit:
        total += abs(parse_amount(credit))
    if debit:
        total -= abs(parse_amount(debit))
    return total
