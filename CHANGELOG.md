# Changelog

## Unreleased

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
