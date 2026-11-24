"""scripts/merge_hermes.py over a small imported database and a fixture Hermes export (no network).

Covers the live-name refusal, add / update / unchanged, the installIdentifier split of a shared
source/name, the same-identifier collapse, the withdrawn mark, the rebuilt order and facets, the
first-party verified rule, and that a second run adds nothing.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from hub.catalog import Catalog
from tests.test_rich_parity import ROOT, TENANT, _row, _run_import


def _load_merger():
    spec = importlib.util.spec_from_file_location("merge_hermes", ROOT / "scripts" / "merge_hermes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["merge_hermes"] = mod
    spec.loader.exec_module(mod)
    return mod


mh = _load_merger()


def _hermes(name, source, desc, ident, category="other", label="Other", **extra):
    return {"name": name, "description": desc, "overview": "", "category": category, "categoryLabel": label,
            "source": source, "tags": [], "platforms": [], "author": "", "version": "", "license": "",
            "envVars": [], "commands": [], "docsPath": "", "installIdentifier": ident,
            "installCmd": f"hermes skills install {ident}", **extra}


HERMES = [
    _hermes("Docker", "ClawHub", "Manage Docker containers, now with compose", "clawhub/docker"),
    _hermes("New Skill", "ClawHub", "short", "clawhub/new-skill"),
    _hermes("New Skill", "ClawHub", "the longer description wins", "clawhub/new-skill"),
    _hermes("search-listings", "browse.sh", "Search cars.com", "browse-sh/cars.com/search-listings-a1"),
    _hermes("search-listings", "browse.sh", "Search craigslist.org listings", "browse-sh/craigslist.org/search-listings-b2"),
    _hermes("apple-notes", "built-in", "Manage Apple Notes", "NousResearch/hermes-agent/skills/apple/apple-notes",
            category="apple", label="Apple", license="MIT", author="Hermes Agent",
            tags=[f"t{i}" for i in range(10)], docsPath="bundled/apple/apple-apple-notes"),
    _hermes("", "ClawHub", "no name, skipped", "clawhub/nameless"),
]


@pytest.fixture()
def merged(tmp_path):
    snap = tmp_path / "snap"
    (snap / "discovery").mkdir(parents=True)
    rows = sorted([
        _row("community__axehub:ClawHub__ClawHub__Docker", "axehub:ClawHub", "Manage Docker containers", "devops", ["docker"]),
        _row("community__axehub:ClawHub__ClawHub__Kubernetes", "axehub:ClawHub", "Run workloads", None, []),
        _row("zeta-first-party", "axe:first-party", "First-party", None, [], verified=True),
    ], key=lambda r: r["name"])
    (snap / "skills-list.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (snap / "details.jsonl").write_text("")
    cats = [{"category": "other", "label": "Other", "count": 2}, {"category": "devops", "label": "Devops", "count": 1}]
    (snap / "discovery" / "categories.json").write_text(json.dumps({"categories": cats}))
    db = tmp_path / "barracks.next.db"
    assert _run_import(snap, db) == 0
    hermes = tmp_path / "hermes-skills.json"
    hermes.write_text(json.dumps(HERMES))
    return db, hermes


def test_refuses_live_database_names(merged, tmp_path):
    db, hermes = merged
    for live in ("barracks.db", "hub.db"):
        (tmp_path / live).write_bytes(db.read_bytes())
        argv = sys.argv
        sys.argv = ["merge_hermes.py", "--db", str(tmp_path / live), "--hermes", str(hermes)]
        try:
            assert mh.main() == 2
        finally:
            sys.argv = argv
        assert (tmp_path / live).read_bytes() == db.read_bytes()


def test_merge_adds_updates_marks_and_is_idempotent(merged):
    db, hermes = merged
    r = mh.merge(db, hermes, now="2026-11-24T00:00:00+00:00")
    assert r["checks"]["ok"], r["checks"]
    assert (r["added"], r["updated"], r["unchanged"], r["skipped"]) == (4, 1, 0, 1)
    assert r["dedup"]["collapsed_same_install_identifier"] == {"ClawHub": 1}
    assert r["dedup"]["recovered_by_install_identifier"] == {"browse.sh": 1}
    assert r["withdrawn_upstream"] == 1 and r["withdrawn_by_source"] == {"axehub:ClawHub": 1}

    again = mh.merge(db, hermes)
    assert (again["added"], again["updated"], again["withdrawn_newly_marked"]) == (0, 0, 0)
    assert again["unchanged"] == 5 and again["checks"]["ok"]

    cat = Catalog(db)
    names = [json.loads(x)["name"] for x in cat.list_page(TENANT, 100, 0)]
    assert names == sorted(names, key=str.encode) and len(names) == cat.total(TENANT) == 7
    assert sum(c["count"] for c in cat.categories(TENANT)) == 7

    docker = json.loads(cat.get(TENANT, "community__axehub:ClawHub__ClawHub__Docker", None))
    assert docker["version"] == "1.0.3" and cat.versions(TENANT, docker["name"]) == ["1.0.2", "1.0.3"]
    assert docker["card"]["category_source"] == "derived" and docker["card"]["category"] == "devops"

    new = json.loads(cat.get(TENANT, "community__axehub:ClawHub__ClawHub__New_Skill", None))
    assert new["card"]["description"] == "the longer description wins"
    assert new["created_by"] == mh.DEFAULT_ACTOR and new["metadata"]["quarantined"] is True

    split = {n for n in names if "search-listings" in n}
    assert len(split) == 2

    notes = json.loads(cat.get(TENANT, "community__axehub:built-in__built-in__apple-notes", None))
    assert notes["card"]["verified"] is True and notes["card"]["license"] == "MIT"
    assert notes["card"]["category_label"] == "Apple" and len(notes["card"]["tags"]) == 8
    assert notes["card"]["install"].startswith("curl -s @@HOST@@/v1/skills/community__axehub%3Abuilt-in")

    con = sqlite3.connect(db)
    meta = dict(con.execute("SELECT name, metadata FROM skills"))
    assert json.loads(meta["community__axehub:ClawHub__ClawHub__Kubernetes"])["upstream_status"] == "withdrawn"
    assert "upstream_status" not in json.loads(meta["zeta-first-party"])
    assert con.execute("SELECT COUNT(*) FROM import_meta WHERE key LIKE 'merge:hermes:%'").fetchone()[0] == 2
    con.close()
