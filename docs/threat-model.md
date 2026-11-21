# Threat model

Memvo holds personal financial records, so this page says plainly what it
protects, what it does not, and how to check each claim yourself.

## What Memvo stores, and where

| Data | Where | Format |
|---|---|---|
| Transactions, verbatim | `~/.memvo/vault.db` (or `$MEMVO_HOME/vault.db`) | SQLite |
| Path and SHA-256 of each imported file | same file | SQLite |
| The statement files themselves | wherever you keep them; Memvo only reads them | untouched |

Nothing else is written. There is no config file, cache, log or telemetry.

## Claims and how to verify them

| Claim | How to check |
|---|---|
| No network access | `grep -rE "socket\|urllib\|http" src/` finds nothing. The test suite blocks every socket call (`tests/conftest.py`), so any network use fails CI. |
| No dependencies at run time | `dependencies = []` in `pyproject.toml`. Only the Python standard library is imported. |
| Agents cannot change data | The MCP server exposes seven tools, all read-only (`src/memvo/mcp.py`). There is no import, edit or delete tool. |
| Stored rows match your files | `memvo audit` re-hashes each source file and compares every stored row with the bytes on disk. |
| Released packages come from this repository | PyPI releases are built and uploaded by `.github/workflows/publish.yml` through trusted publishing. No upload token exists. |

## In scope

- **Malformed or hostile statement files.** CSV and OFX are parsed with the
  standard library and regular expressions; there is no XML entity
  expansion, `eval` or shell call. Bad rows are skipped and reported with
  their line number. `tests/test_robustness.py` feeds the readers random
  input on every CI run.
- **SQL injection.** Every value reaches SQLite as a bound parameter. SQL
  text is assembled only from fixed fragments in `vault.py`, never from
  input.
- **An agent asking for too much.** MCP tool inputs are validated against a
  JSON schema with `additionalProperties: false`, and results are capped
  (`limit` at most 100).

## Out of scope

- **Someone with access to your user account.** The vault is a plain SQLite
  file protected by file-system permissions only. Use full-disk encryption.
- **What an agent does with an answer.** Memvo returns rows with receipts;
  the MCP client decides where that text goes. A cloud-hosted model will
  receive whatever the tools return.
- **Correctness of the bank's own export.** Memvo reports what the file says.
  `memvo reconcile` catches broken running balances but cannot know about a
  transaction the bank left out.

## Reporting

See [SECURITY.md](../SECURITY.md).
