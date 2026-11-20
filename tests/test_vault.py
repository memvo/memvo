from pathlib import Path

import pytest

from memvo.audit import audit
from memvo.reconcile import reconcile
from memvo.vault import Vault, VaultError, entry_id, sha256_text


def test_import_is_idempotent(vault, files):
    r1 = vault.import_csv(files / "checking.csv", "checking")
    assert r1.added == 6
    r2 = vault.import_csv(files / "checking.csv", "checking")
    assert r2.added == 0 and r2.already_present == 6
    assert vault.stats()["entries"] == 6


def test_entry_ids_are_deterministic(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    e = vault.entries("checking")[0]
    assert e.id == entry_id(e.source_sha256, e.first_line, e.raw)
    assert e.raw_sha256 == sha256_text(e.raw)


def test_search_returns_receipts(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    hits = vault.search("streamly subscription")
    assert [h.amount_text for h in hits] == ["-17.99", "-15.99"] or {h.amount_text for h in hits} == {"-17.99", "-15.99"}
    r = hits[0].receipt()
    assert r["source"].endswith("checking.csv") and r["raw"].startswith("2026-")
    assert r["raw_sha256"] == sha256_text(r["raw"])


def test_search_prefix_filters_and_or_fallback(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    vault.import_csv(files / "tabungan.csv", "tabungan")
    assert len(vault.search("stream")) == 2
    assert [h.id for h in vault.search("streamly", period="2026-11")] == [vault.search("streamly", period="2026-11")[0].id]
    assert len(vault.search("streamly", since="2026-11-01", until="2026-11-30")) == 1
    assert vault.search("kopi", account="checking") == []
    assert len(vault.search("kopi rent")) == 2
    assert vault.search("zzzz") == []
    latest = vault.search("", limit=2)
    assert [e.day for e in latest] == ["2026-11-05", "2026-11-03"]
    assert vault.search("tokó")[0].account == "tabungan"


def test_accounts_periods_sources(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    vault.import_csv(files / "broker.csv", "broker", kind="broker")
    accts = {a["name"]: a for a in vault.accounts()}
    assert accts["checking"]["net"] == "4,131.82" and accts["broker"]["kind"] == "broker"
    oct_ = [p for p in vault.periods("checking") if p["period"] == "2026-10"][0]
    assert oct_["in"] == "5,700.00" and oct_["out"] == "-1,550.19"
    assert len(vault.periods()) == 3
    assert [s["account"] for s in vault.sources()] == ["checking", "broker"]
    assert vault.get("e_missing") is None


def test_vault_errors(tmp_path):
    with pytest.raises(VaultError, match="memvo init"):
        Vault(tmp_path / "none.db")
    with Vault.init(tmp_path / "v.db") as v:
        with pytest.raises(VaultError, match="empty"):
            v.ensure_account("  ")
        v.db.execute("UPDATE meta SET value='99' WHERE key='schema'")
        v.db.commit()
    with pytest.raises(VaultError, match="newer"):
        Vault(tmp_path / "v.db")


def test_default_path_respects_env(tmp_path, monkeypatch):
    from memvo.vault import default_vault_path

    monkeypatch.setenv("MEMVO_HOME", str(tmp_path / "h"))
    assert default_vault_path() == tmp_path / "h" / "vault.db"
    monkeypatch.delenv("MEMVO_HOME")
    assert default_vault_path().name == "vault.db"


def test_audit_ok_changed_missing_and_tampered_row(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    vault.import_csv(files / "tabungan.csv", "tabungan")
    vault.import_csv(files / "broker.csv", "broker")
    assert audit(vault).ok

    vault.db.execute("UPDATE entries SET raw = raw || 'x' WHERE first_line = 2 AND account = 'broker'")
    rep = audit(vault)
    assert not rep.ok and [s.mismatched for s in rep.sources if s.mismatched]

    (files / "checking.csv").write_text("changed\n")
    (files / "tabungan.csv").unlink()
    statuses = {Path(s.path).name: s.status for s in audit(vault).sources}
    assert statuses == {"checking.csv": "changed", "tabungan.csv": "missing", "broker.csv": "ok"}
    assert audit(vault).as_dict()["ok"] is False


def test_audit_flags_overlapping_exports(vault, files, tmp_path):
    vault.import_csv(files / "checking.csv", "checking")
    overlap = tmp_path / "november.csv"
    overlap.write_text('Date,Description,Amount\n2026-11-05,"Streamly subscription monthly",-17.99\n')
    vault.import_csv(overlap, "checking")
    assert len(audit(vault).duplicates) == 1


def test_reconcile_running_balance_newest_and_oldest_first(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    vault.import_csv(files / "tabungan.csv", "tabungan")
    rc = reconcile(vault, "checking")
    assert rc.ok and rc.chains[0].order == "oldest-first"
    rt = reconcile(vault, "tabungan")
    assert rt.ok and rt.chains[0].order == "newest-first"


def test_reconcile_finds_missing_row(vault, files):
    vault.import_csv(files / "broken.csv", "cash")
    rep = reconcile(vault, "cash")
    assert not rep.ok
    (b,) = rep.chains[0].breaks
    assert b.day == "2026-10-04" and b.expected == "83.00" and b.stated == "80.00" and b.diff == "-3.00"


def test_reconcile_expected_balance(vault, files):
    from decimal import Decimal

    from memvo.money import to_scaled

    vault.import_csv(files / "checking.csv", "checking")
    good = reconcile(vault, "checking", expected=to_scaled(Decimal("4131.82")))
    assert good.ok and good.difference == "0.00"
    asof = reconcile(vault, "checking", expected=to_scaled(Decimal("4149.81")), as_of="2026-10-31")
    assert asof.ok
    off = reconcile(vault, "checking", expected=to_scaled(Decimal("4200")), opening=to_scaled(Decimal("50")))
    assert not off.ok and off.difference == "18.18"
    assert off.as_dict()["difference"] == "18.18"
