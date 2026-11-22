"""`memvo demo`: a guided run on made-up statements.

Everything happens in a throwaway folder with its own vault, so the user's
real vault is never opened. The last step edits one line of the sample file
to show what `audit` reports when a source changes after import.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Callable

SAMPLES = ("checking.csv", "card.qfx")


def _say(text: str) -> None:
    print(f"\n# {text}")


def run(main: Callable[[list[str]], int], keep: str | None = None) -> int:
    base = Path(keep).expanduser().resolve() if keep else Path(tempfile.mkdtemp(prefix="memvo-demo-"))
    base.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()
    os.chdir(base)  # so the commands below can use short file names
    try:
        return _walkthrough(main, base)
    finally:
        os.chdir(cwd)
        if keep:
            print(f"\nDemo files kept in {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)


def _walkthrough(main: Callable[[list[str]], int], base: Path) -> int:
    for name in SAMPLES:
        (base / name).write_bytes(files("memvo.demo_data").joinpath(name).read_bytes())
    vault = "vault.db"
    checking = base / "checking.csv"

    def memvo(*argv: str) -> int:
        shown = " ".join(a if " " not in a else repr(a) for a in argv)
        print(f"$ memvo {shown}")
        return main([argv[0], "--vault", vault, *argv[1:]])

    print("Memvo demo on made-up statements in", base)
    print("Your own vault is not opened.")

    _say("Import a bank CSV and a card QFX. Rows are stored verbatim.")
    memvo("init")
    memvo("import", "checking.csv", "--account", "checking")
    memvo("import", "card.qfx", "--account", "card", "--kind", "card")

    _say("Ask a question. Every hit points at a file and a line.")
    memvo("search", "streamly")

    _say("Open one entry to see its receipt.")
    from .vault import Vault

    with Vault(vault) as v:
        entry = v.search("streamly", limit=1)[0]
    memvo("show", entry.id)

    _say("Check the balances against what the statements say.")
    memvo("reconcile", "--account", "checking", "--expect", "4131.82")
    memvo("reconcile", "--account", "card", "--expect", "statement")

    _say("Someone edits the CSV after import: rent 1450.00 becomes 1405.00.")
    checking.write_text(checking.read_text().replace("-1450.00", "-1405.00"))
    code = memvo("audit")

    print("\nThat is the whole idea: answers come from stored rows, and any row can be")
    print("checked against the file it came from. Next: `memvo init`, then import your own files.")
    return 0 if code == 2 else 1
