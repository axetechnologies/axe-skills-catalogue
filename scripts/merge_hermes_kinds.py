#!/usr/bin/env python3
"""Merge Hermes plugins and connectors into a copy of a served hub database (read-only input).

    python3 scripts/merge_hermes_kinds.py --db COPY --input plugins-normalized.json \
        [--input connectors-normalized.json] [--report FILE] [--dry-run]

The companion of scripts/merge_hermes.py for the two kinds that are not skills. Each input is a JSON list (or
an object holding one) of normalised records: kind (plugin | connector), name, display_name, source, author,
category, description, version, licence, homepage, install, trust_tier, disclosure, permissions, env_vars,
platforms, raw; and, where the export has them, publisher, licence_source, repo, repo_pin, credentials_needed,
risk_flags, stars and updated_at.

- The database gets the kind columns first if it lacks them (hub/kinds.py); its skills are not rewritten.
- A record is keyed by kind, source and name: <kind>__axehub:<source>__<name>. Records sharing a key collapse
  to the richest; the count is reported.
- Everything lands in community-quarantine, quarantined and unverified, whatever trust tier upstream gives it:
  the tier, licence, author, permissions, env vars and disclosure text are carried on the card and in the
  metadata for review, not acted on.
- The body is the whole record as sorted JSON and its sha256 the checksum. A new key lands at 1.0.0; a changed
  body gets the next version and the card moves to it; an unchanged one is left alone.
- A key of a kind this run brought that upstream no longer lists is kept and marked upstream_status
  "withdrawn"; the mark is cleared if it comes back unchanged.
- Order (seq, kind by kind with skills first), the category facets per kind and an import_meta record are
  rebuilt; nothing is deleted. The report proves the skills' rows, order and facets are unchanged.

A second run over the same input adds nothing. Record text is stored as data and never executed. Live
databases are refused by name and by identity.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_hermes as mh  # noqa: E402
from hub import kinds  # noqa: E402
from hub.community import _bump  # noqa: E402

TENANT = mh.TENANT
HOST_TOKEN = mh.HOST_TOKEN
DEFAULT_ACTOR = "hermes-kinds-merge-20261124"
MERGE_KINDS = ("plugin", "connector")
LIVE_PATHS = (Path.home() / ".axe" / "hub" / "barracks.db",)
# Normalised field, then the spellings other exports use for it.
ALIASES = {
    "display_name": ("display_name", "displayName", "title"),
    "licence": ("licence", "license"),
    "trust_tier": ("trust_tier", "trustTier", "trust", "tier"),
    "env_vars": ("env_vars", "envVars"),
    "homepage": ("homepage", "url", "docs_url", "docsUrl"),
    "install": ("install", "install_cmd", "installCmd"),
    "version": ("version", "upstream_version"),
}


def field(rec: dict, key: str):
    for k in ALIASES.get(key, (key,)):
        v = rec.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def text(rec: dict, key: str) -> str:
    v = field(rec, key)
    return v.strip() if isinstance(v, str) else ""


def slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")


def entry_name(kind: str, source: str, name: str) -> str:
    return f"{kind}__axehub:{source}__" + name.replace("/", "__").replace(" ", "_")


def richness(rec: dict) -> tuple:
    filled = sum(1 for v in rec.values() if v not in (None, "", [], {}, False))
    return (-len(text(rec, "description")), -filled, json.dumps(rec, sort_keys=True))


def refuse(db: Path) -> str | None:
    why = mh.refuse(db)
    if why:
        return why
    live = list(LIVE_PATHS)
    if os.environ.get("AXE_HUB_DB"):
        live.append(Path(os.environ["AXE_HUB_DB"]).expanduser())
    for p in live:
        if p.exists() and os.path.samefile(p, db):
            return f"refusing to write {db}: it is the live database {p}"
    return None


def load(path: Path) -> list:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        for key in ("items", "records", "data", "plugins", "connectors"):
            if isinstance(data.get(key), list):
                return data[key]
        raise ValueError(f"{path}: no list of records in it")
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of records")
    return data


# (record field, card key), in card order. install is the upstream command; the card's own install is ours.
CARRIED = (("author", "author"), ("publisher", "publisher"), ("licence", "license"),
           ("licence_source", "license_source"), ("homepage", "homepage"), ("repo", "repo"),
           ("repo_pin", "repo_pin"), ("version", "upstream_version"), ("trust_tier", "trust_tier"),
           ("disclosure", "disclosure"), ("risk_flags", "risk_flags"), ("credentials_needed", "credentials_needed"),
           ("permissions", "permissions"), ("env_vars", "env_vars"), ("platforms", "platforms"),
           ("stars", "stars"), ("updated_at", "upstream_updated_at"), ("install", "upstream_install"))
# Card keys repeated in the metadata, which list rows carry and search reads.
META_KEYS = ("author", "publisher", "license", "upstream_version", "trust_tier", "disclosure", "risk_flags",
             "credentials_needed", "permissions", "env_vars", "platforms")


def card_of(name: str, kind: str, rec: dict) -> dict:
    """The rich build's card shape: keys only when non-empty, install carrying @@HOST@@."""
    source = text(rec, "source")
    card: dict = {"title": text(rec, "display_name") or text(rec, "name"), "kind": kind,
                  "source": "axehub:" + source, "verified": False, "use_count": 0}
    if text(rec, "description"):
        card["description"] = text(rec, "description")
    if text(rec, "category"):
        cat = slug(text(rec, "category"))
        label = text(rec, "category")
        card.update(category=cat, category_label=label if label != cat else mh.label_of(cat),
                    category_source="upstream")
    for key, out in CARRIED:
        v = field(rec, key)
        if v is not None:
            card[out] = v.strip() if isinstance(v, str) else v
    card["install"] = f"curl -s {HOST_TOKEN}/v1/skills/" + quote(name, safe="")
    return card


def meta_of(kind: str, rec: dict, card: dict, now: str) -> dict:
    meta = {"kind": kind, "source": card["source"], "external_id": f"{text(rec, 'source')}/{text(rec, 'name')}",
            "homepage": card.get("homepage", ""), "verified": False, "use_count": 0, "federated_at": now,
            "quarantined": True}
    for key in META_KEYS:
        if key in card:
            meta[key] = card[key]
    return meta


def skills_digest(con: sqlite3.Connection) -> dict:
    """What a skills-only client is served: its rows, their order and its facets, as hashes."""
    rows, facets = hashlib.sha256(), hashlib.sha256()
    only = " AND c.kind = 'skill'" if kinds.present(con) else ""
    n = 0
    for r in con.execute(
            "SELECT c.seq, c.name, c.version, c.card, c.category, c.verified, s.checksum, s.metadata"
            " FROM skill_cards c JOIN skills s ON s.tenant_id = c.tenant_id AND s.name = c.name"
            " AND s.version = c.version WHERE c.tenant_id = ?" + only + " ORDER BY c.seq", (TENANT,)):
        rows.update(json.dumps(r).encode())
        n += 1
    for r in con.execute("SELECT ord, category, label, count FROM categories c WHERE tenant_id = ?" + only
                         + " ORDER BY ord", (TENANT,)):
        facets.update(json.dumps(r).encode())
    return {"skills": n, "rows_sha256": rows.hexdigest(), "categories_sha256": facets.hexdigest()}


def merge(db: Path, inputs: list[Path], actor: str = DEFAULT_ACTOR, dry_run: bool = False,
          now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat()
    report: dict = {"db": str(db), "inputs": [{"path": str(p), "sha256": mh.sha256_file(p)} for p in inputs],
                    "actor": actor, "dry_run": dry_run}
    skipped = collections.Counter()
    groups: dict[str, list[tuple[str, dict]]] = collections.defaultdict(list)
    brought: set = set()
    rows_in = 0
    for p in inputs:
        for rec in load(p):
            rows_in += 1
            if not isinstance(rec, dict):
                skipped["not an object"] += 1
                continue
            kind = text(rec, "kind").lower()
            if kind not in MERGE_KINDS:
                skipped[f"kind not one of {', '.join(MERGE_KINDS)}"] += 1
                continue
            if not text(rec, "name") or not text(rec, "source"):
                skipped["no name or source"] += 1
                continue
            brought.add(kind)
            groups[entry_name(kind, text(rec, "source"), text(rec, "name"))].append((kind, rec))
    report["input_rows"] = rows_in

    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    had_kinds = kinds.present(con)
    report["skills_before"] = skills_digest(con)
    existing: dict = {}
    if had_kinds:
        for name, kind, version, card, fmt, checksum, meta in con.execute(
                "SELECT c.name, c.kind, c.version, c.card, s.format, s.checksum, s.metadata FROM skill_cards c"
                " JOIN skills s ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version"
                " WHERE c.tenant_id = ? AND c.kind != 'skill'", (TENANT,)):
            existing[name] = {"kind": kind, "version": version, "card": json.loads(card), "format": fmt,
                              "checksum": checksum, "meta": json.loads(meta)}
    held = {n for (n,) in con.execute("SELECT DISTINCT name FROM skills WHERE tenant_id = ?", (TENANT,))}
    report["before_by_kind"] = dict(collections.Counter(v["kind"] for v in existing.values()))

    added, updated, unchanged = collections.Counter(), collections.Counter(), collections.Counter()
    collapsed = collections.Counter()
    new_labels: dict = {}
    returned = 0
    seen: set = set()
    with con:
        if not dry_run:
            report["migrated"] = kinds.up(con)
        next_seq = con.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM skill_cards WHERE tenant_id = ?",
                               (TENANT,)).fetchone()[0]
        for name in sorted(groups, key=str.encode):
            group = sorted(groups[name], key=lambda kr: richness(kr[1]))
            kind, rec = group[0]
            collapsed[kind] += len(group) - 1
            have = existing.get(name)
            if have is None and name in held:
                skipped["name held by a row of another kind"] += 1
                continue
            seen.add(name)
            content = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            checksum = hashlib.sha256(content.encode()).hexdigest()
            if have and have["checksum"] == checksum:
                unchanged[kind] += 1
                if "upstream_status" in have["meta"]:
                    returned += 1
                    if not dry_run:
                        mh.set_meta(con, name, have["version"], {k: v for k, v in have["meta"].items()
                                                                 if k not in ("upstream_status", "withdrawn_seen_at")})
                continue
            card = card_of(name, kind, rec)
            meta = meta_of(kind, rec, card, now)
            if card.get("category"):
                new_labels[(kind, card["category"])] = card["category_label"]
            if have:
                versions = [v for (v,) in con.execute(
                    "SELECT version FROM skill_versions WHERE tenant_id = ? AND name = ? ORDER BY ord",
                    (TENANT, name))] or [have["version"]]
                version = _bump(versions[-1])
                while version in versions:
                    version = _bump(version)
                updated[kind] += 1
            else:
                version, versions = "1.0.0", []
                added[kind] += 1
            if dry_run:
                continue
            con.execute(
                "INSERT INTO skills (tenant_id, name, version, format, content, checksum, metadata,"
                " created_by, created_at, yanked_at) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (TENANT, name, version, "catalog", content, checksum, json.dumps(meta), actor, now))
            con.execute("INSERT INTO skill_versions (tenant_id, name, ord, version) VALUES (?,?,?,?)",
                        (TENANT, name, len(versions), version))
            category = card.get("category") or "other"
            if have:
                con.execute("UPDATE skill_cards SET version = ?, card = ?, category = ?, verified = 0"
                            " WHERE tenant_id = ? AND name = ?", (version, json.dumps(card), category, TENANT, name))
            else:
                con.execute("INSERT INTO skill_cards (tenant_id, name, version, seq, card, category, verified, kind)"
                            " VALUES (?,?,?,?,?,?,0,?)", (TENANT, name, version, next_seq, json.dumps(card),
                                                          category, kind))
                next_seq += 1

        # Only the kinds this run brought can be judged withdrawn: a plugins-only run says nothing of connectors.
        withdrawn, newly_withdrawn = collections.Counter(), 0
        for name, have in existing.items():
            if name in seen or have["kind"] not in brought or not have["meta"].get("source", "").startswith("axehub:"):
                continue
            withdrawn[have["kind"]] += 1
            if have["meta"].get("upstream_status") != "withdrawn":
                newly_withdrawn += 1
                if not dry_run:
                    mh.set_meta(con, name, have["version"],
                                {**have["meta"], "upstream_status": "withdrawn", "withdrawn_seen_at": now})

        changed = bool(added or updated or newly_withdrawn or returned)
        if not dry_run and (changed or report.get("migrated")):
            mh.resequence(con)
            mh.rebuild_categories(con, new_labels, recount=MERGE_KINDS)
        if not dry_run:
            sha = hashlib.sha256("".join(i["sha256"] for i in report["inputs"]).encode()).hexdigest()
            by_kind = dict(con.execute("SELECT kind, COUNT(*) FROM skill_cards WHERE tenant_id = ? GROUP BY kind",
                                       (TENANT,)))
            record = {"at": now, "actor": actor, "inputs": report["inputs"], "input_rows": rows_in,
                      "added": sum(added.values()), "updated": sum(updated.values()),
                      "unchanged": sum(unchanged.values()), "withdrawn_upstream": sum(withdrawn.values()),
                      "by_kind": by_kind}
            key = "merge:hermes-kinds:" + sha[:16]
            if changed or not con.execute("SELECT 1 FROM import_meta WHERE key = ?", (key,)).fetchone():
                con.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES (?, ?)",
                            (key, json.dumps(record, sort_keys=True)))
            con.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES ('merge:hermes-kinds:last', ?)",
                        (json.dumps(record, sort_keys=True),))
    if not dry_run and changed:
        con.execute("ANALYZE")
        con.commit()

    report.update({
        "had_kinds": had_kinds,
        "added": sum(added.values()), "updated": sum(updated.values()), "unchanged": sum(unchanged.values()),
        "added_by_kind": dict(added), "updated_by_kind": dict(updated), "unchanged_by_kind": dict(unchanged),
        "collapsed_same_key": dict(collapsed),
        "skipped": sum(skipped.values()), "skipped_reasons": {k: v for k, v in skipped.items() if v},
        "withdrawn_upstream": sum(withdrawn.values()), "withdrawn_newly_marked": newly_withdrawn,
        "withdrawn_flag_cleared": returned,
    })
    if not dry_run:
        report["skills_after"] = skills_digest(con)
        report["skills_untouched"] = report["skills_after"] == report["skills_before"]
        report["checks"] = mh.check(con)
        report["checks"]["non_skill_not_quarantined"] = con.execute(
            "SELECT COUNT(*) FROM skill_cards c JOIN skills s ON s.tenant_id = c.tenant_id AND s.name = c.name"
            " AND s.version = c.version WHERE c.tenant_id = ? AND c.kind != 'skill'"
            " AND (json_extract(s.metadata, '$.quarantined') IS NOT 1 OR c.verified != 0)", (TENANT,)).fetchone()[0]
        report["checks"]["ok"] = (report["checks"]["ok"] and report["skills_untouched"]
                                  and report["checks"]["non_skill_not_quarantined"] == 0)
    con.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True, help="a copy of the served database; written in place")
    ap.add_argument("--input", type=Path, action="append", required=True,
                    help="normalised plugins or connectors JSON; repeat for more than one")
    ap.add_argument("--actor", default=DEFAULT_ACTOR, help="created_by for the rows this run writes")
    ap.add_argument("--dry-run", action="store_true", help="count only; write nothing")
    ap.add_argument("--report", type=Path, help="write the full report here as JSON")
    args = ap.parse_args()

    db = args.db.expanduser()
    why = refuse(db)
    if why:
        print(why, file=sys.stderr)
        return 2
    report = merge(db, [p.expanduser() for p in args.input], actor=args.actor, dry_run=args.dry_run)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if args.dry_run or report["checks"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
