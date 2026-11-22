"""PDF statements: rows, receipts, audit and reconcile."""

import json
from decimal import Decimal

from pdfgen import make_pdf
from test_pdf_text import HEADER, PAGE

from memvo.audit import audit
from memvo.cli import main
from memvo.importers.pdf_rows import read_pdf_pages
from memvo.importers.pdf_text import extract
from memvo.mcp import Server
from memvo.reconcile import reconcile
from memvo.vault import SCHEMA_VERSION, Vault


def test_rows_from_generated_pdf():
    r = read_pdf_pages(extract(make_pdf([PAGE])))
    assert r.skipped == []
    assert r.opening_balance == Decimal("4149.81")
    a, b = r.rows
    assert (a.when.isoformat(), a.amount, a.balance, a.description) == ("2026-11-05", Decimal("-17.99"), Decimal("4131.82"), "STREAMLY SUBSCRIPTION")
    assert (b.amount, b.page, b.first_line, b.last_line) == (Decimal("2500.00"), 1, 5, 6)
    assert b.raw == "06/11/2026   SALARY ACME (PT)   2,500.00   6,631.82\nREF 7781"
    assert b.description == "SALARY ACME (PT) REF 7781"


def test_markers_signs_and_inferred_signs():
    page = [
        (40, 800, "Period 01/12/2026 - 31/12/2026"),
        (60, 780, "SALDO AWAL"), (400, 780, "1,000.00"),
        (40, 760, "02/12"), (100, 760, "WARUNG"), (300, 760, "50.00 DB"), (400, 760, "950.00"),
        (40, 745, "03/12"), (100, 745, "GAJI"), (300, 745, "500.00"), (330, 745, "CR"), (400, 745, "1,450.00"),
        (40, 730, "04/12"), (100, 730, "TOKO"), (300, 730, "25.00"), (400, 730, "1,425.00"),
        (40, 715, "05/12"), (100, 715, "BUNGA"), (300, 715, "1.25"), (400, 715, "1,426.25"),
        (40, 700, "06/12"), (100, 700, "REFUND (12.00)"), (300, 700, "(12.00)"),
        (60, 685, "SALDO AKHIR"), (400, 685, "1,426.25"),
    ]
    r = read_pdf_pages(extract(make_pdf([page])))
    assert [str(x.amount) for x in r.rows] == ["-50.00", "500.00", "-25.00", "1.25", "-12.00"]
    assert r.opening_balance == Decimal("1000.00") and r.ledger_balance == Decimal("1426.25")
    assert r.rows[0].when.isoformat() == "2026-12-02"


def test_short_dates_cross_the_new_year():
    page = [
        (40, 800, "Statement date 05 Jan 2027"),
        (40, 760, "30 Dec"), (100, 760, "HOTEL"), (300, 760, "-210.00"),
        (40, 745, "02 Jan"), (100, 745, "TAXI"), (300, 745, "-18.40"),
    ]
    r = read_pdf_pages(extract(make_pdf([page])))
    assert [x.when.isoformat() for x in r.rows] == ["2026-12-30", "2027-01-02"]


def test_unreadable_rows_are_listed_not_guessed():
    page = [
        (40, 745, "2026-11-02"), (100, 745, "AMOUNT ON NEXT LINE"),
        (40, 730, "2026-11-03"), (100, 730, "THREE"), (250, 730, "1.00"), (300, 730, "2.00"), (350, 730, "3.00"),
    ]
    r = read_pdf_pages(extract(make_pdf([page])))
    assert r.rows == []
    assert r.skipped == [
        ("page 1 line 1", "starts with a date but has no amount"),
        ("page 1 line 2", "3 amounts and no column header to tell them apart"),
    ]
    no_year = read_pdf_pages(extract(make_pdf([[(40, 760, "01/11"), (100, 760, "SHOP"), (300, 760, "-5.00")]])))
    assert no_year.rows == [] and "has no year" in no_year.skipped[0][1]


def test_two_amounts_in_one_column_is_skipped():
    page = [*HEADER, (40, 730, "05/11/2026"), (100, 730, "X"), (320, 730, "1.00"), (340, 730, "2.00")]
    r = read_pdf_pages(extract(make_pdf([page])))
    assert r.skipped == [("page 1 line 2", "two amounts under one column")]


def test_chrome_statement_end_to_end(tmp_path, files):
    pdf = files / "pdf" / "statement-chrome.pdf"
    with Vault.init(tmp_path / "v.db") as v:
        rep = v.import_file(pdf, "checking")
        assert (rep.format, rep.added, rep.skipped) == ("pdf", 11, [])
        assert (rep.statement_opening, rep.statement_balance, rep.statement_as_of) == ("4,150.00", "5,610.25", "2026-11-28")
        assert v.import_file(pdf, "checking").added == 0

        rent = v.search("rent")[0]
        receipt = rent.receipt()
        assert (receipt["page"], receipt["lines"]) == (1, "10-11")
        assert receipt["raw"] == "07 Nov 2026   RENT NOVEMBER   1,450.00   2,674.83\nSTANDING ORDER 0042"
        assert rent.amount == -14_500_000
        assert v.search("booknook")[0].receipt()["page"] == 2

        chain = reconcile(v, "checking")
        assert chain.chains[0].breaks == [] and chain.chains[0].rows_checked == 11
        stated = reconcile(v, "checking", opening=41_500_000, use_statement=True)
        assert stated.difference == "0.00"
        assert audit(v).ok

    data = bytearray(pdf.read_bytes())
    data[-40] ^= 1
    pdf.write_bytes(bytes(data))
    with Vault(tmp_path / "v.db") as v:
        assert audit(v).sources[0].status == "changed"


def test_quartz_statement_markers(tmp_path, files):
    with Vault.init(tmp_path / "v.db") as v:
        rep = v.import_file(files / "pdf" / "statement-quartz.pdf", "tabungan")
        assert rep.added == 5 and rep.skipped == []
        amounts = [e.amount_text for e in v.entries("tabungan")]
        assert amounts == ["-45.10", "2,800.00", "-39.99", "-12.30", "-2.50"]
        assert reconcile(v, "tabungan").chains[0].breaks == []
        cafe = v.search("cafe")[0]
        assert cafe.description == "CAFE LUNA CARD 4421" and cafe.receipt()["lines"] == "8-9"


def test_audit_catches_a_stored_row_edited_in_the_vault(tmp_path, files):
    with Vault.init(tmp_path / "v.db") as v:
        v.import_file(files / "pdf" / "statement-chrome.pdf", "checking")
        v.db.execute("UPDATE entries SET raw = replace(raw, '42.18', '24.18')")
        v.db.commit()
        rep = audit(v)
    assert not rep.ok and len(rep.sources[0].mismatched) == 1


def test_cli_and_mcp_show_the_page(tmp_path, files, capsys):
    db = str(tmp_path / "v.db")
    main(["init", "--vault", db])
    assert main(["import", "--vault", db, str(files / "pdf" / "statement-chrome.pdf"), "--account", "checking"]) == 0
    out = capsys.readouterr().out
    assert "11 entries added from statement-chrome.pdf (pdf)" in out
    assert "opening balance 4,150.00 (pass --opening 4,150.00 to reconcile)" in out
    main(["search", "--vault", db, "interest"])
    out = capsys.readouterr().out
    assert "statement-chrome.pdf:p2:7" in out
    entry = out.split()[4]
    main(["show", "--vault", db, entry])
    assert "(page 2, line 7)" in capsys.readouterr().out
    assert main(["reconcile", "--vault", db, "--account", "checking", "--expect", "statement", "--opening", "4150"]) == 0

    res = Server(db).call_tool("memvo_get_entry", {"id": entry})
    assert json.loads(res["content"][0]["text"])["receipt"]["page"] == 2


def test_cli_reports_unreadable_pdf(tmp_path, capsys):
    db = str(tmp_path / "v.db")
    main(["init", "--vault", db])
    bad = tmp_path / "locked.pdf"
    bad.write_bytes(make_pdf([PAGE], encrypt=True))
    assert main(["import", "--vault", db, str(bad), "--account", "x"]) == 1
    assert "encrypted" in capsys.readouterr().err


def test_migrates_v2_vault(tmp_path, files):
    path = tmp_path / "old.db"
    with Vault.init(path) as v:
        v.import_file(files / "checking.csv", "checking")
        v.db.execute("ALTER TABLE entries DROP COLUMN page")
        v.db.execute("UPDATE meta SET value='2' WHERE key='schema'")
        v.db.commit()
    with Vault(path) as v:
        assert v.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(SCHEMA_VERSION)
        assert v.import_file(files / "pdf" / "statement-chrome.pdf", "checking").added == 11
        assert audit(v).ok


def test_a_page_without_text_is_listed():
    r = read_pdf_pages(extract(make_pdf([PAGE, []])))
    assert len(r.rows) == 2 and ("page 2", "no text on this page (scanned image?)") in r.skipped
