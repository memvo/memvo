# Changelog

## Unreleased

- CSV import with header detection (English and Indonesian column names),
  sniffed separators, day/month order decided per file, multi-line records.
- Vault in one SQLite file: accounts, periods, verbatim entries, source hashes.
- `search` with full-text matching; every hit carries a receipt.
- `audit` re-hashes sources and checks each row against the file.
- `reconcile` checks running balances and an expected balance.
- `memvo mcp`: read-only MCP server on stdio with seven tools; results carry receipts.
