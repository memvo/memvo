# MCP tools

`memvo mcp` speaks the Model Context Protocol over stdio (JSON-RPC 2.0, one
message per line). Supported protocol versions: `2025-06-18`, `2025-03-26`,
`2024-11-05`.

All tools are read-only. Imports stay a manual step on the command line.

| Tool | Input | Returns |
|---|---|---|
| `memvo_search` | `query`, `account`, `period` (YYYY-MM), `since`, `until`, `limit` (1–100, default 10) | Matching entries, best match first (newest first for an empty query), each with a receipt. |
| `memvo_get_entry` | `id` (required) | One entry with its receipt. |
| `memvo_accounts` | none | Accounts with entry count, net total and date range. |
| `memvo_periods` | `account` (optional) | Money in and out per account per month. |
| `memvo_audit` | none | Per-file status (`ok`, `changed`, `missing`), mismatched rows and likely duplicates. |
| `memvo_reconcile` | `account` (required), `expected`, `as_of`, `opening` | Running-balance breaks and the difference from an expected balance. `expected: "statement"` uses the newest OFX ledger balance. |
| `memvo_stats` | none | Vault path, counts and date range. |

## Receipts

Every result that mentions an entry carries:

```json
{
  "entry": "e_87f7eaf199f9cde5",
  "source": "/home/me/statements/checking.csv",
  "lines": "7",
  "source_sha256": "7e61003a…",
  "raw_sha256": "6fe2f1f3…",
  "raw": "2026-11-05,\"STREAMLY SUBSCRIPTION, MONTHLY\",-17.99,4131.82"
}
```

Multi-line rows give a range such as `"12-14"`. OFX entries add `bank_ref`, the
bank's FITID. PDF entries add `page`, and `lines` counts printed lines on that
page.

The server's `instructions` ask the agent to cite the receipt before stating
an amount, and to say so when nothing matches instead of estimating.
