#!/usr/bin/env python3
"""Build a hub database from a rich-build snapshot (read-only input, new output file).

    python3 scripts/import_snapshot.py [--snapshot DIR] [--out DB] [--force] [--report FILE]

Every list row of the snapshot becomes one row of the repo's own `skills` table with the values the
rich build reported (tenant, checksum, created_by, created_at, metadata). The card object, the stored
categories and the version histories go into the tables of hub/schema_serve.sql. Nothing is scanned,
re-classified or re-flagged: quarantined and verified are copied as the snapshot has them.

Content: the snapshot's list rows carry no body. Bodies are taken from details.jsonl where captured
(all 80 skillmd rows and the one plugin row). A catalog row's body is a JSON document that is a pure
function of its metadata and card; it is rebuilt from them and accepted only if its sha256 equals the
checksum the rich build reported, so a rebuilt body is proven, not assumed.

The output is built beside the target and renamed into place, and an existing target is refused
unless --force is given. The default target is never the live hub.db.
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
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.store import Registry  # noqa: E402

TENANT = "community-quarantine"
HOST_TOKEN = "@@HOST@@"
INSTALL_RE = re.compile(r"^curl -s https://[^/\s]+(/v1/skills/\S+)$")
DEFAULT_SNAPSHOT = Path.home() / ".axe" / "skills-hub-v2" / "snapshot"
DEFAULT_OUT = Path.home() / ".axe" / "hub" / "hub-v2.db"

EXPECTED_SHA = {
    "skills-list.jsonl": "daf34bedc998661a81f21b136e1e7c5341a96ed557a61a61fd0c4cfe97a28947",
    "details.jsonl": "700e607255a78a3f13f983281b1b3343015a34075956514a0ae66c2771ceaeec",
    "find-baseline.jsonl": "a0b6fa60925179c2f16d1c442f5c956dd3571c46ee18a7cdcc24d4c1cc49f8bc",
    "discovery/openapi.json": "40ea9473e97e1302d48ad5511654a94415ceb7e23f938b8bfa0859f527cc7de1",
    "discovery/categories.json": "684bbf23198db68432fe0e35d5f3b8945d5d7beae5208901dfc20d0cf8f2b3ea",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rebuild_catalog_content(row: dict) -> str:
    meta, card = row["metadata"], row["card"]
    source = meta["source"]
    if source.startswith("axehub:"):
        source = "hermes:" + source[len("axehub:"):]
    doc = {
        "description": card.get("description", ""),
        "external_id": meta["external_id"],
        "homepage": meta["homepage"],
        "name": card["title"],
        "source": source,
        "taxonomy": meta["taxonomy"],
        "use_count": meta["use_count"],
        "verified": meta["verified"],
    }
    return json.dumps(doc, sort_keys=True)


def norm_install(card: dict) -> dict:
    out = dict(card)
    out["install"] = "curl -s " + HOST_TOKEN + INSTALL_RE.match(card["install"]).group(1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="replace an existing output file")
    ap.add_argument("--skip-input-checksums", action="store_true",
                    help="do not require the snapshot files to match the checksums in its README")
    ap.add_argument("--report", type=Path, help="verification report (default: <out>.verify.json)")
    args = ap.parse_args()

    snap, out = args.snapshot, args.out.expanduser()
    if out.name == "hub.db":
        print("refusing to write a file named hub.db: that is the live database", file=sys.stderr)
        return 2
    if out.exists() and not args.force:
        print(f"{out} exists; pass --force to replace it", file=sys.stderr)
        return 2
    report_path = args.report or out.with_suffix(".verify.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    report: dict = {"snapshot": str(snap), "out": str(out), "problems": []}
    problems = report["problems"]

    report["input_checksums"] = {}
    for rel, want in EXPECTED_SHA.items():
        if not (snap / rel).exists() and args.skip_input_checksums:
            continue
        got = sha256_file(snap / rel)
        report["input_checksums"][rel] = {"sha256": got, "matches_readme": got == want}
        if got != want and not args.skip_input_checksums:
            problems.append(f"input checksum differs from the snapshot README: {rel}")

    rows = [json.loads(line) for line in open(snap / "skills-list.jsonl")]
    details = {}
    for line in open(snap / "details.jsonl"):
        d = json.loads(line)
        if d.get("detail_status") in (200, "200") and isinstance(d.get("detail"), dict):
            details[d["name"]] = d
    categories_doc = json.load(open(snap / "discovery" / "categories.json"))

    names = [r["name"] for r in rows]
    report["rows"] = len(rows)
    report["unique_names"] = len(set(names))
    report["list_in_binary_name_order"] = names == sorted(names, key=lambda n: n.encode())
    if len(set(names)) != len(names):
        problems.append("duplicate names in the list")
    if not report["list_in_binary_name_order"]:
        problems.append("list is not in binary name order; seq will follow snapshot order anyway")

    tmp = out.with_name(out.name + ".building")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if p.exists():
            p.unlink()
    reg = Registry(tmp)
    reg.add_tenant(TENANT, "Community (quarantine)")
    con = sqlite3.connect(tmp)
    con.executescript((Path(__file__).resolve().parent.parent / "hub" / "schema_serve.sql").read_text())

    body_source = collections.Counter()
    formats = collections.Counter()
    versions_multi = {}
    install_bad = 0
    cat_counts: collections.Counter = collections.Counter()
    cat_labels: dict = {}
    detail_mismatch = []
    unproven = []
    with con:
        for seq, r in enumerate(rows):
            name = r["name"]
            det = details.get(name)
            if det and "content" in det["detail"]:
                content = det["detail"]["content"]
                body_source["captured_detail"] += 1
            elif r["format"] == "catalog":
                content = rebuild_catalog_content(r)
                body_source["rebuilt_from_metadata_and_card"] += 1
            else:
                content = ""
                body_source["missing"] += 1
            if hashlib.sha256(content.encode()).hexdigest() != r["checksum"]:
                unproven.append(name)
            formats[r["format"]] += 1

            if not INSTALL_RE.match(r["card"]["install"]) or (
                INSTALL_RE.match(r["card"]["install"]).group(1) != "/v1/skills/" + quote(name, safe="")
            ):
                install_bad += 1
            card = norm_install(r["card"])
            category = card.get("category") or "other"
            cat_counts[category] += 1
            cat_labels.setdefault(category, card.get("category_label") or "Other")

            con.execute(
                "INSERT INTO skills (tenant_id, name, version, format, content, checksum, metadata,"
                " created_by, created_at, yanked_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["tenant_id"], name, r["version"], r["format"], content, r["checksum"],
                 json.dumps(r["metadata"]), r["created_by"], r["created_at"], r["yanked_at"]),
            )
            con.execute(
                "INSERT INTO skill_cards (tenant_id, name, version, seq, card, category, verified)"
                " VALUES (?,?,?,?,?,?,?)",
                (r["tenant_id"], name, r["version"], seq, json.dumps(card), category,
                 1 if r["metadata"].get("verified") else 0),
            )
            vers = det["versions"] if det and isinstance(det.get("versions"), list) and det["versions"] else [r["version"]]
            if vers[-1] != r["version"]:
                problems.append(f"{name}: latest captured version {vers[-1]} != list version {r['version']}")
            if len(vers) > 1:
                versions_multi[name] = len(vers)
            for i, v in enumerate(vers):
                con.execute("INSERT INTO skill_versions (tenant_id, name, ord, version) VALUES (?,?,?,?)",
                            (r["tenant_id"], name, i, v))
            if det:
                a = json.loads(json.dumps(det["detail"]))
                a.pop("content", None)
                b = json.loads(json.dumps(r))
                for x in (a, b):
                    x["card"] = norm_install(x["card"])
                if a != b:
                    detail_mismatch.append(name)

        stored = categories_doc["categories"]
        computed = {c: n for c, n in cat_counts.items()}
        stored_map = {c["category"]: c["count"] for c in stored}
        report["categories"] = {
            "stored": len(stored),
            "computed_from_cards": len(computed),
            "counts_equal": stored_map == computed,
            "labels_equal": all(cat_labels.get(c["category"]) == c["label"] for c in stored),
            "sum": sum(stored_map.values()),
        }
        if not report["categories"]["counts_equal"]:
            problems.append("stored category counts differ from the counts computed from the cards")
        for i, c in enumerate(stored):
            con.execute("INSERT INTO categories (tenant_id, ord, category, label, count) VALUES (?,?,?,?,?)",
                        (TENANT, i, c["category"], c["label"], c["count"]))
        meta = {
            "source_snapshot": str(snap),
            "list_sha256": report["input_checksums"]["skills-list.jsonl"]["sha256"],
            "rows": str(len(rows)),
            "tenant": TENANT,
        }
        for k, v in meta.items():
            con.execute("INSERT INTO import_meta (key, value) VALUES (?,?)", (k, v))
    con.execute("ANALYZE")
    con.commit()

    report["body_source"] = dict(body_source)
    report["bodies_unproven_by_checksum"] = len(unproven)
    report["bodies_unproven_names"] = unproven[:20]
    report["formats"] = dict(formats)
    report["install_not_matching_name_pattern"] = install_bad
    report["detail_rows_differing_from_list_row"] = detail_mismatch
    report["details_captured"] = len(details)
    report["skillmd_bodies_captured"] = sum(
        1 for d in details.values() if d["detail"]["format"] == "skillmd")
    report["multi_version_skills"] = versions_multi
    if unproven:
        problems.append(f"{len(unproven)} bodies do not hash to the reported checksum")
    if detail_mismatch:
        problems.append(f"{len(detail_mismatch)} captured details differ from their list row")

    count = con.execute("SELECT COUNT(*) FROM skills WHERE tenant_id=?", (TENANT,)).fetchone()[0]
    report["db_rows"] = count
    report["db_rows_equal_snapshot"] = count == len(rows)
    report["db_distinct_names"] = con.execute("SELECT COUNT(DISTINCT name) FROM skills").fetchone()[0]
    report["db_audit_rows"] = con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    report["db_quarantined_flag"] = {
        str(k): v for k, v in con.execute(
            "SELECT json_extract(metadata,'$.quarantined'), COUNT(*) FROM skills GROUP BY 1")}
    report["db_verified_true"] = con.execute("SELECT COUNT(*) FROM skill_cards WHERE verified=1").fetchone()[0]
    snap_verified = sum(1 for r in rows if r["metadata"].get("verified"))
    snap_quarantined = collections.Counter(str(r["metadata"].get("quarantined")) for r in rows)
    report["snapshot_verified_true"] = snap_verified
    report["snapshot_quarantined_flag"] = dict(snap_quarantined)
    if count != len(rows):
        problems.append("row count differs from the snapshot")
    con.close()

    # Re-read in the snapshot's order and compare every row back to the snapshot (metadata, card
    # with the host normalised, scalar columns), so the database is checked, not only the insert.
    chk = sqlite3.connect(tmp)
    bad = 0
    for r in rows:
        s = chk.execute(
            "SELECT version, format, checksum, metadata, created_by, created_at, yanked_at, tenant_id"
            " FROM skills WHERE tenant_id=? AND name=?", (TENANT, r["name"])).fetchone()
        c = chk.execute("SELECT card FROM skill_cards WHERE tenant_id=? AND name=?",
                        (TENANT, r["name"])).fetchone()[0]
        want = (r["version"], r["format"], r["checksum"], json.dumps(r["metadata"]), r["created_by"],
                r["created_at"], r["yanked_at"], r["tenant_id"])
        if tuple(s) != want or json.loads(c) != norm_install(r["card"]):
            bad += 1
    chk.close()
    report["rows_read_back_and_compared"] = len(rows)
    report["rows_differing_after_read_back"] = bad
    if bad:
        problems.append(f"{bad} rows differ after read-back")

    if out.exists():
        out.unlink()
    os.replace(tmp, out)
    for suffix in ("-wal", "-shm"):
        p = Path(str(tmp) + suffix)
        if p.exists():
            p.unlink()
    report["db_sha256"] = sha256_file(out)
    report["db_bytes"] = out.stat().st_size
    report["ok"] = not problems
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in (
        "rows", "db_rows", "bodies_unproven_by_checksum", "body_source", "skillmd_bodies_captured",
        "rows_differing_after_read_back", "ok")}, indent=2))
    print("problems:", problems or "none")
    print("report:", report_path)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
