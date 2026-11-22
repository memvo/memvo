from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import audit
from .money import AmountError, parse_amount, to_scaled
from .reconcile import reconcile
from .vault import Vault, VaultError, default_vault_path


def _vault(args) -> Vault:
    return Vault(args.vault or default_vault_path())


def _emit(args, payload, text: str) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(text)


def _parse_map(pairs: list[str] | None) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        role, sep, col = pair.partition("=")
        if not sep or not role or not col:
            raise SystemExit(f"--map expects role=column, got {pair!r}")
        out[role.strip()] = col.strip()
    return out


def cmd_init(args) -> int:
    path = Path(args.vault or default_vault_path())
    existed = path.exists()
    with Vault.init(path) as v:
        _emit(args, v.stats(), f"{'Vault already at' if existed else 'Vault created at'} {path}")
    return 0


def cmd_import(args) -> int:
    with _vault(args) as v:
        r = v.import_csv(args.file, args.account, kind=args.kind, columns=_parse_map(args.map))
    lines = [
        f"{r.account}: {r.added} entries added from {Path(r.path).name} ({r.format})",
        f"source sha256 {r.sha256[:16]}…",
    ]
    if r.already_present:
        lines[0] = f"{r.account}: file already imported ({r.already_present} entries), nothing added"
    if r.skipped:
        lines.append(f"{len(r.skipped)} rows skipped:")
        lines += [f"  line {n}: {why}" for n, why in r.skipped[:10]]
    if r.columns:
        lines.append("columns: " + ", ".join(f"{k}={v}" for k, v in r.columns.items()))
    if r.statement_balance is not None:
        lines.append(f"statement balance {r.statement_balance} as of {r.statement_as_of}")
    _emit(args, r.__dict__, "\n".join(lines))
    return 0


def _entry_line(e) -> str:
    who = e.counterparty or e.description
    return f"{e.day}  {e.amount_text:>14}  {e.account:<12} {who[:48]}\n    {e.id}  {Path(e.source_path).name}:{e.first_line}"


def cmd_search(args) -> int:
    with _vault(args) as v:
        hits = v.search(
            " ".join(args.query), account=args.account, period=args.period,
            since=args.since, until=args.until, limit=args.limit,
        )
    text = "\n".join(_entry_line(e) for e in hits) if hits else "No entries match."
    _emit(args, [e.as_dict() for e in hits], text)
    return 0 if hits else 1


def cmd_show(args) -> int:
    with _vault(args) as v:
        e = v.get(args.entry)
    if not e:
        print(f"no entry {args.entry}", file=sys.stderr)
        return 1
    r = e.receipt()
    text = (
        f"{e.id}\n{e.day}  {e.amount_text}  {e.currency or ''}  {e.account}\n"
        f"{e.description}\n\nreceipt\n  source  {r['source']} (line{'s' if '-' in r['lines'] else ''} {r['lines']})\n"
        f"  file    sha256 {r['source_sha256']}\n  row     sha256 {r['raw_sha256']}\n  raw     {r['raw']}"
    )
    _emit(args, e.as_dict(), text)
    return 0


def cmd_accounts(args) -> int:
    with _vault(args) as v:
        rows = v.accounts()
    text = "\n".join(
        f"{a['name']:<16} {a['kind']:<8} {a['entries']:>6} entries  net {a['net']:>14}  {a['first'] or '-'} → {a['last'] or '-'}"
        for a in rows
    ) or "No accounts yet. Import a statement with `memvo import FILE --account NAME`."
    _emit(args, rows, text)
    return 0


def cmd_periods(args) -> int:
    with _vault(args) as v:
        rows = v.periods(args.account)
    text = "\n".join(
        f"{p['account']:<16} {p['period']}  {p['entries']:>5}  in {p['in']:>14}  out {p['out']:>14}" for p in rows
    ) or "No entries yet."
    _emit(args, rows, text)
    return 0


def cmd_audit(args) -> int:
    with _vault(args) as v:
        rep = audit(v)
    lines = []
    for s in rep.sources:
        mark = "ok" if s.status == "ok" and not s.mismatched else s.status.upper()
        extra = f", {len(s.mismatched)} rows differ" if s.mismatched else ""
        lines.append(f"[{mark}] {Path(s.path).name}: {s.entries} entries{extra}")
    if rep.duplicates:
        lines.append(f"{len(rep.duplicates)} possible duplicates across files (same account, day, amount, text):")
        lines += ["  " + " ".join(d) for d in rep.duplicates[:10]]
    lines.append("All entries match their sources." if rep.ok else "Audit found problems.")
    _emit(args, rep.as_dict(), "\n".join(lines))
    return 0 if rep.ok else 2


def cmd_reconcile(args) -> int:
    try:
        use_statement = args.expect == "statement"
        expected = to_scaled(parse_amount(args.expect)) if args.expect and not use_statement else None
        opening = to_scaled(parse_amount(args.opening)) if args.opening else 0
    except AmountError as exc:
        raise SystemExit(str(exc)) from exc
    with _vault(args) as v:
        rep = reconcile(v, args.account, expected=expected, as_of=args.as_of, opening=opening,
                        use_statement=use_statement)
    lines = []
    for c in rep.chains:
        state = "unbroken" if not c.breaks else f"{len(c.breaks)} breaks"
        lines.append(f"running balance in {Path(c.path).name}: {c.rows_checked} rows, {c.order}, {state}")
        for b in c.breaks[:10]:
            lines.append(f"  {b.day} {b.entry}: expected {b.expected}, statement says {b.stated} (off by {b.diff})")
    if rep.expected is not None:
        lines.append(
            f"as of {rep.as_of or 'latest'}: entries add up to {rep.computed}, "
            f"{'statement says' if rep.expected_from == 'statement' else 'expected'} {rep.expected}, "
            f"difference {rep.difference}"
        )
    if not lines:
        lines.append("Nothing to check: no balance column in the sources and no --expect given.")
    _emit(args, rep.as_dict(), "\n".join(lines))
    return 0 if rep.ok else 2


def cmd_mcp(args) -> int:
    from .mcp import Server

    Server(args.vault or default_vault_path()).serve()
    return 0


def cmd_demo(args) -> int:
    from .demo import run

    return run(main, keep=args.keep)


def cmd_stats(args) -> int:
    with _vault(args) as v:
        s = v.stats()
    _emit(args, s, "\n".join(f"{k:<9} {v}" for k, v in s.items()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memvo", description="Local-first financial memory with a receipt for every answer.")
    p.add_argument("--version", action="version", version=f"memvo {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", help="vault file (default: $MEMVO_HOME/vault.db or ~/.memvo/vault.db)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", parents=[common], help="create a vault").set_defaults(fn=cmd_init)

    s = sub.add_parser("import", parents=[common], help="import a CSV or OFX/QFX statement")
    s.add_argument("file")
    s.add_argument("--account", required=True)
    s.add_argument("--kind", default="bank", choices=["bank", "card", "broker", "wallet", "cash", "other"])
    s.add_argument("--map", action="append", metavar="ROLE=COLUMN",
                   help="override column detection, e.g. --map amount=Betrag")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("search", parents=[common], help="find entries; each hit carries its receipt")
    s.add_argument("query", nargs="*")
    s.add_argument("--account")
    s.add_argument("--period", help="YYYY-MM")
    s.add_argument("--since", help="YYYY-MM-DD")
    s.add_argument("--until", help="YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("show", parents=[common], help="show one entry and its receipt")
    s.add_argument("entry")
    s.set_defaults(fn=cmd_show)

    sub.add_parser("accounts", parents=[common], help="list accounts").set_defaults(fn=cmd_accounts)

    s = sub.add_parser("periods", parents=[common], help="money in and out per month")
    s.add_argument("--account")
    s.set_defaults(fn=cmd_periods)

    sub.add_parser("audit", parents=[common], help="check every entry against its source file").set_defaults(fn=cmd_audit)

    s = sub.add_parser("reconcile", parents=[common], help="check balances")
    s.add_argument("--account", required=True)
    s.add_argument("--expect", help="balance shown on the statement or wallet, or 'statement' to use the "
                   "ledger balance from the newest imported OFX")
    s.add_argument("--as-of", help="YYYY-MM-DD, default: all entries")
    s.add_argument("--opening", help="opening balance before the first entry")
    s.set_defaults(fn=cmd_reconcile)

    sub.add_parser("stats", parents=[common], help="vault summary").set_defaults(fn=cmd_stats)
    sub.add_parser("mcp", parents=[common], help="run the read-only MCP server on stdio").set_defaults(fn=cmd_mcp)

    s = sub.add_parser("demo", help="guided run on made-up statements, in a throwaway folder")
    s.add_argument("--keep", metavar="DIR", help="write the demo files and vault to DIR and keep them")
    s.set_defaults(fn=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (VaultError, ValueError, FileNotFoundError, UnicodeDecodeError) as exc:
        print(f"memvo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
