#!/usr/bin/env python3
"""Merge a Hermes Agent catalogue export into a copy of a served hub database (read-only input).

    python3 scripts/merge_hermes.py --db COPY --hermes hermes-skills.json [--report FILE] [--dry-run]

The database must be one built by scripts/import_snapshot.py (it has skill_cards). Rows are built the way
the existing community rows were: HermesCatalog reads the records, hub.community._taxonomy lifts the
classification, the body is the federate() descriptor and its sha256 is the checksum, and the card has the
shape the rich build served (keys present only when non-empty, install carrying @@HOST@@).

- A name not in the database is added at 1.0.0 in community-quarantine, quarantined.
- A name whose body changed upstream gets the next version (hub.community._bump); its card moves to it.
  A category the rich build derived is kept when upstream still gives none.
- source/name is not a key upstream: different skills share it (browse.sh `search-listings` on nine
  sites). installIdentifier is unique, so a collision keeps the plain name for one record (the one the
  database already holds, else the one with the richest description) and names the others by their
  installIdentifier. Records sharing one installIdentifier collapse to the richest.
- A federated name upstream no longer lists is kept and marked in its metadata (upstream_status
  "withdrawn", withdrawn_seen_at); the mark is cleared if the name comes back unchanged.
- Category facets, list order (seq) and an import_meta record are rebuilt; nothing is deleted.
- On a database that also holds plugins and connectors (hub/kinds.py) only the skills are read, compared and
  marked; their order and facets are rebuilt within the kind.

A second run over the same input adds nothing. Record text is stored as data and never executed. The
live database is refused by name.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from axeskills_hermes_catalog import HermesCatalog  # noqa: E402
from hub import kinds  # noqa: E402
from hub.community import CommunityEntry, _bump, _taxonomy  # noqa: E402

TENANT = "community-quarantine"
HOST_TOKEN = "@@HOST@@"
LIVE_NAMES = {"barracks.db", "hub.db", "hub-v2.db", "skills-catalogue.db"}
DEFAULT_ACTOR = "hermes-merge-20261124"
NO_UPSTREAM_CATEGORY = {"other", "uncategorized"}
CARD_TAGS = 8


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upstream(entry: CommunityEntry) -> str:
    return entry.source.split(":", 1)[1]


def skill_name(source: str, external_id: str) -> str:
    return f"community__axehub:{source}__" + external_id.replace("/", "__").replace(" ", "_")


def content_of(entry: CommunityEntry, external_id: str, taxonomy: dict) -> str:
    return json.dumps({
        "description": entry.description,
        "external_id": external_id,
        "homepage": entry.homepage,
        "name": entry.name,
        "source": entry.source,
        "taxonomy": taxonomy,
        "use_count": entry.use_count,
        "verified": entry.verified,
    }, sort_keys=True)


def card_of(name: str, entry: CommunityEntry, taxonomy: dict, prior: dict | None) -> dict:
    card: dict = {"title": entry.name, "source": "axehub:" + upstream(entry), "verified": entry.verified,
                  "use_count": entry.use_count}
    if entry.description:
        card["description"] = entry.description
    cat = taxonomy.get("category")
    if cat and cat not in NO_UPSTREAM_CATEGORY:
        label = taxonomy.get("category_label")
        card.update(category=cat, category_label=label if label and label != cat else label_of(cat),
                    category_source="upstream")
    elif prior and prior.get("category_source") == "derived":
        card.update(category=prior["category"], category_label=prior["category_label"],
                    category_source="derived")
    for k in ("author", "license"):
        if taxonomy.get(k):
            card[k] = taxonomy[k]
    if entry.homepage:
        card["homepage"] = entry.homepage
    if taxonomy.get("tags"):
        card["tags"] = taxonomy["tags"][:CARD_TAGS]
    card["install"] = f"curl -s {HOST_TOKEN}/v1/skills/" + quote(name, safe="")
    return card


def label_of(category: str) -> str:
    return category.replace("-", " ").title()


def richness(entry: CommunityEntry) -> tuple:
    filled = sum(1 for v in entry.raw.values() if v not in (None, "", [], {}, False))
    return (-len(entry.description), -filled, entry.raw.get("installIdentifier") or "")


def refuse(db: Path) -> str | None:
    if not db.exists():
        return f"{db} does not exist; make the copy first (sqlite3 LIVE \".backup COPY\")"
    if db.name in LIVE_NAMES or db.resolve().name in LIVE_NAMES:
        return f"refusing to write {db}: that is a live database name"
    return None


def plan(entries: list[CommunityEntry], existing: dict) -> tuple[list[tuple], dict]:
    """Decide the skill name of every record: [(name, external_id, entry)] and the collapse counts."""
    by_ident: dict[tuple, list[CommunityEntry]] = collections.defaultdict(list)
    for e in entries:
        ident = e.raw.get("installIdentifier") or ""
        by_ident[(upstream(e), ident) if ident else (upstream(e), "", e.external_id)].append(e)
    collapsed = collections.Counter()
    unique: list[CommunityEntry] = []
    for key, group in by_ident.items():
        group.sort(key=richness)
        unique.append(group[0])
        if len(group) > 1:
            collapsed[key[0]] += len(group) - 1

    by_name: dict[str, list[CommunityEntry]] = collections.defaultdict(list)
    for e in unique:
        by_name[skill_name(upstream(e), e.external_id)].append(e)

    out: list[tuple] = []
    recovered = collections.Counter()
    unqualified = collections.Counter()
    for name in sorted(by_name, key=str.encode):
        group = sorted(by_name[name], key=richness)
        primary = group[0]
        if len(group) > 1 and name in existing:
            have = existing[name]["checksum"]
            for e in group:
                if hashlib.sha256(content_of(e, e.external_id, _taxonomy(e)).encode()).hexdigest() == have:
                    primary = e
                    break
        out.append((name, primary.external_id, primary))
        for e in group:
            if e is primary:
                continue
            ident = e.raw.get("installIdentifier") or ""
            if not ident:
                unqualified[upstream(e)] += 1
                continue
            ext = f"{upstream(e)}/{ident}"
            out.append((skill_name(upstream(e), ext), ext, e))
            recovered[upstream(e)] += 1
    return out, {"collapsed_same_install_identifier": dict(collapsed),
                 "recovered_by_install_identifier": dict(recovered),
                 "dropped_collision_without_install_identifier": dict(unqualified)}


def merge(db: Path, hermes: Path, actor: str = DEFAULT_ACTOR, dry_run: bool = False,
          now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat()
    raw_rows = json.loads(hermes.read_text())
    entries = list(HermesCatalog(skills_url=str(hermes)).fetch())
    report: dict = {"db": str(db), "hermes": str(hermes), "hermes_sha256": sha256_file(hermes),
                    "hermes_rows": len(raw_rows), "actor": actor, "dry_run": dry_run}
    skipped = collections.Counter()
    skipped["not an object or no name"] = len(raw_rows) - len(entries)

    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    existing = {}
    only_skills = " AND c.kind = 'skill'" if kinds.present(con) else ""
    for name, version, card, fmt, checksum, meta in con.execute(
            "SELECT c.name, c.version, c.card, s.format, s.checksum, s.metadata FROM skill_cards c JOIN skills s "
            "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version WHERE c.tenant_id = ?"
            + only_skills, (TENANT,)):
        existing[name] = {"version": version, "card": json.loads(card), "format": fmt, "checksum": checksum,
                          "meta": json.loads(meta)}
    report["before_skills"] = len(existing)
    report["before_verified_and_quarantined"] = con.execute(
        "SELECT COUNT(*) FROM skills s JOIN skill_cards c ON s.tenant_id = c.tenant_id AND s.name = c.name "
        "AND s.version = c.version WHERE c.verified = 1 AND json_extract(s.metadata, '$.quarantined') = 1"
    ).fetchone()[0]

    planned, report["dedup"] = plan(entries, existing)
    seen: set = set()
    added, updated, unchanged = collections.Counter(), collections.Counter(), collections.Counter()
    licence_filled = collections.Counter()
    returned = 0
    next_seq = con.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM skill_cards WHERE tenant_id = ?",
                           (TENANT,)).fetchone()[0]
    with con:
        for name, external_id, e in planned:
            src = upstream(e)
            if name in seen:
                skipped["qualified name collides with another record"] += 1
                continue
            seen.add(name)
            taxonomy = _taxonomy(e)
            content = content_of(e, external_id, taxonomy)
            checksum = hashlib.sha256(content.encode()).hexdigest()
            have = existing.get(name)
            if have and have["format"] != "catalog":
                skipped["name held by a non-catalog row"] += 1
                continue
            if have and have["checksum"] == checksum:
                unchanged[src] += 1
                if "upstream_status" in have["meta"]:
                    returned += 1
                    if not dry_run:
                        meta = {k: v for k, v in have["meta"].items()
                                if k not in ("upstream_status", "withdrawn_seen_at")}
                        set_meta(con, name, have["version"], meta)
                continue
            meta = {"source": "axehub:" + src, "external_id": external_id, "homepage": e.homepage,
                    "verified": e.verified, "use_count": e.use_count, "federated_at": now,
                    "quarantined": True, "taxonomy": taxonomy}
            card = card_of(name, e, taxonomy, have["card"] if have else None)
            if have:
                versions = [v for (v,) in con.execute(
                    "SELECT version FROM skill_versions WHERE tenant_id = ? AND name = ? ORDER BY ord",
                    (TENANT, name))] or [have["version"]]
                version = _bump(versions[-1])
                while version in versions:
                    version = _bump(version)
                updated[src] += 1
                if card.get("license") and not have["card"].get("license"):
                    licence_filled[src] += 1
            else:
                version = "1.0.0"
                versions = []
                added[src] += 1
            if dry_run:
                continue
            con.execute(
                "INSERT INTO skills (tenant_id, name, version, format, content, checksum, metadata,"
                " created_by, created_at, yanked_at) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                (TENANT, name, version, "catalog", content, checksum, json.dumps(meta), actor, now))
            con.execute("INSERT INTO skill_versions (tenant_id, name, ord, version) VALUES (?,?,?,?)",
                        (TENANT, name, len(versions), version))
            category = card.get("category") or "other"
            verified = 1 if e.verified else 0
            if have:
                con.execute("UPDATE skill_cards SET version = ?, card = ?, category = ?, verified = ?"
                            " WHERE tenant_id = ? AND name = ?",
                            (version, json.dumps(card), category, verified, TENANT, name))
            else:
                con.execute("INSERT INTO skill_cards (tenant_id, name, version, seq, card, category, verified)"
                            " VALUES (?,?,?,?,?,?,?)",
                            (TENANT, name, version, next_seq, json.dumps(card), category, verified))
                next_seq += 1

        # A federated row upstream no longer lists is kept and marked, never deleted: some are takedowns,
        # some renames, and the page decides what to show.
        withdrawn, newly_withdrawn = collections.Counter(), 0
        for name, have in existing.items():
            src = have["meta"].get("source", "")
            if name in seen or not src.startswith("axehub:"):
                continue
            withdrawn[src] += 1
            if have["meta"].get("upstream_status") != "withdrawn":
                newly_withdrawn += 1
                if not dry_run:
                    set_meta(con, name, have["version"],
                             {**have["meta"], "upstream_status": "withdrawn", "withdrawn_seen_at": now})

        if not dry_run:
            resequence(con)
            rebuild_categories(con)
            total = con.execute("SELECT COUNT(*) FROM skill_cards c WHERE tenant_id = ?" + only_skills,
                                (TENANT,)).fetchone()[0]
            record = {"at": now, "actor": actor, "hermes": str(hermes), "hermes_sha256": report["hermes_sha256"],
                      "hermes_rows": len(raw_rows), "added": sum(added.values()),
                      "updated": sum(updated.values()), "unchanged": sum(unchanged.values()), "skills": total}
            key = "merge:hermes:" + report["hermes_sha256"][:16]
            record["withdrawn_upstream"] = sum(withdrawn.values())
            if added or updated or not con.execute("SELECT 1 FROM import_meta WHERE key = ?", (key,)).fetchone():
                con.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES (?, ?)",
                            (key, json.dumps(record, sort_keys=True)))
            con.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES ('merge:hermes:last', ?)",
                        (json.dumps(record, sort_keys=True),))
    if not dry_run and (added or updated or newly_withdrawn or returned):
        con.execute("ANALYZE")
        con.commit()

    report.update({
        "added": sum(added.values()), "updated": sum(updated.values()), "unchanged": sum(unchanged.values()),
        "skipped": sum(skipped.values()), "skipped_reasons": {k: v for k, v in skipped.items() if v},
        "added_by_source": dict(added.most_common()), "updated_by_source": dict(updated.most_common()),
        "unchanged_by_source": dict(unchanged.most_common()),
        "withdrawn_upstream": sum(withdrawn.values()), "withdrawn_newly_marked": newly_withdrawn,
        "withdrawn_by_source": dict(withdrawn.most_common()), "withdrawn_flag_cleared": returned,
        "licence_blank_to_filled": sum(licence_filled.values()),
        "licence_blank_to_filled_by_source": dict(licence_filled.most_common()),
        "new_rows_with_licence": None,
    })
    if not dry_run:
        report["new_rows_with_licence"] = con.execute(
            "SELECT COUNT(*) FROM skill_cards WHERE tenant_id = ? AND json_extract(card, '$.license') IS NOT NULL"
            " AND name IN (SELECT name FROM skills WHERE tenant_id = ? AND created_by = ? AND version = '1.0.0')",
            (TENANT, TENANT, actor)).fetchone()[0]
        report["checks"] = check(con)
    con.close()
    return report


def set_meta(con: sqlite3.Connection, name: str, version: str, meta: dict) -> None:
    con.execute("UPDATE skills SET metadata = ? WHERE tenant_id = ? AND name = ? AND version = ?",
                (json.dumps(meta), TENANT, name, version))


def resequence(con: sqlite3.Connection) -> None:
    """seq is the position in binary name order: list pages are seq ranges and search indexes by seq.

    Where the database has kinds, each kind is one range in kinds.KINDS order, so skills come first.
    """
    if kinds.present(con):
        rows = con.execute("SELECT kind, name FROM skill_cards WHERE tenant_id = ?", (TENANT,)).fetchall()
        names = [n for _, n in sorted(rows, key=lambda r: (kinds.rank(r[0]), r[1].encode()))]
    else:
        names = sorted((n for (n,) in con.execute("SELECT name FROM skill_cards WHERE tenant_id = ?", (TENANT,))),
                       key=str.encode)
    con.execute("UPDATE skill_cards SET seq = -1 - seq WHERE tenant_id = ?", (TENANT,))
    con.executemany("UPDATE skill_cards SET seq = ? WHERE tenant_id = ? AND name = ?",
                    ((i, TENANT, n) for i, n in enumerate(names)))


def rebuild_categories(con: sqlite3.Connection, new_labels: dict | None = None,
                       recount: tuple[str, ...] = kinds.KINDS) -> None:
    """Counts from the cards; a stored label is kept, a new category gets the stored labels' form.

    Where the database has kinds, facets are per kind and ordered kind by kind (skills first). Only the kinds
    in recount are counted again; the others keep their stored rows and order, so a plugin merge cannot move
    a skill facet. new_labels ({(kind, category): label}) names categories not stored yet.
    """
    if not kinds.present(con):
        labels = dict(con.execute("SELECT category, label FROM categories WHERE tenant_id = ?", (TENANT,)))
        counts = con.execute("SELECT category, COUNT(*) FROM skill_cards WHERE tenant_id = ? GROUP BY category",
                             (TENANT,)).fetchall()
        counts.sort(key=lambda r: (r[1], r[0]), reverse=True)
        con.execute("DELETE FROM categories WHERE tenant_id = ?", (TENANT,))
        con.executemany("INSERT INTO categories (tenant_id, ord, category, label, count) VALUES (?,?,?,?,?)",
                        ((TENANT, i, c, labels.get(c) or label_of(c), n) for i, (c, n) in enumerate(counts)))
        return
    stored = con.execute("SELECT kind, category, label, count FROM categories WHERE tenant_id = ? ORDER BY ord",
                         (TENANT,)).fetchall()
    labels = {(k, c): lbl for k, c, lbl, _ in stored}
    marks = ",".join("?" * len(recount))
    counts = con.execute(f"SELECT kind, category, COUNT(*) FROM skill_cards WHERE tenant_id = ? AND kind IN ({marks})"
                         " GROUP BY kind, category", (TENANT, *recount)).fetchall()
    counts.sort(key=lambda r: (r[2], r[1]), reverse=True)
    rows = [r for r in stored if r[0] not in recount] + [
        (k, c, labels.get((k, c)) or (new_labels or {}).get((k, c)) or label_of(c), n) for k, c, n in counts]
    rows.sort(key=lambda r: kinds.rank(r[0]))
    con.execute("DELETE FROM categories WHERE tenant_id = ?", (TENANT,))
    con.executemany("INSERT INTO categories (tenant_id, ord, category, label, count, kind) VALUES (?,?,?,?,?,?)",
                    ((TENANT, i, c, lbl, n, k) for i, (k, c, lbl, n) in enumerate(rows)))


def check(con: sqlite3.Connection) -> dict:
    one = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
    cards = one("SELECT COUNT(*) FROM skill_cards WHERE tenant_id = ?", TENANT)
    out = {
        "integrity_check": one("PRAGMA integrity_check"),
        "skill_cards": cards,
        "distinct_skill_names": one("SELECT COUNT(DISTINCT name) FROM skills WHERE tenant_id = ?", TENANT),
        "skills_rows": one("SELECT COUNT(*) FROM skills WHERE tenant_id = ?", TENANT),
        "categories_sum": one("SELECT SUM(count) FROM categories WHERE tenant_id = ?", TENANT),
        "seq_contiguous": one("SELECT MIN(seq) = 0 AND MAX(seq) = COUNT(*) - 1 FROM skill_cards WHERE tenant_id = ?",
                              TENANT) == 1,
        "cards_without_skill_row": one(
            "SELECT COUNT(*) FROM skill_cards c LEFT JOIN skills s ON s.tenant_id = c.tenant_id AND s.name = c.name"
            " AND s.version = c.version WHERE c.tenant_id = ? AND s.name IS NULL", TENANT),
        "names_without_card": one(
            "SELECT COUNT(DISTINCT s.name) FROM skills s LEFT JOIN skill_cards c ON c.tenant_id = s.tenant_id"
            " AND c.name = s.name WHERE s.tenant_id = ? AND c.name IS NULL", TENANT),
        "card_version_not_latest": one(
            "SELECT COUNT(*) FROM skill_cards c JOIN skill_versions v ON v.tenant_id = c.tenant_id"
            " AND v.name = c.name WHERE c.tenant_id = ? AND v.ord = (SELECT MAX(ord) FROM skill_versions w"
            " WHERE w.tenant_id = c.tenant_id AND w.name = c.name) AND v.version != c.version", TENANT),
        "cards_without_versions": one(
            "SELECT COUNT(*) FROM skill_cards c WHERE c.tenant_id = ? AND NOT EXISTS (SELECT 1 FROM"
            " skill_versions v WHERE v.tenant_id = c.tenant_id AND v.name = c.name)", TENANT),
    }
    bad_sum = 0
    bad_install = 0
    for name, content, checksum, card in con.execute(
            "SELECT s.name, s.content, s.checksum, c.card FROM skills s JOIN skill_cards c"
            " ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version WHERE s.tenant_id = ?",
            (TENANT,)):
        if hashlib.sha256(content.encode()).hexdigest() != checksum:
            bad_sum += 1
        if json.loads(card).get("install") != f"curl -s {HOST_TOKEN}/v1/skills/" + quote(name, safe=""):
            bad_install += 1
    out["served_rows_checksum_mismatch"] = bad_sum
    out["served_rows_install_mismatch"] = bad_install
    kinds_ok = True
    if kinds.present(con):
        out["by_kind"] = {}
        for kind, n, lo, hi in con.execute("SELECT kind, COUNT(*), MIN(seq), MAX(seq) FROM skill_cards"
                                           " WHERE tenant_id = ? GROUP BY kind", (TENANT,)):
            facets = one("SELECT COALESCE(SUM(count), 0) FROM categories WHERE tenant_id = ? AND kind = ?",
                         TENANT, kind)
            out["by_kind"][kind] = {"cards": n, "categories_sum": facets, "seq_from": lo,
                                    "seq_contiguous": hi - lo + 1 == n}
            kinds_ok = kinds_ok and facets == n and hi - lo + 1 == n
        firsts = sorted((v["seq_from"], kinds.rank(k)) for k, v in out["by_kind"].items())
        out["kinds_in_order"] = [r for _, r in firsts] == sorted(r for _, r in firsts)
        kinds_ok = kinds_ok and out["kinds_in_order"]
    out["ok"] = (out["integrity_check"] == "ok" and out["categories_sum"] == cards == out["distinct_skill_names"]
                 and out["seq_contiguous"] and kinds_ok and not any(out[k] for k in (
                     "cards_without_skill_row", "names_without_card", "card_version_not_latest",
                     "cards_without_versions", "served_rows_checksum_mismatch")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True, help="a copy of the served database; written in place")
    ap.add_argument("--hermes", type=Path, required=True, help="Hermes skills.json export (a JSON list)")
    ap.add_argument("--actor", default=DEFAULT_ACTOR, help="created_by for the rows this run writes")
    ap.add_argument("--dry-run", action="store_true", help="count only; write nothing")
    ap.add_argument("--report", type=Path, help="write the full report here as JSON")
    args = ap.parse_args()

    db = args.db.expanduser()
    why = refuse(db)
    if why:
        print(why, file=sys.stderr)
        return 2
    report = merge(db, args.hermes.expanduser(), actor=args.actor, dry_run=args.dry_run)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if args.dry_run or report["checks"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
