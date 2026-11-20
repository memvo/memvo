from datetime import date
from decimal import Decimal

import pytest

from memvo.dates import DateError, parse_date, slash_order
from memvo.money import AmountError, fmt, from_scaled, parse_amount, to_scaled


@pytest.mark.parametrize(
    "text,want",
    [
        ("12.50", "12.50"),
        ("-12.50", "-12.50"),
        ("+12.50", "12.50"),
        ("(12.50)", "-12.50"),
        ("12.50-", "-12.50"),
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1.500.000", "1500000"),
        ("1.500", "1500"),
        ("0.500", "0.500"),
        ("12,5", "12.5"),
        ("$1,000", "1000"),
        ("IDR 2.000.000,00", "2000000.00"),
        ("USD -3.12", "-3.12"),
        ("−5.00", "-5.00"),
        ("1'234.50", "1234.50"),
        ("7", "7"),
    ],
)
def test_parse_amount(text, want):
    assert parse_amount(text) == Decimal(want)


@pytest.mark.parametrize("text", ["", "  ", "abc", "1.2.3,4,5", "12..5x", "-"])
def test_parse_amount_rejects(text):
    with pytest.raises(AmountError):
        parse_amount(text)


def test_scaled_roundtrip():
    assert to_scaled(Decimal("1234.5678")) == 12_345_678
    assert from_scaled(12_345_678) == Decimal("1234.5678")
    assert from_scaled(0) == 0
    with pytest.raises(AmountError):
        to_scaled(Decimal("0.00001"))


def test_fmt():
    assert fmt(to_scaled(Decimal("-1450"))) == "-1,450.00"
    assert fmt(to_scaled(Decimal("0.0005"))) == "0.0005"


@pytest.mark.parametrize(
    "text,order,want",
    [
        ("2026-11-03", "dmy", date(2026, 11, 3)),
        ("2026-11-03T10:00:00Z", "dmy", date(2026, 11, 3)),
        ("2026/11/03", "dmy", date(2026, 11, 3)),
        ("03/11/2026", "dmy", date(2026, 11, 3)),
        ("03/11/2026", "mdy", date(2026, 3, 11)),
        ("3-11-26", "dmy", date(2026, 11, 3)),
        ("21 Nov 2026", "dmy", date(2026, 11, 21)),
        ("21-Agustus-2026", "dmy", date(2026, 8, 21)),
        ("Nov 21, 2026", "dmy", date(2026, 11, 21)),
        ("1763683200", "dmy", date(2025, 11, 21)),
        ("1763683200000", "dmy", date(2025, 11, 21)),
    ],
)
def test_parse_date(text, order, want):
    assert parse_date(text, order) == want


@pytest.mark.parametrize("text", ["", "yesterday", "32/01/2026", "21 Foo 2026", "Foo 21, 2026"])
def test_parse_date_rejects(text):
    with pytest.raises(DateError):
        parse_date(text)


def test_slash_order():
    assert slash_order(["01/02/2026", "25/02/2026"]) == "dmy"
    assert slash_order(["02/25/2026"]) == "mdy"
    assert slash_order(["01/02/2026", "not a date"]) == "dmy"
