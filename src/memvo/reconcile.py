"""Reconcile: compare what the entries add up to with what the statement says.

Two checks:
  1. Running balance. When a source has a balance column, each row's balance
     must equal the previous row's balance plus this row's amount. A break
     means a row is missing, duplicated or misread. Rows are walked in file
     order, and both newest-first and oldest-first exports are handled.
  2. Expected balance. Given a balance the user reads off a statement or a
     wallet, opening + sum(entries up to that day) must equal it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .money import fmt
from .vault import Vault


@dataclass
class Break:
    entry: str
    day: str
    expected: str
    stated: str
    diff: str


@dataclass
class ChainResult:
    source_id: int
    path: str
    rows_checked: int
    order: str
    breaks: list[Break] = field(default_factory=list)


@dataclass
class ReconcileReport:
    account: str
    chains: list[ChainResult]
    computed: str | None = None
    expected: str | None = None
    difference: str | None = None
    as_of: str | None = None

    @property
    def ok(self) -> bool:
        no_breaks = all(not c.breaks for c in self.chains)
        return no_breaks and (self.difference is None or self.difference == fmt(0))

    def as_dict(self) -> dict:
        return {
            "account": self.account,
            "ok": self.ok,
            "as_of": self.as_of,
            "computed": self.computed,
            "expected": self.expected,
            "difference": self.difference,
            "running_balance": [
                {"source": c.source_id, "path": c.path, "rows": c.rows_checked, "order": c.order,
                 "breaks": [b.__dict__ for b in c.breaks]}
                for c in self.chains
            ],
        }


def _chain(rows: list[tuple]) -> tuple[str, list[Break]]:
    """rows: (id, day, amount, balance) in file order, balance not null."""
    def walk(seq):
        out = []
        for prev, cur in zip(seq, seq[1:]):
            want = prev[3] + cur[2]
            if want != cur[3]:
                out.append(Break(cur[0], cur[1], fmt(want), fmt(cur[3]), fmt(cur[3] - want)))
        return out

    forward = walk(rows)
    if not forward:
        return "oldest-first", []
    backward = walk(rows[::-1])
    if len(backward) < len(forward):
        return "newest-first", backward
    return "oldest-first", forward


def reconcile(
    vault: Vault,
    account: str,
    *,
    expected: int | None = None,
    as_of: str | None = None,
    opening: int = 0,
) -> ReconcileReport:
    chains = []
    for src in vault.sources():
        if src["account"] != account:
            continue
        rows = vault.db.execute(
            "SELECT id, day, amount, balance FROM entries WHERE source_id=? AND balance IS NOT NULL "
            "ORDER BY first_line",
            (src["id"],),
        ).fetchall()
        if len(rows) < 2:
            continue
        order, breaks = _chain(rows)
        chains.append(ChainResult(src["id"], src["path"], len(rows), order, breaks))

    report = ReconcileReport(account, chains)
    if expected is not None:
        sql, args = "SELECT COALESCE(SUM(amount),0) FROM entries WHERE account=?", [account]
        if as_of:
            sql += " AND day <= ?"
            args.append(as_of)
        total = opening + vault.db.execute(sql, args).fetchone()[0]
        report.computed = fmt(total)
        report.expected = fmt(expected)
        report.difference = fmt(expected - total)
        report.as_of = as_of
    return report
