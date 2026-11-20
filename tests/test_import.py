from datetime import date
from decimal import Decimal

import pytest

from memvo.importers.csv_rows import ColumnMap, read_csv


def test_reads_rows_with_verbatim_raw(files):
    text = (files / "checking.csv").read_text()
    res = read_csv(text)
    assert res.columns.date == "Date" and res.columns.amount == "Amount" and res.columns.balance == "Balance"
    assert len(res.rows) == 6 and not res.skipped
    sub = res.rows[2]
    assert sub.raw == '2026-10-05,"STREAMLY SUBSCRIPTION, MONTHLY",-15.99,2399.81'
    assert sub.first_line == sub.last_line == 4
    assert sub.amount == Decimal("-15.99")
    assert sub.balance == Decimal("2399.81")


def test_semicolon_debit_credit_day_first(files):
    res = read_csv((files / "tabungan.csv").read_text())
    assert [r.amount for r in res.rows] == [Decimal("-45000.00"), Decimal("2000000.00")]
    assert res.rows[0].when == date(2026, 11, 3)
    assert res.rows[0].description == "TRSF E-BANKING KE TOKO KOPI"


def test_multiline_record_keeps_line_range(files):
    res = read_csv((files / "broker.csv").read_text())
    buy = res.rows[0]
    assert (buy.first_line, buy.last_line) == (2, 3)
    assert buy.raw.endswith('limit order filled in two parts"')
    assert buy.when == date(2026, 11, 18)
    assert buy.currency == "USD"
    assert res.rows[1].first_line == 4


def test_bad_rows_are_skipped_with_reason():
    res = read_csv("date,amount\n2026-01-01,5\nnot-a-date,5\n2026-01-03,abc\n2026-01-04,\n")
    assert len(res.rows) == 1
    assert [n for n, _ in res.skipped] == [3, 4, 5]


def test_bom_blank_lines_and_empty_file():
    res = read_csv("﻿date,amount\n\n2026-01-01,5\n")
    assert len(res.rows) == 1 and res.rows[0].first_line == 3
    assert read_csv("").rows == []


def test_overrides_and_detection_errors():
    cols = ColumnMap.detect(["When", "Betrag", "Text"], {"date": "When", "amount": "Betrag"})
    assert cols.date == "When" and cols.amount == "Betrag"
    with pytest.raises(ValueError, match="no date column"):
        ColumnMap.detect(["Betrag"])
    with pytest.raises(ValueError, match="no amount"):
        ColumnMap.detect(["Date", "Text"])
    with pytest.raises(ValueError, match="unknown column role"):
        ColumnMap.detect(["Date", "Amount"], {"colour": "Date"})
    with pytest.raises(ValueError, match="not in header"):
        ColumnMap.detect(["Date", "Amount"], {"amount": "Nope"})


def test_debit_only_and_missing_both():
    res = read_csv("date,debit,credit\n2026-01-01,10,\n2026-01-02,,\n")
    assert res.rows[0].amount == Decimal("-10")
    assert res.skipped and "neither" in res.skipped[0][1]


def test_short_row_is_tolerated():
    res = read_csv("date,amount,memo\n2026-01-01,5\n")
    assert res.rows[0].description == ""
