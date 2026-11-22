# Changelog

## Unreleased

## 0.2.0a1 (2026-11-22)

- PDF text layer reader (`memvo.importers.pdf_text`), standard library only:
  object streams, Flate/ASCIIHex/ASCII85 streams, simple and composite fonts
  with ToUnicode, form XObjects. Each printed line keeps its page and line
  number. Encrypted and scanned PDFs are reported, not read.
- `memvo import` reads text-based PDF statements. Rows are lines that start
  with a date and end with amounts; debit, credit and balance come from the
  column header above them, a DB/DR/CR marker, or the running balance.
  Text-only lines under a row (a reference, a second payee line) join it.
  Opening and closing balances are recognised; the closing one feeds
  `reconcile --expect statement`. Lines that start with a date but cannot be
  read are listed with their page and line.
- Receipts of PDF entries carry the `page` they were printed on, and
  `memvo audit` re-checks them against a fresh extraction of that page.
- Vault schema 3 adds the page column; older vaults are migrated on open.
- `memvo demo` also imports a made-up savings PDF and shows its receipt.

## 0.1.0a3 (2026-11-22)

- Listed in the official MCP Registry as `pro.memvo/memvo` (`server.json`).
- `ROADMAP.md`: what is planned next, and what is not planned.

## 0.1.0a2 (2026-11-22)

- `memvo demo`: a guided run on made-up statements in a throwaway folder,
  ending with `audit` catching an edited source line.
- Fix: on Python 3.10 a CSV file containing NUL bytes crashed the import with
  `_csv.Error`. Such files are now rejected on every Python version with the
  line of the first NUL byte. Found by the new robustness tests.
- Tests: the suite now blocks all network access, and new robustness tests
  feed the CSV and OFX readers random and malformed input.
- Docs: `docs/threat-model.md` and `docs/mcp.md`; `CONTRIBUTING.md` and issue
  templates.
- CI: GitHub Actions pinned to commit SHAs, least-privilege permissions,
  CodeQL, OpenSSF Scorecard and Dependabot.
- The memvo.pro website moved out of this repository; it was never part of
  the package.

## 0.1.0a1 (2026-11-22)

First pre-release on PyPI. Pre-alpha: the vault schema may still change.

- CSV import with header detection (English and Indonesian column names),
  sniffed separators, day/month order decided per file, multi-line records.
- Vault in one SQLite file: accounts, periods, verbatim entries, source hashes.
- `search` with full-text matching; every hit carries a receipt.
- `audit` re-hashes sources and checks each row against the file.
- `reconcile` checks running balances and an expected balance.
- OFX/QFX import (SGML and XML), bank transaction ids, statement ledger balance,
  `reconcile --expect statement`, Windows-1252 fallback, vault schema 2 with
  automatic migration from 1.
- `memvo mcp`: read-only MCP server on stdio with seven tools; results carry receipts.
