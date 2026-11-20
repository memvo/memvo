"""MCP server over stdio (JSON-RPC 2.0, one message per line).

Read-only by design: an agent can search, inspect, audit and reconcile, but
cannot import, edit or delete. Imports stay a deliberate human step.
Every tool result that mentions an entry includes its receipt, so the agent
can quote the source line instead of paraphrasing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__
from .audit import audit
from .money import AmountError, parse_amount, to_scaled
from .reconcile import reconcile
from .vault import Vault

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Memvo holds the user's financial records as verbatim rows from their own statement files. "
    "Before stating any amount, date or payee, find it with memvo_search and cite the receipt "
    "(source file and line). If nothing matches, say so; do not estimate."
)

_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "memvo_search",
        "description": "Full-text search over stored transactions. Each hit includes a receipt with the "
        "source file, line range, file SHA-256 and the raw line. Empty query lists the latest entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "account": {"type": "string"},
                "period": {"type": "string", "pattern": r"^\d{4}-\d{2}$", "description": "YYYY-MM"},
                "since": _DATE,
                "until": _DATE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "memvo_get_entry",
        "description": "Fetch one entry by id with its receipt.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memvo_accounts",
        "description": "List accounts with entry counts, net total and date range.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memvo_periods",
        "description": "Money in and out per account per month.",
        "inputSchema": {
            "type": "object",
            "properties": {"account": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "memvo_audit",
        "description": "Re-hash every source file and compare each stored row with the file on disk. "
        "Also lists likely duplicates across overlapping exports.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memvo_reconcile",
        "description": "Check running balances in the account's statements, and optionally compare the sum "
        "of entries with an expected balance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account": {"type": "string"},
                "expected": {"type": "string", "description": "e.g. \"4131.82\" or \"1.955.000,00\", "
                             "or \"statement\" for the newest imported OFX ledger balance"},
                "as_of": _DATE,
                "opening": {"type": "string"},
            },
            "required": ["account"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memvo_stats",
        "description": "Vault summary: path, counts and date range.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class ToolError(Exception):
    pass


def _money(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        return to_scaled(parse_amount(value))
    except AmountError as exc:
        raise ToolError(f"{name}: {exc}") from exc


class Server:
    def __init__(self, vault_path: Path | str):
        self.vault_path = Path(vault_path)
        self.handlers: dict[str, Callable[[Vault, dict], Any]] = {
            "memvo_search": self._search,
            "memvo_get_entry": self._get,
            "memvo_accounts": lambda v, a: v.accounts(),
            "memvo_periods": lambda v, a: v.periods(a.get("account")),
            "memvo_audit": lambda v, a: audit(v).as_dict(),
            "memvo_reconcile": self._reconcile,
            "memvo_stats": lambda v, a: v.stats(),
        }

    @staticmethod
    def _search(v: Vault, a: dict) -> list[dict]:
        limit = int(a.get("limit", 10))
        if not 1 <= limit <= 100:
            raise ToolError("limit must be between 1 and 100")
        hits = v.search(
            a.get("query", ""), account=a.get("account"), period=a.get("period"),
            since=a.get("since"), until=a.get("until"), limit=limit,
        )
        return [e.as_dict() for e in hits]

    @staticmethod
    def _get(v: Vault, a: dict) -> dict:
        e = v.get(a["id"])
        if e is None:
            raise ToolError(f"no entry {a['id']}")
        return e.as_dict()

    @staticmethod
    def _reconcile(v: Vault, a: dict) -> dict:
        use_statement = a.get("expected") == "statement"
        try:
            rep = reconcile(
                v, a["account"],
                expected=None if use_statement else _money(a.get("expected"), "expected"),
                as_of=a.get("as_of"), opening=_money(a.get("opening"), "opening") or 0,
                use_statement=use_statement,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return rep.as_dict()

    def call_tool(self, name: str, args: dict) -> dict:
        handler = self.handlers.get(name)
        if handler is None:
            raise KeyError(name)
        tool = next(t for t in TOOLS if t["name"] == name)
        missing = [k for k in tool["inputSchema"].get("required", []) if k not in args]
        unknown = [k for k in args if k not in tool["inputSchema"]["properties"]]
        try:
            if missing or unknown:
                raise ToolError(f"missing {missing} unknown {unknown}".replace(" []", " none"))
            if not self.vault_path.exists():
                raise ToolError(f"no vault at {self.vault_path}; run `memvo init` and import a statement")
            with Vault(self.vault_path) as v:
                data = handler(v, args)
        except ToolError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        text = json.dumps(data, ensure_ascii=False, indent=2)
        result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
        result["structuredContent"] = data if isinstance(data, dict) else {"results": data}
        return result

    def handle(self, msg: Any) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        method, mid, params = msg["method"], msg.get("id"), msg.get("params") or {}
        if "id" not in msg:
            return None  # notifications (initialized, cancelled) need no reply
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return _ok(mid, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "memvo", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(args, dict):
                return _error(mid, -32602, "arguments must be an object")
            try:
                return _ok(mid, self.call_tool(name, args))
            except KeyError:
                return _error(mid, -32602, f"unknown tool {name!r}")
        return _error(mid, -32601, f"method not found: {method}")

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply: dict | None = _error(None, -32700, "parse error")
            else:
                reply = self.handle(msg)
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()


def _ok(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
