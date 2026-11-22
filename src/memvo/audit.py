"""Audit: prove that every stored entry still matches the file it came from.

For each source the file is re-read and re-hashed. If the hash matches, every
entry from it is checked line by line against the bytes on disk. If the file
changed or disappeared, its entries are reported, never silently rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .importers.pdf_text import PdfError, extract
from .vault import Vault, decode_text, sha256_bytes, sha256_text


@dataclass
class SourceCheck:
    source_id: int
    path: str
    status: str  # ok | changed | missing
    entries: int
    mismatched: list[str] = field(default_factory=list)


@dataclass
class AuditReport:
    sources: list[SourceCheck]
    duplicates: list[list[str]]

    @property
    def ok(self) -> bool:
        return all(s.status == "ok" and not s.mismatched for s in self.sources)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "sources": [s.__dict__ for s in self.sources],
            "possible_duplicates": self.duplicates,
        }


def audit(vault: Vault) -> AuditReport:
    checks: list[SourceCheck] = []
    for src in vault.sources():
        rows = vault.db.execute(
            "SELECT id, first_line, last_line, raw, raw_sha256, page FROM entries WHERE source_id=? "
            "ORDER BY page, first_line",
            (src["id"],),
        ).fetchall()
        path = Path(src["path"])
        if not path.exists():
            checks.append(SourceCheck(src["id"], src["path"], "missing", len(rows)))
            continue
        data = path.read_bytes()
        if sha256_bytes(data) != src["sha256"]:
            checks.append(SourceCheck(src["id"], src["path"], "changed", len(rows)))
            continue
        bad = []
        if src["format"] == "pdf":
            # A PDF entry is checked against a fresh extraction of its page.
            try:
                pages = {p.number: [ln.text for ln in p.lines] for p in extract(data)}
            except PdfError:
                pages = {}
            for eid, first, last, raw, raw_sha, page in rows:
                printed = "\n".join(pages.get(page, [])[first - 1 : last])
                if raw != printed or sha256_text(raw) != raw_sha:
                    bad.append(eid)
        else:
            lines = decode_text(data).splitlines(keepends=True)
            # CSV rows equal their line range; an OFX block may share a line with others.
            for eid, first, last, raw, raw_sha, _page in rows:
                on_disk = "".join(lines[first - 1 : last]).rstrip("\r\n")
                if raw not in on_disk or sha256_text(raw) != raw_sha:
                    bad.append(eid)
        checks.append(SourceCheck(src["id"], src["path"], "ok", len(rows), bad))

    dupes = [
        ids.split(",")
        for (ids,) in vault.db.execute(
            """SELECT GROUP_CONCAT(id) FROM entries GROUP BY fingerprint
               HAVING COUNT(DISTINCT source_id) > 1 ORDER BY MIN(day)"""
        )
    ]
    return AuditReport(checks, dupes)
