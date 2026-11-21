"""Hostile and malformed statement files.

Bank exports are untrusted input. Whatever is in them, the readers either
return rows plus a list of skipped lines, or raise ValueError with a message
the CLI can show. They never crash with anything else.
"""

import random
import socket

import pytest

from memvo.importers.csv_rows import read_csv
from memvo.importers.ofx_rows import read_ofx

ODD_VALUES = [
    "2026-13-45", "2026-02-30", "0000-00-00", "31/12/2026", "12/31/26", "9999999-1-1",
    "1.234,56", "(12.00)", "--5", "$5", "-", "", "1e9999", "NaN", "Infinity",
    "99999999999999999999", "٣٤", "１２", "\x00", "é", '"a,b"', "1,2,3",
]

PIECES = ODD_VALUES + [
    "date", "amount", "debit", "credit", "balance", "description",
    ",", ";", "\t", "\n", "\r\n", '"', "<STMTTRN>", "</STMTTRN>", "<DTPOSTED>", "<TRNAMT>",
]


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 40)))


@pytest.mark.parametrize("seed", range(8))
def test_random_text_never_crashes_the_readers(seed):
    rng = random.Random(seed)
    for _ in range(500):
        text = _random_text(rng)
        for reader in (read_csv, read_ofx):
            try:
                reader(text)
            except ValueError:
                pass  # a clear "no date column" style message is fine


@pytest.mark.parametrize("seed", range(8))
def test_bad_cells_are_skipped_not_imported(seed):
    rng = random.Random(1000 + seed)
    for _ in range(300):
        lines = ["date,amount,balance,description"]
        values = [v for v in ODD_VALUES if v != "\x00"]
        lines += [",".join(rng.choice(values) for _ in range(4)) for _ in range(rng.randint(1, 5))]
        result = read_csv("\n".join(lines))
        assert len(result.rows) + len(result.skipped) <= len(lines) - 1
        for row in result.rows:
            assert row.amount.is_finite()


@pytest.mark.parametrize("seed", range(8))
def test_bad_ofx_blocks_are_skipped(seed):
    rng = random.Random(2000 + seed)
    for _ in range(300):
        posted, amount, bal, asof = (rng.choice(ODD_VALUES) for _ in range(4))
        text = (
            f"<OFX><STMTTRN><DTPOSTED>{posted}<TRNAMT>{amount}</STMTTRN>"
            f"<LEDGERBAL><BALAMT>{bal}<DTASOF>{asof}</LEDGERBAL>"
        )
        result = read_ofx(text)
        assert len(result.rows) + len(result.skipped) == 1
        for row in result.rows:
            assert row.amount.is_finite()


def test_huge_file_is_read_in_one_pass():
    body = "\n".join(f"2026-11-{(i % 28) + 1:02d},-{i}.25,,row {i}" for i in range(20000))
    result = read_csv("date,amount,balance,description\n" + body)
    assert len(result.rows) == 20000
    assert result.rows[-1].first_line == 20001


def test_network_is_blocked_during_tests():
    with pytest.raises(AssertionError):
        socket.create_connection(("example.com", 443))


def test_nul_bytes_are_rejected_with_the_line():
    with pytest.raises(ValueError, match="NUL byte on line 2"):
        read_csv("date,amount\n2026-11-01,-5.00\x00\n")


def test_csv_module_errors_become_value_errors(monkeypatch):
    import csv

    def broken_reader(*args, **kwargs):
        raise csv.Error("line contains NUL")

    monkeypatch.setattr("memvo.importers.csv_rows.csv.reader", broken_reader)
    with pytest.raises(ValueError, match="not a readable CSV file"):
        read_csv("date,amount\n2026-11-01,-5.00\n")
