"""The v2 build: a database imported from a rich-build snapshot, served read-only.

Builds a four-row snapshot on disk, runs scripts/import_snapshot.py over it, then drives a real server
against the result. Covers the importer's refusals, the list/detail/find/categories/search shapes, the
structured error body, the response headers, HEAD, and that a GET never writes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TENANT = "community-quarantine"


def _load_importer():
    spec = importlib.util.spec_from_file_location("import_snapshot", ROOT / "scripts" / "import_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


imp = _load_importer()


def _row(name: str, source: str, desc: str, category: str | None, tags: list[str], verified: bool = False) -> dict:
    meta = {"source": source, "external_id": f"x/{name}", "homepage": "", "verified": verified, "use_count": 0,
            "federated_at": "2026-09-10T06:04:26+00:00", "quarantined": not verified,
            "taxonomy": {"category": "other", "category_label": "Other", "tags": tags}}
    card = {"title": name.split("__")[-1], "source": source, "verified": verified, "use_count": 0,
            "description": desc}
    if category:
        card.update(category=category, category_label=category.title(), category_source="derived")
    if tags:
        card["tags"] = tags
    card["install"] = "curl -s https://operator.axe.onl/v1/skills/" + name.replace(":", "%3A")
    row = {"tenant_id": TENANT, "name": name, "version": "1.0.2", "format": "catalog", "checksum": "",
           "metadata": meta, "created_by": "federate-cron", "created_at": "2026-09-10T06:04:26+00:00",
           "yanked_at": None, "card": card}
    row["checksum"] = hashlib.sha256(imp.rebuild_catalog_content(row).encode()).hexdigest()
    return row


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory) -> Path:
    snap = tmp_path_factory.mktemp("snap")
    rows = sorted([
        _row("community__axehub:ClawHub__ClawHub__Docker", "axehub:ClawHub", "Manage Docker containers", "devops", ["docker"]),
        _row("community__axehub:ClawHub__ClawHub__Kubernetes", "axehub:ClawHub", "Run workloads on kubernetes", None, []),
        _row("community__axehub:skills.sh__skills.sh__pdf", "axehub:skills.sh", "Read and edit PDF files", "productivity", ["pdf"]),
        _row("zeta-first-party", "axe:first-party", "Docker is not mentioned here", None, [], verified=True),
    ], key=lambda r: r["name"])
    (snap / "skills-list.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    detail = {"name": rows[0]["name"], "must": True, "detail_status": "200", "detail_build": "rich",
              "detail": {**{k: v for k, v in rows[0].items() if k != "card"},
                         "content": imp.rebuild_catalog_content(rows[0]), "card": rows[0]["card"]},
              "versions_status": "200", "versions_build": "rich", "versions": ["1.0.0", "1.0.1", "1.0.2"]}
    (snap / "details.jsonl").write_text(json.dumps(detail) + "\n")
    counts: dict = {}
    for r in rows:
        c = r["card"].get("category") or "other"
        counts[c] = counts.get(c, 0) + 1
    cats = [{"category": c, "label": c.title(), "count": n, "find": f"/v1/tools/find?category={c}&q=<task>"}
            for c, n in sorted(counts.items(), key=lambda x: -x[1])]
    (snap / "discovery").mkdir()
    (snap / "discovery" / "categories.json").write_text(json.dumps({"count": len(cats), "categories": cats, "usage": "u"}))
    return snap


def _run_import(snap: Path, out: Path, *extra: str) -> int:
    argv = sys.argv
    sys.argv = ["import_snapshot.py", "--snapshot", str(snap), "--out", str(out), "--skip-input-checksums", *extra]
    try:
        return imp.main()
    finally:
        sys.argv = argv


def test_import_refuses_overwrite_and_live_name(snapshot, tmp_path):
    out = tmp_path / "hub-v2.db"
    assert _run_import(snapshot, out) == 0
    first = out.read_bytes()
    assert _run_import(snapshot, out) == 2
    assert out.read_bytes() == first
    assert _run_import(snapshot, out, "--force") == 0
    assert _run_import(snapshot, tmp_path / "hub.db") == 2
    report = json.loads(out.with_suffix(".verify.json").read_text())
    assert report["ok"] and report["db_rows"] == 4 and report["bodies_unproven_by_checksum"] == 0
    assert report["rows_differing_after_read_back"] == 0


@pytest.fixture(scope="module")
def v2(snapshot, tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "hub-v2.db"
    assert _run_import(snapshot, db) == 0

    from hub.evals import NoOpEvalStore
    from hub.serve import make_server
    from hub.store import Registry

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = make_server(Registry(db), NoOpEvalStore(), host="127.0.0.1", port=port,
                        default_tenant=TENANT, allow_origin="https://axe.onl", read_only=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    for _ in range(40):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)

    class V2:
        base = f"http://127.0.0.1:{port}"
        path = db

        def req(self, path, method="GET", headers=None, data=None):
            r = urllib.request.Request(self.base + path, method=method, headers=headers or {}, data=data)
            try:
                resp = urllib.request.urlopen(r)
            except urllib.error.HTTPError as e:
                resp = e
            body = resp.read().decode()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body

        def get(self, path, headers=None):
            code, h, body = self.req(path, headers=headers)
            return code, json.loads(body)

    yield V2()
    httpd.shutdown()


def test_list_is_bare_array_with_card_and_install_following_host(v2):
    code, rows = v2.get("/v1/skills")
    assert code == 200 and [r["name"] for r in rows] == sorted(r["name"] for r in rows) and len(rows) == 4
    assert list(rows[0]) == ["tenant_id", "name", "version", "format", "checksum", "metadata", "created_by",
                             "created_at", "yanked_at", "card"]
    assert rows[0]["tenant_id"] == TENANT
    assert rows[0]["card"]["install"].startswith("curl -s http://127.0.0.1:")
    assert rows[0]["card"]["install"].endswith("/v1/skills/community__axehub%3AClawHub__ClawHub__Docker")


def test_list_paging_and_envelope(v2):
    assert v2.get("/v1/skills?limit=0")[1] == []
    assert v2.get("/v1/skills?limit=-1")[1] == []
    code, env = v2.get("/v1/skills?limit=2&offset=1&envelope=1")
    assert [k for k in env] == ["object", "data", "limit", "offset", "total", "has_more"]
    assert env["total"] == 4 and env["has_more"] is True and len(env["data"]) == 2
    assert v2.get("/v1/skills?limit=1&offset=999&envelope=1")[1]["has_more"] is False
    assert v2.get("/v1/skills?limit=5000&envelope=1")[1]["limit"] == 1000


def test_detail_has_content_card_and_versions(v2):
    name = "community__axehub:ClawHub__ClawHub__Docker"
    for path in (f"/v1/skills/{name}", "/v1/skills/community__axehub%3AClawHub__ClawHub__Docker"):
        code, d = v2.get(path)
        assert code == 200 and list(d)[-2:] == ["content", "card"]
        assert hashlib.sha256(d["content"].encode()).hexdigest() == d["checksum"]
    assert v2.get(f"/v1/skills/{name}/versions")[1] == ["1.0.0", "1.0.1", "1.0.2"]
    assert v2.get(f"/v1/skills/{name}?version=1.0.0")[0] == 404


def test_errors_are_structured(v2):
    code, body = v2.get("/v1/skills/__no_such_skill__")
    assert code == 404 and body == {"error": {"type": "invalid_request_error", "code": "not_found",
                                              "message": "not found", "param": None}}
    code, body = v2.get("/v1/skills/__no_such_skill__/versions")
    assert code == 404 and body["error"]["message"] == "skill '__no_such_skill__' not found"
    code, body = v2.get("/v1/tools/find")
    assert code == 400 and body["error"] == {"type": "invalid_request_error", "code": "bad_request",
                                             "message": "q (or task) is required", "param": None}
    assert v2.get("/v1/tools/find?q=%20")[0] == 400
    assert v2.get("/v1/skills/search?q=")[0] == 400
    code, body = v2.get("/v1/tools/find?q=docker&limit=abc")
    assert code == 400 and body["error"]["param"] == "limit" and body["param"] == "limit"
    assert v2.get("/v1/tools/find?q=docker&limit=0")[0] == 400
    assert v2.get("/v1/nope")[1]["error"]["code"] == "not_found"


def test_find_shape_filters_and_limits(v2):
    code, f = v2.get("/v1/tools/find?q=docker&limit=3")
    assert code == 200 and list(f) == ["query", "count", "results", "limit"]
    assert f["results"][0]["name"].endswith("Docker") and f["results"][0]["score"] == 136.0
    assert list(f["results"][0]) == ["name", "title", "description", "category", "category_label",
                                     "category_source", "tags", "source", "author", "license", "verified",
                                     "use_count", "version", "homepage", "score", "matched_terms", "install"]
    k = v2.get("/v1/tools/find?q=kubernetes")[1]["results"][0]
    assert (k["category"], k["category_label"], k["category_source"]) == ("other", "Other", "upstream")
    assert [r["name"] for r in v2.get("/v1/tools/find?q=docker&verified=1")[1]["results"]] == ["zeta-first-party"] or \
        v2.get("/v1/tools/find?q=docker&verified=1")[1]["count"] == 0
    assert v2.get("/v1/tools/find?q=docker&category=devops")[1]["count"] == 1
    capped = v2.get("/v1/tools/find?q=docker&limit=99")[1]
    assert capped["limit"] == 50 and capped["limit_capped"] is True and "note_limit" in capped
    lit = v2.get("/v1/tools/find?q=the%20and")[1]
    assert lit["searched_literally"] == ["the", "and"] and "note" in lit


def test_categories_are_the_stored_values(v2):
    code, c = v2.get("/v1/categories")
    assert code == 200 and c["count"] == len(c["categories"]) == 3 and c["usage"].startswith("pick a category")
    assert c["categories"][0]["find"].startswith("/v1/tools/find?category=")


def test_search_matches_name_and_metadata_case_insensitively(v2):
    assert [r["name"] for r in v2.get("/v1/skills/search?q=KUBERNETES")[1]] == [
        "community__axehub:ClawHub__ClawHub__Kubernetes"]
    assert v2.get("/v1/skills/search?q=zzzqqq")[1] == []
    assert len(v2.get("/v1/skills/search?q=axehub:ClawHub")[1]) == 2


def test_headers_head_options_and_405(v2):
    code, h, body = v2.req("/healthz")
    assert h["x-request-id"].startswith("req_") and len(h["x-request-id"]) == 28
    assert h["access-control-allow-origin"] == "https://axe.onl" and h["vary"] == "Origin"
    assert h["x-frame-options"] == "SAMEORIGIN" and "cache-control" not in h
    code, h, body = v2.req("/v1/skills?limit=1", method="HEAD")
    assert code == 200 and body == "" and int(h["content-length"]) > 100
    code, h, body = v2.req("/v1/skills", method="OPTIONS")
    assert code == 204 and h["access-control-max-age"] == "600"
    code, h, body = v2.req("/v1/skills", method="POST", data=b"{}")
    assert code == 405 and json.loads(body)["error"]["code"] == "method_not_allowed"
    assert "HEAD" in h["allow"]


def test_tenant_header_is_ignored_on_the_read_only_origin(v2):
    for tenant in ("public", "axe-internal", "nonexistent"):
        assert v2.get("/v1/skills?limit=1", {"X-AXE-Tenant": tenant})[1][0]["tenant_id"] == TENANT


def test_a_get_never_writes(v2):
    def audit_rows() -> int:
        con = sqlite3.connect(f"file:{v2.path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        finally:
            con.close()

    before = audit_rows()
    v2.get("/v1/skills/community__axehub:ClawHub__ClawHub__Docker?_actor=mallory")
    v2.get("/v1/skills/zeta-first-party")
    assert audit_rows() == before == 0


def test_openapi_is_served_and_names_the_routes(v2):
    code, doc = v2.get("/openapi.json")
    assert code == 200 and doc["openapi"].startswith("3.1")
    assert {"/v1/tools/find", "/v1/categories", "/v1/skills", "/v1/skills/{name}"} <= set(doc["paths"])
    assert doc["servers"][0]["url"].startswith("http://127.0.0.1:")
