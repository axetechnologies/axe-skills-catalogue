"""Kinds: plugins and connectors beside the skills (hub/kinds.py, scripts/merge_hermes_kinds.py). No network.

Covers the live-path refusals, the merge (quarantine, carried fields, keys, collapse, versions, withdrawn marks,
idempotency), the reversible migration, ?kind= on list/search/categories/find, /v1/kinds, that a skills-only
client is served byte for byte what it was served before, that a later skills merge leaves the other kinds
alone, and the plain registry path.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hub.catalog import Catalog
from tests.test_merge_hermes import HERMES, mh
from tests.test_rich_parity import ROOT, TENANT, _row, _run_import


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mk = _load("merge_hermes_kinds")
migrate = _load("migrate_kinds")


def _rec(kind, name, desc, category, **extra):
    rec = {"kind": kind, "name": name, "display_name": name.replace("-", " ").title(), "source": "Hermes",
           "author": "", "category": category, "description": desc, "version": "", "licence": "",
           "homepage": "", "install": f"hermes {kind}s install {name}", "trust_tier": "community",
           "disclosure": "", "permissions": [], "env_vars": [], "platforms": [], "raw": {"name": name}}
    rec.update(extra)
    return rec


PLUGINS = [
    _rec("plugin", "hermes-memory-wiki", "Long-term memory as a wiki", "Memory", trust_tier="official",
         author="Nous Research", licence="MIT", version="0.4.1", homepage="https://github.com/x/memory-wiki",
         disclosure="Disclosure — stores notes on a remote server.", permissions=["network"],
         env_vars=["WIKI_TOKEN"], platforms=["linux", "macos"], risk_flags=["network-egress"], stars=0,
         install={"method": "cli", "command": "hermes plugins install hermes-memory-wiki"}),
    _rec("plugin", "blender", "Drive Blender from the agent", "Desktop"),
    _rec("plugin", "blender", "Drive Blender from the agent, with scene export", "Desktop"),
    _rec("plugin", "docker-tools", "Docker helpers", "Tools", trust_tier="verified"),
    _rec("skill", "not-here", "a skill record is not this script's to merge", "Tools"),
    _rec("plugin", "", "no name, skipped", "Tools"),
]
CONNECTORS = [
    _rec("connector", "github", "GitHub through one sign-in", "Developer", trust_tier=None, author=None),
    _rec("connector", "slack", "Slack through one sign-in", "Communication"),
]


def _base_db(tmp_path) -> Path:
    snap = tmp_path / "snap"
    (snap / "discovery").mkdir(parents=True)
    rows = sorted([
        _row("community__axehub:ClawHub__ClawHub__Docker", "axehub:ClawHub", "Manage Docker containers", "devops", ["docker"]),
        _row("community__axehub:ClawHub__ClawHub__Kubernetes", "axehub:ClawHub", "Run workloads", None, []),
        _row("community__axehub:skills.sh__skills.sh__pdf", "axehub:skills.sh", "Read PDF files", "productivity", []),
        _row("zeta-first-party", "axe:first-party", "First-party", None, [], verified=True),
    ], key=lambda r: r["name"])
    (snap / "skills-list.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (snap / "details.jsonl").write_text("")
    cats = [{"category": "other", "label": "Other", "count": 2}, {"category": "devops", "label": "Devops", "count": 1},
            {"category": "productivity", "label": "Productivity", "count": 1}]
    (snap / "discovery" / "categories.json").write_text(json.dumps({"categories": cats}))
    db = tmp_path / "barracks.before.db"
    assert _run_import(snap, db) == 0
    return db


@pytest.fixture()
def dbs(tmp_path):
    before = _base_db(tmp_path)
    after = tmp_path / "barracks.kinds.db"
    shutil.copy(before, after)
    plugins, connectors = tmp_path / "plugins-normalized.json", tmp_path / "connectors-normalized.json"
    plugins.write_text(json.dumps(PLUGINS))
    connectors.write_text(json.dumps({"items": CONNECTORS}))
    return before, after, plugins, connectors


def _meta(db, name):
    con = sqlite3.connect(db)
    try:
        return json.loads(con.execute("SELECT metadata FROM skills WHERE name = ? ORDER BY created_at DESC",
                                      (name,)).fetchone()[0])
    finally:
        con.close()


def test_refuses_live_names_and_the_live_file(dbs, tmp_path, monkeypatch):
    before, _, plugins, _ = dbs
    original = before.read_bytes()
    for live in ("barracks.db", "hub.db", "skills-catalogue.db"):
        (tmp_path / live).write_bytes(original)
        assert mk.refuse(tmp_path / live) is not None
    other = tmp_path / "innocent.db"
    other.hardlink_to(before)
    monkeypatch.setenv("AXE_HUB_DB", str(before))
    assert "live database" in mk.refuse(other)
    monkeypatch.setattr(sys, "argv", ["merge_hermes_kinds.py", "--db", str(other), "--input", str(plugins)])
    assert mk.main() == 2
    monkeypatch.setattr(sys, "argv", ["migrate_kinds.py", "--db", str(tmp_path / "barracks.db"), "up"])
    assert migrate.main() == 2
    assert before.read_bytes() == original and (tmp_path / "barracks.db").read_bytes() == original
    monkeypatch.delenv("AXE_HUB_DB")
    assert mk.refuse(tmp_path / "missing.db") is not None


def test_merge_quarantines_carries_fields_and_is_idempotent(dbs):
    _, db, plugins, connectors = dbs
    r = mk.merge(db, [plugins, connectors], now="2026-11-24T00:00:00+00:00")
    assert r["checks"]["ok"], r["checks"]
    assert r["skills_untouched"] and r["migrated"] is True
    assert r["added_by_kind"] == {"plugin": 3, "connector": 2} and r["updated"] == 0
    assert r["collapsed_same_key"] == {"plugin": 1, "connector": 0}
    assert r["skipped_reasons"] == {"kind not one of plugin, connector": 1, "no name or source": 1}
    assert r["checks"]["by_kind"]["skill"] == {"cards": 4, "categories_sum": 4, "seq_from": 0, "seq_contiguous": True}
    assert r["checks"]["kinds_in_order"] and r["checks"]["non_skill_not_quarantined"] == 0

    cat = Catalog(db)
    wiki = json.loads(cat.get(TENANT, "plugin__axehub:Hermes__hermes-memory-wiki", None))
    c, m = wiki["card"], wiki["metadata"]
    assert wiki["version"] == "1.0.0" and wiki["created_by"] == mk.DEFAULT_ACTOR
    assert c["kind"] == "plugin" and c["verified"] is False and c["trust_tier"] == "official"
    assert (c["license"], c["author"], c["upstream_version"]) == ("MIT", "Nous Research", "0.4.1")
    assert c["disclosure"].startswith("Disclosure") and c["permissions"] == ["network"]
    assert c["env_vars"] == ["WIKI_TOKEN"] and c["platforms"] == ["linux", "macos"]
    assert c["category"] == "memory" and c["category_label"] == "Memory"
    assert c["upstream_install"]["command"] == "hermes plugins install hermes-memory-wiki"
    assert c["risk_flags"] == m["risk_flags"] == ["network-egress"] and c["stars"] == 0
    assert c["install"] == "curl -s @@HOST@@/v1/skills/plugin__axehub%3AHermes__hermes-memory-wiki"
    assert m["quarantined"] is True and m["kind"] == "plugin" and m["trust_tier"] == "official"
    assert m["license"] == "MIT" and m["disclosure"] == c["disclosure"]
    assert json.loads(wiki["content"])["raw"] == {"name": "hermes-memory-wiki"}
    blender = json.loads(cat.get(TENANT, "plugin__axehub:Hermes__blender", None))
    assert blender["card"]["description"].endswith("scene export")

    again = mk.merge(db, [plugins, connectors])
    assert (again["added"], again["updated"], again["withdrawn_newly_marked"]) == (0, 0, 0)
    assert again["unchanged"] == 5 and again["checks"]["ok"] and again["skills_untouched"]
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM import_meta WHERE key LIKE 'merge:hermes-kinds:%'").fetchone()[0] == 2
    con.close()


def test_changed_record_gets_next_version_and_missing_ones_are_marked_per_kind(dbs):
    _, db, plugins, connectors = dbs
    mk.merge(db, [plugins, connectors])
    changed = [dict(p) for p in PLUGINS if p["name"] != "docker-tools"]
    changed[0] = {**changed[0], "description": "Long-term memory as a wiki, now searchable"}
    plugins.write_text(json.dumps(changed))
    r = mk.merge(db, [plugins])
    assert r["updated_by_kind"] == {"plugin": 1} and r["checks"]["ok"]
    assert r["withdrawn_upstream"] == 1 and r["withdrawn_newly_marked"] == 1
    cat = Catalog(db)
    wiki = json.loads(cat.get(TENANT, "plugin__axehub:Hermes__hermes-memory-wiki", None))
    assert wiki["version"] == "1.0.1" and cat.versions(TENANT, wiki["name"]) == ["1.0.0", "1.0.1"]
    assert _meta(db, "plugin__axehub:Hermes__docker-tools")["upstream_status"] == "withdrawn"
    assert "upstream_status" not in _meta(db, "connector__axehub:Hermes__github")

    plugins.write_text(json.dumps(PLUGINS))
    back = mk.merge(db, [plugins])
    assert back["withdrawn_flag_cleared"] == 1 and "upstream_status" not in _meta(db, "plugin__axehub:Hermes__docker-tools")


def test_migration_is_reversible(dbs):
    before, db, plugins, connectors = dbs
    digest = mk.skills_digest(sqlite3.connect(before))
    mk.merge(db, [plugins, connectors])
    con = sqlite3.connect(db)
    with con:
        out = migrate.kinds.down(con)
    assert out["entries_removed"] == 5 and out["skills_rows_removed"] == 5
    assert not migrate.kinds.present(con) and mk.skills_digest(con) == digest
    assert con.execute("SELECT COUNT(*) FROM skill_versions").fetchone()[0] == \
        sqlite3.connect(before).execute("SELECT COUNT(*) FROM skill_versions").fetchone()[0]
    with con:
        assert migrate.kinds.up(con) is True and migrate.kinds.up(con) is False
    assert mk.skills_digest(con) == digest
    con.close()


def test_a_later_skills_merge_leaves_plugins_and_connectors_alone(dbs, tmp_path):
    _, db, plugins, connectors = dbs
    mk.merge(db, [plugins, connectors])
    hermes = tmp_path / "hermes-skills.json"
    hermes.write_text(json.dumps(HERMES))
    r = mh.merge(db, hermes)
    assert r["checks"]["ok"], r["checks"]
    assert r["withdrawn_by_source"] == {"axehub:ClawHub": 1, "axehub:skills.sh": 1} and r["added"] == 4
    assert r["checks"]["by_kind"]["plugin"]["cards"] == 3 and r["checks"]["kinds_in_order"]
    assert "upstream_status" not in _meta(db, "plugin__axehub:Hermes__blender")
    again = mk.merge(db, [plugins, connectors])
    assert again["unchanged"] == 5 and again["added"] == again["updated"] == 0 and again["checks"]["ok"]


class _Srv:
    def __init__(self, db: Path, plain_tenant: str | None = None) -> None:
        from hub.evals import NoOpEvalStore
        from hub.serve import make_server
        from hub.store import Registry

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.httpd = make_server(Registry(db), NoOpEvalStore(), host="127.0.0.1", port=port,
                                 default_tenant=plain_tenant or TENANT, read_only=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    def raw(self, path):
        try:
            resp = urllib.request.urlopen(self.base + path)
        except urllib.error.HTTPError as e:
            resp = e
        return resp.status, resp.read()

    def get(self, path):
        code, body = self.raw(path)
        return code, json.loads(body)


@pytest.fixture()
def servers(dbs):
    before, after, plugins, connectors = dbs
    assert mk.merge(after, [plugins, connectors])["checks"]["ok"]
    old, new = _Srv(before), _Srv(after)
    yield old, new
    old.httpd.shutdown()
    new.httpd.shutdown()


SKILL_PATHS = [
    "/v1/skills", "/v1/skills?limit=2&offset=1", "/v1/skills?envelope=1", "/v1/skills?limit=1&offset=3&envelope=1",
    "/v1/skills?kind=skill", "/v1/skills/search?q=docker", "/v1/skills/search?q=a&limit=2&offset=1",
    "/v1/categories", "/v1/tools/find?q=docker", "/v1/tools/find?q=run+workloads&limit=60",
    "/v1/skills/find?q=pdf&category=productivity", "/v1/skills/zeta-first-party",
    "/v1/skills/community__axehub%3AClawHub__ClawHub__Docker/versions", "/v1/skills/search",
]


def test_skills_only_clients_see_no_change(servers):
    old, new = servers

    def same_host(path):
        code, body = new.raw(path)
        return code, body.replace(new.base.encode(), old.base.encode())

    for path in SKILL_PATHS:
        assert old.raw(path) == same_host(path), path
    assert same_host("/v1/skills?kind=skill") == old.raw("/v1/skills")


def test_kinds_endpoint_and_kind_filters(servers):
    old, new = servers
    code, body = new.get("/v1/kinds")
    assert code == 200 and body["count"] == 3
    assert [(k["kind"], k["count"]) for k in body["kinds"]] == [("skill", 4), ("plugin", 3), ("connector", 2)]
    assert body["kinds"][1]["list"] == "/v1/skills?kind=plugin"
    assert [(k["kind"], k["count"]) for k in old.get("/v1/kinds")[1]["kinds"]] == [
        ("skill", 4), ("plugin", 0), ("connector", 0)]

    code, rows = new.get("/v1/skills?kind=plugin")
    assert code == 200 and [r["name"] for r in rows] == [
        "plugin__axehub:Hermes__blender", "plugin__axehub:Hermes__docker-tools",
        "plugin__axehub:Hermes__hermes-memory-wiki"]
    assert all(r["card"]["kind"] == "plugin" and r["metadata"]["quarantined"] for r in rows)
    assert rows[0]["card"]["install"].startswith(f"curl -s {new.base}/v1/skills/plugin__")
    assert [r["name"] for r in new.get("/v1/skills?kind=plugin&limit=1&offset=1")[1]] == [rows[1]["name"]]
    env = new.get("/v1/skills?kind=connector&envelope=1&limit=1")[1]
    assert (env["total"], env["has_more"], len(env["data"])) == (2, True, 1)
    assert old.get("/v1/skills?kind=plugin") == (200, [])

    assert [r["name"] for r in new.get("/v1/skills/search?q=docker&kind=plugin")[1]] == [
        "plugin__axehub:Hermes__docker-tools"]
    assert [r["name"] for r in new.get("/v1/skills/search?q=docker")[1]] == [
        "community__axehub:ClawHub__ClawHub__Docker"]

    cats = new.get("/v1/categories?kind=plugin")[1]
    assert {c["category"]: c["count"] for c in cats["categories"]} == {"desktop": 1, "memory": 1, "tools": 1}
    assert cats["categories"][0]["find"].endswith("&kind=plugin&q=<task>")
    assert {c["label"] for c in new.get("/v1/categories?kind=connector")[1]["categories"]} == {
        "Developer", "Communication"}

    found = new.get("/v1/tools/find?q=docker&kind=plugin")[1]
    assert [r["name"] for r in found["results"]] == ["plugin__axehub:Hermes__docker-tools"]
    assert found["results"][0]["kind"] == "plugin" and found["results"][0]["verified"] is False
    assert "kind" not in new.get("/v1/tools/find?q=docker")[1]["results"][0]
    assert new.get("/v1/tools/find?q=memory&kind=plugin&category=memory")[1]["count"] == 1

    assert new.get("/v1/skills/connector__axehub%3AHermes__github")[1]["card"]["kind"] == "connector"
    for path in ("/v1/skills?kind=bundle", "/v1/skills/search?q=x&kind=Plugin", "/v1/categories?kind=x",
                 "/v1/tools/find?q=x&kind=all"):
        code, err = new.get(path)
        assert code == 400 and err["error"]["param"] == "kind", path


def test_plain_registry_path_has_only_skills(tmp_path):
    from hub.store import Registry

    db = tmp_path / "plain.db"
    reg = Registry(db)
    reg.add_tenant("t1", "Test")
    reg.publish("t1", "auto-tail", "1.0.0", "tail -f $1", actor="test", format="python",
                metadata={"description": "Tail a log file."})
    srv = _Srv(db, plain_tenant="t1")
    try:
        assert [(k["kind"], k["count"]) for k in srv.get("/v1/kinds")[1]["kinds"]] == [
            ("skill", 1), ("plugin", 0), ("connector", 0)]
        assert srv.raw("/v1/skills?kind=skill") == srv.raw("/v1/skills")
        assert srv.get("/v1/skills?kind=plugin") == (200, [])
        assert srv.get("/v1/skills/search?q=tail&kind=connector") == (200, [])
        assert srv.get("/v1/tools/find?q=tail&kind=plugin")[1]["count"] == 0
        assert srv.get("/v1/skills?kind=nope")[0] == 400
    finally:
        srv.httpd.shutdown()
