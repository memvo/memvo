import io
import json
import subprocess
import sys

import pytest

from memvo.mcp import TOOLS, Server


@pytest.fixture
def server(vault, files):
    vault.import_csv(files / "checking.csv", "checking")
    vault.import_csv(files / "broken.csv", "cash")
    return Server(vault.path)


def rpc(server, method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def call(server, name, **args):
    res = rpc(server, "tools/call", {"name": name, "arguments": args})["result"]
    return res, json.loads(res["content"][0]["text"]) if not res["isError"] else res["content"][0]["text"]


def test_initialize_and_list(server):
    init = rpc(server, "initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert init["protocolVersion"] == "2025-03-26"
    assert init["serverInfo"]["name"] == "memvo" and "receipt" in init["instructions"]
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    names = [t["name"] for t in rpc(server, "tools/list")["result"]["tools"]]
    assert names == [t["name"] for t in TOOLS] and "memvo_import" not in names
    assert rpc(server, "ping")["result"] == {}


def test_search_returns_receipts(server):
    res, hits = call(server, "memvo_search", query="rent")
    assert not res["isError"] and hits[0]["amount"] == "-1,450.00"
    assert hits[0]["receipt"]["raw"] == "2026-10-20,RENT OCTOBER,-1450.00,4149.81"
    assert res["structuredContent"]["results"] == hits
    _, latest = call(server, "memvo_search", limit=1)
    assert len(latest) == 1


def test_get_accounts_periods_stats(server):
    _, hits = call(server, "memvo_search", query="payroll")
    _, entry = call(server, "memvo_get_entry", id=hits[0]["id"])
    assert entry["description"] == "PAYROLL ACME LTD"
    res, msg = call(server, "memvo_get_entry", id="e_nope")
    assert res["isError"] and "no entry" in msg
    _, accts = call(server, "memvo_accounts")
    assert {a["name"] for a in accts} == {"checking", "cash"}
    _, periods = call(server, "memvo_periods", account="checking")
    assert [p["period"] for p in periods] == ["2026-10", "2026-11"]
    _, stats = call(server, "memvo_stats")
    assert stats["entries"] == 9


def test_audit_and_reconcile(server):
    _, rep = call(server, "memvo_audit")
    assert rep["ok"] is True
    _, rec = call(server, "memvo_reconcile", account="checking", expected="4,131.82")
    assert rec["ok"] and rec["difference"] == "0.00"
    _, broken = call(server, "memvo_reconcile", account="cash")
    assert not broken["ok"] and broken["running_balance"][0]["breaks"][0]["diff"] == "-3.00"
    res, msg = call(server, "memvo_reconcile", account="checking", expected="lots")
    assert res["isError"] and msg.startswith("expected:")


def test_argument_validation(server):
    res, msg = call(server, "memvo_reconcile")
    assert res["isError"] and "missing ['account']" in msg
    res, msg = call(server, "memvo_search", colour="red")
    assert res["isError"] and "unknown ['colour']" in msg
    res, msg = call(server, "memvo_search", limit=0)
    assert res["isError"] and "limit" in msg
    bad = rpc(server, "tools/call", {"name": "memvo_search", "arguments": [1]})
    assert bad["error"]["code"] == -32602
    unknown = rpc(server, "tools/call", {"name": "memvo_delete_everything"})
    assert unknown["error"]["code"] == -32602


def test_protocol_errors(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert server.handle([1, 2])["error"]["code"] == -32600
    assert server.handle({"id": 1, "method": "ping"})["error"]["code"] == -32600
    assert rpc(server, "resources/list")["error"]["code"] == -32601


def test_missing_vault(tmp_path):
    res = Server(tmp_path / "none.db").call_tool("memvo_stats", {})
    assert res["isError"] and "memvo init" in res["content"][0]["text"]


def test_serve_loop(server):
    stdin = io.StringIO(
        "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "",
            "{not json",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n"
    )
    out = io.StringIO()
    server.serve(stdin, out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == -32700


def test_cli_mcp_subprocess(server):
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "memvo_search", "arguments": {"query": "streamly"}}},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "memvo", "mcp", "--vault", str(server.vault_path)],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True, text=True, timeout=30, check=True,
    )
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    hits = replies[1]["result"]["structuredContent"]["results"]
    assert len(hits) == 2 and all(h["receipt"]["source"].endswith("checking.csv") for h in hits)
