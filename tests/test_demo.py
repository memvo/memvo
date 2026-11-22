from pathlib import Path

from memvo.cli import main


def test_demo_runs_and_cleans_up(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("MEMVO_HOME", str(tmp_path / "real-home"))
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "$ memvo search streamly" in out
    assert "checking.csv:7" in out
    assert "difference 0.00" in out
    assert "[CHANGED] checking.csv" in out
    # the user's own vault was never created
    assert not (tmp_path / "real-home").exists()
    folder = Path(out.split("statements in ", 1)[1].splitlines()[0])
    assert not folder.exists()


def test_demo_keep(capsys, tmp_path):
    keep = tmp_path / "kept"
    assert main(["demo", "--keep", str(keep)]) == 0
    assert (keep / "vault.db").exists()
    assert (keep / "card.qfx").exists()
    assert "Demo files kept in" in capsys.readouterr().out
