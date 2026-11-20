import json

import pytest

from memvo.cli import main


@pytest.fixture
def run(tmp_path, capsys):
    db = str(tmp_path / "v.db")

    def _run(*argv):
        code = main([*argv[:1], "--vault", db, *argv[1:]])
        out = capsys.readouterr()
        return code, out.out, out.err

    return _run


def test_full_flow(run, files):
    assert run("init")[1].startswith("Vault created")
    assert run("init")[1].startswith("Vault already")
    code, out, _ = run("import", str(files / "checking.csv"), "--account", "checking")
    assert code == 0 and "6 entries added" in out and "amount=Amount" in out
    assert "already imported" in run("import", str(files / "checking.csv"), "--account", "checking")[1]

    code, out, _ = run("search", "rent")
    assert code == 0 and "-1,450.00" in out and "checking.csv:6" in out
    code, out, _ = run("search", "rent", "--json")
    hit = json.loads(out)[0]
    assert hit["receipt"]["lines"] == "6"

    code, out, _ = run("show", hit["id"])
    assert "RENT OCTOBER" in out and "sha256" in out
    assert run("show", "e_nope")[0] == 1
    assert run("search", "nothingmatches")[0] == 1

    assert "checking" in run("accounts")[1]
    assert "2026-11" in run("periods", "--account", "checking")[1]
    assert run("audit")[0] == 0
    code, out, _ = run("reconcile", "--account", "checking", "--expect", "4,131.82")
    assert code == 0 and "unbroken" in out and "difference 0.00" in out
    assert json.loads(run("stats", "--json")[1])["entries"] == 6


def test_problems_exit_nonzero(run, files):
    run("init")
    run("import", str(files / "broken.csv"), "--account", "cash")
    code, out, _ = run("reconcile", "--account", "cash")
    assert code == 2 and "off by -3.00" in out
    (files / "broken.csv").write_text("x\n")
    code, out, _ = run("audit")
    assert code == 2 and "CHANGED" in out


def test_skips_map_and_errors(run, files, tmp_path):
    run("init")
    weird = tmp_path / "w.csv"
    weird.write_text("When,Betrag\n2026-01-01,5\nbad,1\n")
    code, out, _ = run("import", str(weird), "--account", "x", "--map", "date=When", "--map", "amount=Betrag")
    assert code == 0 and "1 rows skipped" in out
    with pytest.raises(SystemExit):
        run("import", str(weird), "--account", "x", "--map", "oops")
    code, _, err = run("import", str(tmp_path / "missing.csv"), "--account", "x")
    assert code == 1 and "memvo:" in err
    with pytest.raises(SystemExit):
        run("reconcile", "--account", "x", "--expect", "abc")


def test_empty_vault_messages(run):
    run("init")
    assert "No accounts yet" in run("accounts")[1]
    assert "No entries yet" in run("periods")[1]
    assert "Nothing to check" in run("reconcile", "--account", "none")[1]


def test_no_vault(tmp_path, capsys):
    assert main(["stats", "--vault", str(tmp_path / "nope.db")]) == 1
    assert "memvo init" in capsys.readouterr().err
