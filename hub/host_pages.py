"""Host-aware landing pages: one hub, three hostnames, three pages.

The Host header (or X-Forwarded-Host, when the request came from loopback as the tunnel's does) picks the page
served at `/` and its assets. Any other host, 127.0.0.1 included, gets the browsable index it always got.

The pages are static files under hub/pages/. They hold no counts: the numbers on screen come from the read API
(/v1/kinds, /v1/categories, /v1/skills ...) and from `stats` below, which is computed from the database. The
same figures are embedded in the served HTML as a JSON data block, so a page still has something true to show
when a call fails. That block is data, not script, so the strict Content-Security-Policy does not touch it.

Nothing here writes: the database is opened read-only.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from hub import kinds as kinds_mod

PAGES_DIR = Path(__file__).resolve().parent / "pages"
HOSTS = {
    "skills.axe.onl": "axe",
    "barracks.0perator.co": "barracks",
    "operator.axetechnologies.ca": "operator",
}
LOOPBACK_PEERS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
PLACEHOLDER = "<!--HUB-FALLBACK-->"
# Pages are same-origin apps: script and data from 'self', fonts from Google, no inline script or style, no
# framing, no form posts. Record text is untrusted and is only ever written with textContent.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data: https://0perator.co; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

_FALLBACK_KEEP_CARD = ("title", "kind", "source", "verified", "use_count", "category", "category_label",
                       "category_source", "author", "publisher", "license", "homepage", "risk_flags",
                       "credentials_needed", "trust_tier", "upstream_install", "install", "tags")
_FALLBACK_KEEP_META = ("kind", "source", "verified", "quarantined", "license", "author", "publisher",
                       "trust_tier", "risk_flags", "credentials_needed", "upstream_status", "homepage")
_SAMPLE_SKILLS = 24
_SAMPLE_PLUGINS_COMMUNITY = 6


def clean_host(raw: str | None) -> str:
    return (raw or "").split(",")[0].strip().lower().split(":")[0]


def page_key(host: str | None, forwarded_host: str | None, peer: str | None) -> str | None:
    """The page this request is for, or None for the default behaviour.

    X-Forwarded-Host is believed only from a loopback peer: anyone else could name a host they are not on.
    """
    raw = forwarded_host if forwarded_host and peer in LOOPBACK_PEERS else host
    return HOSTS.get(clean_host(raw))


def asset_names(key: str) -> dict[str, tuple[Path, str]]:
    """Public asset name -> (file, content type) for one page; the page's own files and the shared script."""
    out: dict[str, tuple[Path, str]] = {}
    for d in (PAGES_DIR / "shared", PAGES_DIR / key):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix in ASSET_TYPES:
                    out[f.name] = (f, ASSET_TYPES[f.suffix])
    return out


def _escape_json(obj) -> str:
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=True)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _trim(card: dict, meta: dict, name: str, version: str, checksum: str, text: int = 300) -> dict:
    c = {k: card[k] for k in _FALLBACK_KEEP_CARD if k in card}
    d = card.get("description")
    if isinstance(d, str):
        c["description"] = d if len(d) <= text else d[:text].rstrip() + "…"
    m = {k: meta[k] for k in _FALLBACK_KEEP_META if k in meta}
    return {"name": name, "version": version, "checksum": checksum, "metadata": m, "card": c}


class PageData:
    """Counts and a small record sample computed from the database, cached after the first call."""

    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.RLock()
        self._cache: dict[tuple, object] = {}

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        con.execute("PRAGMA query_only = ON")
        return con

    def _memo(self, key: tuple, build):
        with self._lock:
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]

    def stats(self, tenant: str) -> dict:
        return self._memo(("stats", tenant), lambda: self._stats(tenant))

    def fallback(self, tenant: str, host: str) -> dict:
        return self._memo(("fallback", tenant, host), lambda: self._fallback(tenant, host))

    def _has_kinds(self, con) -> bool:
        return kinds_mod.present(con)

    def _stats(self, tenant: str) -> dict:
        con = self._con()
        try:
            has = self._has_kinds(con)
            kcol = "kind" if has else "'skill'"
            totals = {k: 0 for k in kinds_mod.KINDS}
            for k, n in con.execute(f"SELECT {kcol}, COUNT(*) FROM skill_cards WHERE tenant_id = ? GROUP BY 1", (tenant,)):
                totals[k] = n
            verified = {k: 0 for k in kinds_mod.KINDS}
            defect = 0
            records = []
            rows = con.execute(
                f"SELECT c.{'kind' if has else 'name'}, c.name, c.version, c.card, s.metadata, s.checksum "
                "FROM skill_cards c JOIN skills s ON s.tenant_id = c.tenant_id AND s.name = c.name "
                "AND s.version = c.version WHERE c.tenant_id = ? AND c.verified = 1 AND s.yanked_at IS NULL "
                "ORDER BY c.seq", (tenant,)).fetchall()
            for kind, name, version, card, meta, checksum in rows:
                kind = kind if has else "skill"
                m = json.loads(meta)
                if m.get("quarantined"):
                    defect += 1
                    continue
                verified[kind] += 1
                records.append(_trim(json.loads(card), m, name, version, checksum))
            tiers: dict[str, int] = {}
            flags: dict[str, dict[str, int]] = {}
            creds: dict[str, dict[str, int]] = {}
            if has:
                for (t, n) in con.execute(
                        "SELECT json_extract(card, '$.trust_tier'), COUNT(*) FROM skill_cards "
                        "WHERE tenant_id = ? AND kind = 'plugin' GROUP BY 1", (tenant,)):
                    if t:
                        tiers[t] = n
                for kind in ("plugin", "connector"):
                    f: dict[str, int] = {}
                    c: dict[str, int] = {}
                    for (card,) in con.execute(
                            "SELECT card FROM skill_cards WHERE tenant_id = ? AND kind = ?", (tenant, kind)):
                        d = json.loads(card)
                        for flag in d.get("risk_flags") or []:
                            f[flag] = f.get(flag, 0) + 1
                        need = d.get("credentials_needed")
                        if need:
                            c[str(need)] = c.get(str(need), 0) + 1
                    flags[kind], creds[kind] = f, c
            licence = {k: 0 for k in kinds_mod.KINDS}
            sources: dict[str, list] = {k: [] for k in kinds_mod.KINDS}
            for k, n in con.execute(
                    f"SELECT {kcol}, COUNT(*) FROM skill_cards WHERE tenant_id = ? "
                    "AND IFNULL(json_extract(card, '$.license'), '') != '' GROUP BY 1", (tenant,)):
                licence[k] = n
            for k, s, n in con.execute(
                    f"SELECT {kcol}, json_extract(card, '$.source'), COUNT(*) FROM skill_cards "
                    "WHERE tenant_id = ? GROUP BY 1, 2 ORDER BY 3 DESC", (tenant,)):
                sources[k].append([s or "unknown", n])
            derived = con.execute(
                f"SELECT COUNT(*) FROM skill_cards WHERE tenant_id = ? AND {kcol} = 'skill' "
                "AND json_extract(card, '$.category_source') = 'derived'", (tenant,)).fetchone()[0]
            withdrawn = con.execute(
                "SELECT COUNT(*) FROM skills WHERE tenant_id = ? AND json_extract(metadata, '$.upstream_status') = 'withdrawn' "
                "AND yanked_at IS NULL", (tenant,)).fetchone()[0]
            meta_row = con.execute("SELECT value FROM import_meta WHERE key LIKE 'merge:%:last' ORDER BY key").fetchall() \
                if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'import_meta'").fetchone() else []
            snapshot = ""
            for (v,) in meta_row:
                try:
                    snapshot = max(snapshot, json.loads(v).get("at", "")[:10])
                except (ValueError, AttributeError):
                    pass
            return {"totals": totals, "verified": verified, "defect": defect, "tiers": tiers, "flags": flags,
                    "credentials": creds, "licence": licence, "sources": sources, "derived": derived,
                    "withdrawn": withdrawn, "snapshot": snapshot, "verified_records": records}
        finally:
            con.close()

    def _fallback(self, tenant: str, host: str) -> dict:
        stats = self.stats(tenant)
        con = self._con()
        try:
            has = self._has_kinds(con)
            cats: dict[str, list] = {k: [] for k in kinds_mod.KINDS}
            kcol = "kind" if has else "'skill'"
            for k, c, label, n in con.execute(
                    f"SELECT {kcol}, category, label, count FROM categories WHERE tenant_id = ? ORDER BY ord", (tenant,)):
                cats[k].append({"category": c, "label": label, "count": n})
            sample: dict[str, list] = {k: [] for k in kinds_mod.KINDS}

            def pull(where: str, args: list, kind: str, limit: int = -1) -> None:
                for name, version, card, meta, checksum in con.execute(
                        "SELECT c.name, c.version, c.card, s.metadata, s.checksum FROM skill_cards c JOIN skills s "
                        "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version "
                        f"WHERE c.tenant_id = ? AND s.yanked_at IS NULL AND {where} ORDER BY c.seq LIMIT ?", [tenant] + args + [limit]):
                    sample[kind].append(_trim(json.loads(card), json.loads(meta), name, version, checksum))

            if has:
                pull("c.kind = 'connector'", [], "connector")
                pull("c.kind = 'plugin' AND json_extract(c.card, '$.trust_tier') IN ('Official', 'Certified')", [], "plugin")
                pull("c.kind = 'plugin' AND json_extract(c.card, '$.trust_tier') = 'Community' "
                     "AND c.seq % 400 = 0", [], "plugin", _SAMPLE_PLUGINS_COMMUNITY)
                pull("c.kind = 'skill' AND c.verified = 0 AND c.seq % ? = 0",
                     [max(1, stats["totals"]["skill"] // _SAMPLE_SKILLS)], "skill", _SAMPLE_SKILLS)
            else:
                pull("c.verified = 0 AND c.seq % ? = 0",
                     [max(1, stats["totals"]["skill"] // _SAMPLE_SKILLS)], "skill", _SAMPLE_SKILLS)
            base = "https://" + host
            blob = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "kinds": [{"kind": k, "label": kinds_mod.LABELS[k], "count": stats["totals"][k]}
                              for k in kinds_mod.KINDS],
                    "categories": cats, "stats": {k: v for k, v in stats.items() if k != "verified_records"},
                    "verified": stats["verified_records"], "sample": sample}
            return json.loads(json.dumps(blob).replace("@@HOST@@", base))
        finally:
            con.close()


def render_page(key: str, data: PageData, tenant: str, host: str) -> str:
    html = (PAGES_DIR / key / "index.html").read_text(encoding="utf-8")
    try:
        blob = data.fallback(tenant, host)
    except sqlite3.Error:
        blob = {}  # a plain registry database has no serving tables: the page then relies on the live calls alone
    block = '<script type="application/json" id="hub-fallback">' + _escape_json(blob) + "</script>"
    return html.replace(PLACEHOLDER, block)
