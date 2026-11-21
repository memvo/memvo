# Memvo

[memvo.pro](https://memvo.pro) · [X @MEMVOpro](https://x.com/MEMVOpro)

Local-first financial memory. Import your statements once, then ask about
your money and get the exact line each answer came from.

Memvo keeps every transaction verbatim, next to the SHA-256 of the file it
was read from. It never summarises, categorises with a model, or sends data
anywhere. Your vault is one SQLite file on your machine.

> **Status: pre-alpha.** Output above is from `tests/fixtures/checking.csv`. CSV import, search, audit and reconcile work and are
> tested, and agents can read the vault over MCP. PDF import and on-chain wallet import are not
> built yet. See [Status](#status).

## Why

Ask an assistant "what did I pay for that subscription in October?" and it
will often answer with a number it cannot show you. Memvo is built the other
way round: an answer is a stored row plus a receipt, or it is nothing.

```text
$ memvo search streamly
2026-11-05          -17.99  checking     STREAMLY SUBSCRIPTION, MONTHLY
    e_87f7eaf199f9cde5  checking.csv:7
2026-10-05          -15.99  checking     STREAMLY SUBSCRIPTION, MONTHLY
    e_477cc512787183fc  checking.csv:4
```

```text
$ memvo show e_87f7eaf199f9cde5
e_87f7eaf199f9cde5
2026-11-05  -17.99    checking
STREAMLY SUBSCRIPTION, MONTHLY

receipt
  source  /home/me/statements/checking.csv (line 7)
  file    sha256 7e61003a02cb6628f28bcbd0e17aba1cef8d823813df4f95324ecfc53c8bdbdb
  row     sha256 6fe2f1f304317c9b9e6e96db7823ae80c72b38804c7ced445335d126a9a81ac5
  raw     2026-11-05,"STREAMLY SUBSCRIPTION, MONTHLY",-17.99,4131.82
```

## How the vault is laid out

```text
vault ── accounts ── periods (YYYY-MM) ── entries ── receipt
           checking     2026-10              raw line, line range,
           savings      2026-11              file sha256, row sha256
           broker
```

- **Entries are verbatim.** The `raw` field is the exact text from the file,
  including quoted fields that span several lines.
- **IDs are deterministic.** An entry id is derived from the file hash, the
  line number and the raw text, so importing the same file twice adds
  nothing.
- **Amounts are exact.** Stored as integers scaled by 10,000. No floats.

## Install

Requires Python 3.10 or newer. No other dependencies.

```bash
pip install memvo   # 0.1.0a1, pre-alpha
memvo init
```

The vault lives at `~/.memvo/vault.db`, or `$MEMVO_HOME/vault.db`, or wherever
`--vault` points.

## Use

```bash
memvo import ~/Downloads/checking.csv --account checking
memvo import mutasi.csv --account tabungan          # ; separators, 1.234,56 amounts, debet/kredit columns
memvo import export.csv --account broker --kind broker --map amount=Net
memvo import download.qfx --account card            # OFX/QFX is recognised from the content

memvo search rent                       # every hit carries its receipt
memvo search coffee --period 2026-11
memvo show e_87f7eaf199f9cde5

memvo accounts
memvo periods --account checking

memvo audit                             # re-hash every source, check every row
memvo reconcile --account checking --expect 4131.82
memvo reconcile --account checking --expect statement   # use the ledger balance in the newest OFX
```

Add `--json` to any command for machine-readable output.

### Import

Column detection reads the header and recognises common English and
Indonesian names (`Date`/`Tanggal`, `Amount`/`Jumlah`, `Debit`/`Debet`,
`Credit`/`Kredit`, `Balance`/`Saldo`, …). Use `--map role=Column` when it
guesses wrong. Separators are sniffed (`,` `;` tab `|`). Amount formats
handled: `1,234.56`, `1.234,56`, `1 234,56`, `(12.50)`, `12.50-`,
`IDR 1.500.000`. Day-first versus month-first is decided once per file by
looking at all its dates.

Rows that cannot be parsed are listed with their line number and reason. They
are never guessed.

OFX and QFX files (the "Download for Quicken/Money" option many banks offer)
are read in both the old SGML form and the XML form. Each `<STMTTRN>` block is
stored verbatim as one entry, its `FITID` is kept as the bank reference, and
the statement's ledger balance is remembered for `reconcile --expect statement`.
Overlapping downloads are matched on `FITID`. Files that are not UTF-8 are read
as Windows-1252.

### Audit

`memvo audit` re-reads every imported file. If the file hash still matches,
each entry's raw text is compared with the bytes on disk. A file that changed
or disappeared is reported as `CHANGED` or `MISSING`; its entries are kept as
they were imported. It also lists likely duplicates across overlapping
exports (same account, day, amount and text in two different files).

Exit code is `0` when everything matches and `2` when it does not, so it can
run in a cron job or CI.

### Reconcile

- **Running balance.** If a statement has a balance column, every row must
  satisfy `previous balance + amount = balance`. A break points at a missing,
  duplicated or misread row. Newest-first and oldest-first files both work.
- **Expected balance.** `--expect` compares the sum of entries (plus
  `--opening`, up to `--as-of`) with a figure you read off a statement or a
  wallet. `--expect statement` takes that figure from the newest imported
  OFX ledger balance.

## Agents (MCP)

`memvo mcp` runs a Model Context Protocol server on stdio. Register it in any
MCP client:

```json
{
  "mcpServers": {
    "memvo": { "command": "memvo", "args": ["mcp"] }
  }
}
```

Tools: `memvo_search`, `memvo_get_entry`, `memvo_accounts`, `memvo_periods`,
`memvo_audit`, `memvo_reconcile`, `memvo_stats`.

The server is read-only. An agent can search, inspect and check, but it
cannot import, edit or delete anything; importing stays a step you take
yourself. Every result that mentions an entry carries its receipt, and the
server tells the client to cite the source line instead of estimating.

## Status

| Feature | State |
|---|---|
| CSV import (bank, card, broker) | Live |
| Search with receipts | Live |
| Audit against source files | Live |
| Reconcile (running and expected balance) | Live |
| MCP server for agents (read-only) | Live |
| OFX / QFX import (1.x SGML and 2.x XML) | Live |
| PDF statement text import | Planned |
| Wallet import from a public address | Planned |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest --cov
```

Coverage must stay at or above 90%.

## Privacy

Memvo makes no network calls. Nothing is uploaded, and there is no
telemetry. Delete the vault file and the data is gone.

## License

MIT
