"""The vault: one SQLite file holding sources, accounts and entries.

Layout mirrors how people already think about money:
  vault -> accounts -> periods (YYYY-MM) -> entries
Every entry keeps the verbatim source text and the hash of the file it came
from. Nothing is summarised or rewritten on the way in.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .importers.csv_rows import read_csv
from .money import fmt, to_scaled

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'bank',
    currency TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    account TEXT NOT NULL REFERENCES accounts(name),
    format TEXT NOT NULL,
    rows INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (sha256, account)
);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    account TEXT NOT NULL REFERENCES accounts(name),
    first_line INTEGER NOT NULL,
    last_line INTEGER NOT NULL,
    raw TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    day TEXT NOT NULL,
    period TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT,
    description TEXT NOT NULL,
    counterparty TEXT NOT NULL,
    balance INTEGER,
    fingerprint TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_account_day ON entries(account, day);
CREATE INDEX IF NOT EXISTS entries_fingerprint ON entries(fingerprint);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    raw, description, counterparty, content='entries', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, raw, description, counterparty)
    VALUES (new.rowid, new.raw, new.description, new.counterparty);
END;
"""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def entry_id(source_sha: str, first_line: int, raw: str) -> str:
    return "e_" + sha256_text(f"{source_sha}:{first_line}:{raw}")[:16]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def fingerprint(account: str, day: str, amount: int, description: str) -> str:
    return sha256_text(f"{account}|{day}|{amount}|{_norm(description)}")[:20]


def default_vault_path() -> Path:
    home = os.environ.get("MEMVO_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".memvo"
    return base / "vault.db"


@dataclass(frozen=True)
class ImportReport:
    source_id: int
    path: str
    sha256: str
    account: str
    added: int
    already_present: int
    skipped: list[tuple[int, str]]
    columns: dict[str, str | None]


@dataclass(frozen=True)
class Entry:
    id: str
    account: str
    day: str
    amount: int
    currency: str | None
    description: str
    counterparty: str
    balance: int | None
    raw: str
    raw_sha256: str
    source_path: str
    source_sha256: str
    first_line: int
    last_line: int

    @property
    def amount_text(self) -> str:
        return fmt(self.amount)

    def receipt(self) -> dict:
        lines = f"{self.first_line}" if self.first_line == self.last_line else f"{self.first_line}-{self.last_line}"
        return {
            "entry": self.id,
            "source": self.source_path,
            "lines": lines,
            "source_sha256": self.source_sha256,
            "raw_sha256": self.raw_sha256,
            "raw": self.raw,
        }

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "account": self.account,
            "date": self.day,
            "amount": self.amount_text,
            "currency": self.currency,
            "description": self.description,
            "counterparty": self.counterparty,
            "balance": fmt(self.balance) if self.balance is not None else None,
            "receipt": self.receipt(),
        }


_ENTRY_COLS = (
    "e.id, e.account, e.day, e.amount, e.currency, e.description, e.counterparty, e.balance, "
    "e.raw, e.raw_sha256, s.path, s.sha256, e.first_line, e.last_line"
)


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, path: Path | str, *, create: bool = False):
        self.path = Path(path)
        if not create and not self.path.exists():
            raise VaultError(f"no vault at {self.path}; run `memvo init` first")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA foreign_keys = ON")
        try:
            self.db.executescript(_SCHEMA)
            row = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if row is None:
                self.db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
                self.db.commit()
            elif int(row[0]) > SCHEMA_VERSION:
                raise VaultError(f"vault schema {row[0]} is newer than this memvo ({SCHEMA_VERSION})")
        except Exception:
            self.db.close()
            raise

    @classmethod
    def init(cls, path: Path | str | None = None) -> Vault:
        return cls(path or default_vault_path(), create=True)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Vault:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ensure_account(self, name: str, kind: str = "bank", currency: str | None = None) -> None:
        if not name.strip():
            raise VaultError("account name is empty")
        self.db.execute(
            "INSERT OR IGNORE INTO accounts(name, kind, currency, created_at) VALUES (?,?,?,?)",
            (name, kind, currency, _now()),
        )

    def accounts(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT a.name, a.kind, a.currency, COUNT(e.id), COALESCE(SUM(e.amount),0),
                      MIN(e.day), MAX(e.day)
               FROM accounts a LEFT JOIN entries e ON e.account = a.name
               GROUP BY a.name ORDER BY a.name"""
        ).fetchall()
        return [
            {
                "name": r[0], "kind": r[1], "currency": r[2], "entries": r[3],
                "net": fmt(r[4]), "first": r[5], "last": r[6],
            }
            for r in rows
        ]

    def periods(self, account: str | None = None) -> list[dict]:
        sql = "SELECT account, period, COUNT(*), SUM(CASE WHEN amount>0 THEN amount ELSE 0 END), " \
              "SUM(CASE WHEN amount<0 THEN amount ELSE 0 END) FROM entries"
        args: tuple = ()
        if account:
            sql += " WHERE account = ?"
            args = (account,)
        sql += " GROUP BY account, period ORDER BY account, period"
        return [
            {"account": a, "period": p, "entries": n, "in": fmt(i), "out": fmt(o)}
            for a, p, n, i, o in self.db.execute(sql, args)
        ]

    def import_csv(
        self,
        path: Path | str,
        account: str,
        *,
        kind: str = "bank",
        columns: dict[str, str] | None = None,
    ) -> ImportReport:
        p = Path(path).expanduser().resolve()
        data = p.read_bytes()
        digest = sha256_bytes(data)
        text = data.decode("utf-8-sig", errors="strict")
        parsed = read_csv(text, columns)

        with self.db:
            self.ensure_account(account, kind)
            existing = self.db.execute(
                "SELECT id FROM sources WHERE sha256=? AND account=?", (digest, account)
            ).fetchone()
            if existing:
                count = self.db.execute(
                    "SELECT COUNT(*) FROM entries WHERE source_id=?", (existing[0],)
                ).fetchone()[0]
                return ImportReport(
                    existing[0], str(p), digest, account, 0, count, parsed.skipped,
                    _cols(parsed.columns),
                )
            cur = self.db.execute(
                "INSERT INTO sources(path, sha256, account, format, rows, skipped, imported_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(p), digest, account, "csv", len(parsed.rows), len(parsed.skipped), _now()),
            )
            source_id = cur.lastrowid
            added = 0
            for row in parsed.rows:
                amount = to_scaled(row.amount)
                day = row.when.isoformat()
                self.db.execute(
                    "INSERT INTO entries(id, source_id, account, first_line, last_line, raw, raw_sha256, "
                    "day, period, amount, currency, description, counterparty, balance, fingerprint) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        entry_id(digest, row.first_line, row.raw), source_id, account,
                        row.first_line, row.last_line, row.raw, sha256_text(row.raw),
                        day, day[:7], amount, row.currency, row.description, row.counterparty,
                        to_scaled(row.balance) if row.balance is not None else None,
                        fingerprint(account, day, amount, row.description or row.counterparty),
                    ),
                )
                added += 1
        return ImportReport(source_id, str(p), digest, account, added, 0, parsed.skipped, _cols(parsed.columns))

    def get(self, entry_id_: str) -> Entry | None:
        row = self.db.execute(
            f"SELECT {_ENTRY_COLS} FROM entries e JOIN sources s ON s.id = e.source_id WHERE e.id = ?",
            (entry_id_,),
        ).fetchone()
        return Entry(*row) if row else None

    def entries(self, account: str | None = None, *, since: str | None = None, until: str | None = None) -> list[Entry]:
        sql = f"SELECT {_ENTRY_COLS} FROM entries e JOIN sources s ON s.id = e.source_id WHERE 1=1"
        args: list = []
        if account:
            sql += " AND e.account = ?"
            args.append(account)
        if since:
            sql += " AND e.day >= ?"
            args.append(since)
        if until:
            sql += " AND e.day <= ?"
            args.append(until)
        sql += " ORDER BY e.day, e.source_id, e.first_line"
        return [Entry(*r) for r in self.db.execute(sql, args)]

    def search(
        self,
        query: str,
        *,
        account: str | None = None,
        period: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 10,
    ) -> list[Entry]:
        terms = _fts_terms(query)
        filters, args = _filters(account, period, since, until)
        if not terms:
            sql = (f"SELECT {_ENTRY_COLS} FROM entries e JOIN sources s ON s.id = e.source_id "
                   f"WHERE 1=1{filters} ORDER BY e.day DESC LIMIT ?")
            return [Entry(*r) for r in self.db.execute(sql, (*args, limit))]
        for joiner in (" AND ", " OR "):
            sql = (
                f"SELECT {_ENTRY_COLS} FROM entries_fts f JOIN entries e ON e.rowid = f.rowid "
                f"JOIN sources s ON s.id = e.source_id WHERE entries_fts MATCH ?{filters} "
                f"ORDER BY bm25(entries_fts, 1.0, 2.0, 2.0), e.day DESC LIMIT ?"
            )
            rows = self.db.execute(sql, (joiner.join(terms), *args, limit)).fetchall()
            if rows or len(terms) == 1:
                return [Entry(*r) for r in rows]
        return []

    def sources(self) -> list[dict]:
        return [
            {"id": i, "path": p, "sha256": h, "account": a, "rows": r, "skipped": s, "imported_at": t}
            for i, p, h, a, r, s, t in self.db.execute(
                "SELECT id, path, sha256, account, rows, skipped, imported_at FROM sources ORDER BY id"
            )
        ]

    def stats(self) -> dict:
        n_entries, n_accounts, n_sources = self.db.execute(
            "SELECT (SELECT COUNT(*) FROM entries), (SELECT COUNT(*) FROM accounts), (SELECT COUNT(*) FROM sources)"
        ).fetchone()
        first, last = self.db.execute("SELECT MIN(day), MAX(day) FROM entries").fetchone()
        return {
            "vault": str(self.path), "accounts": n_accounts, "sources": n_sources,
            "entries": n_entries, "first": first, "last": last,
        }


def _filters(account, period, since, until) -> tuple[str, list]:
    sql, args = "", []
    for col, op, val in (("e.account", "=", account), ("e.period", "=", period),
                         ("e.day", ">=", since), ("e.day", "<=", until)):
        if val:
            sql += f" AND {col} {op} ?"
            args.append(val)
    return sql, args


def _fts_terms(query: str) -> list[str]:
    words = re.findall(r"[\w][\w.\-']*", query.lower(), flags=re.UNICODE)
    return ['"' + w.replace('"', "") + '"*' for w in words if len(w) > 1 or w.isdigit()]


def _cols(columns) -> dict[str, str | None]:
    return {k: v for k, v in columns.__dict__.items() if v}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

