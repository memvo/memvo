"""Date parsing for statement exports.

Slash dates are ambiguous (03/04/2026). The importer looks at every date in a
file before choosing day-first or month-first, so one file is never parsed
two different ways.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january", "januari"),
            ("feb", "february", "februari"),
            ("mar", "march", "maret"),
            ("apr", "april"),
            ("may", "mei"),
            ("jun", "june", "juni"),
            ("jul", "july", "juli"),
            ("aug", "august", "agu", "agustus"),
            ("sep", "sept", "september"),
            ("oct", "october", "okt", "oktober"),
            ("nov", "november", "nop", "nopember"),
            ("dec", "december", "des", "desember"),
        ],
        start=1,
    )
    for m in names
}

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
_SLASH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?:\s.*)?$")
_YMD_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})(?:\s.*)?$")
_NAMED = re.compile(r"^(\d{1,2})[\s\-]+([A-Za-z]+)\.?[\s\-,]+(\d{2,4})$")
_NAMED_US = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")


class DateError(ValueError):
    pass


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if len(y) == 2 else n


def slash_order(samples: list[str]) -> str:
    """Return "dmy" or "mdy" for a column of slash dates."""
    for s in samples:
        m = _SLASH.match(s.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            return "dmy"
        if b > 12 >= a:
            return "mdy"
    return "dmy"


def parse_date(text: str, order: str = "dmy") -> date:
    s = text.strip()
    try:
        if m := _ISO.match(s):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _YMD_SLASH.match(s):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := _SLASH.match(s):
            a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            return date(y, b, a) if order == "dmy" else date(y, a, b)
        if m := _NAMED.match(s):
            month = _MONTHS.get(m.group(2).lower())
            if month:
                return date(_year(m.group(3)), month, int(m.group(1)))
        if m := _NAMED_US.match(s):
            month = _MONTHS.get(m.group(1).lower())
            if month:
                return date(int(m.group(3)), month, int(m.group(2)))
        if s.isdigit() and len(s) in (10, 13):
            ts = int(s) / (1000 if len(s) == 13 else 1)
            return datetime.fromtimestamp(ts, timezone.utc).date()
    except ValueError as exc:
        raise DateError(f"not a date: {text!r}") from exc
    raise DateError(f"not a date: {text!r}")
