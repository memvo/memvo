import json
from datetime import date
from decimal import Decimal

import pytest

from memvo.audit import audit
from memvo.cli import main
from memvo.importers.ofx_rows import looks_like_ofx, read_ofx
from memvo.mcp import Server
from memvo.reconcile import reconcile
from memvo.vault import SCHEMA_VERSION, Vault


def test_sgml_ofx(files):
    text = (files / "checking-nov.ofx").read_bytes().decode()
    assert looks_like_ofx(text)
    res = read_ofx(text)
    assert [r.amount for r in res.rows] == [Decimal("-42.10"), Decimal("3200.00"), Decimal("-17.99")]
    first = res.rows[0]
    assert first.when == date(2026, 11, 3) and first.ref == "2026110301"
    assert first.description == "NORTHWIND GROCERY #14 · POS PURCHASE"
    assert first.raw.startswith("<STMTTRN>") and first.raw.endswith("</STMTTRN>")
    assert (first.first_line, first.last_line) == (17, 24)
    assert res.rows[2].description == "STREAMLY · SUBSCRIPTION & TAX"
    assert res.currency == "USD" and first.currency == "USD"
    assert res.ledger_balance == Decimal("7271.73") and res.ledger_as_of == date(2026, 11, 20)


def test_xml_qfx_skips_bad_row(files):
    res = read_ofx((files / "card.qfx").read_text())
    assert [r.ref for r in res.rows] == ["A1", "A3"]
    assert res.rows[0].first_line == res.rows[0].last_line
    assert res.skipped and "OFX date" in res.skipped[0][1]
    assert res.rows[1].description == "REFUND · Order 1182"
    assert res.ledger_balance == Decimal("-312.40") and res.currency == "EUR"


def test_ofx_without_name_or_ledger():
    text = "<OFX><STMTTRN><TRNTYPE>FEE<DTPOSTED>20260101<TRNAMT>-1</STMTTRN>" \
           "<LEDGERBAL><BALAMT>oops<DTASOF>20260101</LEDGERBAL></OFX>"
    res = read_ofx(text)
    assert res.rows[0].description == "FEE" and res.rows[0].currency is None
    assert res.ledger_balance is None and res.ledger_as_of is None
    assert not looks_like_ofx("Date,Amount\n")


def test_vault_imports_ofx_and_reconciles_with_statement(vault, files):
    vault.import_file(files / "checking.csv", "checking")
    rep = vault.import_file(files / "checking-nov.ofx", "checking")
    assert rep.format == "ofx" and rep.added == 3 and rep.columns == {}
    assert rep.statement_balance == "7,271.73" and rep.statement_as_of == "2026-11-20"
    again = vault.import_file(files / "checking-nov.ofx", "checking")
    assert again.already_present == 3 and again.statement_balance == "7,271.73"

    hit = vault.search("northwind", period="2026-11")[0]
    receipt = hit.receipt()
    assert receipt["bank_ref"] == "2026110301" and receipt["lines"] == "17-24"
    assert audit(vault).ok

    rc = reconcile(vault, "checking", use_statement=True)
    assert rc.ok and rc.difference == "0.00" and rc.expected_from == "statement" and rc.as_of == "2026-11-20"
    with pytest.raises(ValueError, match="states a balance"):
        reconcile(vault, "nobody", use_statement=True)


def test_overlapping_ofx_downloads_match_on_fitid(vault, files, tmp_path):
    vault.import_file(files / "card.qfx", "card")
    later = tmp_path / "later.qfx"
    later.write_text(
        "<OFX><STMTTRN><DTPOSTED>20261102<TRNAMT>-9.50<FITID>A1<NAME>Cafe Lumen (pending)</STMTTRN>"
        "<STMTTRN><DTPOSTED>20261102<TRNAMT>-9.50<FITID>A9<NAME>CAFE LUMEN</STMTTRN></OFX>\n"
    )
    vault.import_file(later, "card")
    dupes = audit(vault).duplicates
    assert len(dupes) == 1 and len(dupes[0]) == 2
    assert audit(vault).ok


def test_cp1252_file(vault, tmp_path):
    f = tmp_path / "old.csv"
    f.write_bytes("Date,Description,Amount\n2026-01-02,Caf\xe9 Ren\xe9,-3.50\n".encode("cp1252"))
    vault.import_file(f, "cash")
    assert vault.search("café")[0].description == "Café René"
    assert audit(vault).ok


def test_migrates_v1_vault(tmp_path, files):
    path = tmp_path / "old.db"
    with Vault.init(path) as v:
        v.import_file(files / "checking.csv", "checking")
        for stmt in ("ALTER TABLE sources DROP COLUMN stated_balance",
                     "ALTER TABLE sources DROP COLUMN stated_as_of",
                     "ALTER TABLE entries DROP COLUMN ref",
                     "ALTER TABLE entries DROP COLUMN page"):
            v.db.execute(stmt)
        v.db.execute("UPDATE meta SET value='1' WHERE key='schema'")
        v.db.commit()
    with Vault(path) as v:
        assert v.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(SCHEMA_VERSION)
        assert v.stats()["entries"] == 6
        v.import_file(files / "checking-nov.ofx", "checking")
        assert v.statement_balance("checking") == (72_717_300, "2026-11-20")


def test_cli_and_mcp_statement_reconcile(tmp_path, files, capsys):
    db = str(tmp_path / "v.db")
    main(["init", "--vault", db])
    main(["import", "--vault", db, str(files / "checking.csv"), "--account", "checking"])
    main(["import", "--vault", db, str(files / "checking-nov.ofx"), "--account", "checking"])
    out = capsys.readouterr().out
    assert "(ofx)" in out and "statement balance 7,271.73 as of 2026-11-20" in out
    assert main(["reconcile", "--vault", db, "--account", "checking", "--expect", "statement"]) == 0
    assert "statement says 7,271.73" in capsys.readouterr().out
    assert main(["reconcile", "--vault", db, "--account", "none", "--expect", "statement"]) == 1

    server = Server(db)
    res = server.call_tool("memvo_reconcile", {"account": "checking", "expected": "statement"})
    assert json.loads(res["content"][0]["text"])["expected_from"] == "statement"
    bad = server.call_tool("memvo_reconcile", {"account": "none", "expected": "statement"})
    assert bad["isError"]
