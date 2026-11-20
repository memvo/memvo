"""Amount parsing.

Exports disagree on separators: "1,234.56", "1.234,56", "1 234,56", "(12.50)",
"-12.50", "12.50-", "IDR 1.500.000". Amounts are kept as Decimal and stored as
integers scaled by SCALE so that sums are exact.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

SCALE = 10_000

_CURRENCY = re.compile(r"[A-Za-z$€£¥₹₩₫₱฿]+")


class AmountError(ValueError):
    pass


def parse_amount(text: str) -> Decimal:
    raw = text
    s = text.strip().replace(" ", " ").replace("−", "-")
    if not s:
        raise AmountError("empty amount")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.endswith("-"):
        negative, s = True, s[:-1].strip()
    if s.startswith("-"):
        negative, s = not negative, s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    s = _CURRENCY.sub("", s).strip()
    if s.startswith("-"):
        negative, s = not negative, s[1:].strip()
    s = s.replace(" ", "").replace("'", "")
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        raise AmountError(f"not an amount: {raw!r}")

    s = _normalise_separators(s)
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise AmountError(f"not an amount: {raw!r}") from exc
    return -value if negative else value


def _normalise_separators(s: str) -> str:
    if s in (".", ",") or re.search(r"[.,]{2}", s):
        raise AmountError(f"malformed number {s!r}")
    dot, comma = s.rfind("."), s.rfind(",")
    if dot >= 0 and comma >= 0:
        decimal_mark = "." if dot > comma else ","
    elif dot >= 0 or comma >= 0:
        mark = "." if dot >= 0 else ","
        parts = s.split(mark)
        # One mark followed by exactly three digits is a thousands group
        # ("1.500" in an IDR export), unless the integer part is 0 ("0.500").
        if len(parts) > 2 or (len(parts[-1]) == 3 and parts[0] not in ("", "0")):
            return s.replace(mark, "")
        decimal_mark = mark
    else:
        return s
    thousands = "," if decimal_mark == "." else "."
    s = s.replace(thousands, "")
    if s.count(decimal_mark) > 1:
        raise AmountError(f"ambiguous separators in {s!r}")
    return s.replace(decimal_mark, ".")


def to_scaled(value: Decimal) -> int:
    scaled = value * SCALE
    if scaled != scaled.to_integral_value():
        raise AmountError(f"{value} has more than 4 decimal places")
    return int(scaled)


def from_scaled(units: int) -> Decimal:
    return (Decimal(units) / SCALE).normalize() if units else Decimal(0)


def fmt(units: int) -> str:
    value = Decimal(units) / SCALE
    return f"{value:,.2f}" if value == value.quantize(Decimal("0.01")) else f"{value.normalize():,}"
