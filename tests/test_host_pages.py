"""Host-aware pages (hub/host_pages.py, hub/pages/): routing by Host, the strict policy, no figures in the page source,
the embedded fallback, and the optional category filter. No network, no live database.
"""
from __future__ import annotations

import json
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hub import host_pages
from hub.axeskills_docs_surface import render_skills_browse
from tests.test_kinds import _Srv, dbs, mk  # noqa: F401  (dbs is a fixture)

HOSTS = {"skills.axe.onl": "axe", "barracks.0perator.co": "barracks", "operator.axetechnologies.ca": "operator"}
TITLES = {"axe": "<title>AXe Skills Hub</title>", "barracks": "<title>Barracks · Operator</title>",
          "operator": "<title>Operator by AXe</title>"}
PAGES = Path(host_pages.PAGES_DIR)


def _get(base: str, path: str, host: str | None = None, headers: dict | None = None):
    req = urllib.request.Request(base + path, headers=dict(headers or {}))
    if host:
        req.add_header("Host", host)
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        resp = e
    return resp.status, dict(resp.headers), resp.read()


@pytest.fixture()
def srv(dbs):  # noqa: F811
    _, after, plugins, connectors = dbs
    assert mk.merge(after, [plugins, connectors])["checks"]["ok"]
    con = sqlite3.connect(after)
    row = con.execute("SELECT name, card FROM skill_cards WHERE kind = 'plugin' ORDER BY seq LIMIT 1").fetchone()
    card = json.loads(row[1])
    card["description"] = "</script><img src=x onerror=alert(1)> & <b>bold</b>"
    con.execute("UPDATE skill_cards SET card = ? WHERE name = ?", (json.dumps(card), row[0]))
    con.commit()
    con.close()
    s = _Srv(after)
    yield s
    s.httpd.shutdown()


def test_each_host_gets_its_page_and_other_hosts_keep_the_old_index(srv):
    seen = set()
    for host, key in HOSTS.items():
        code, headers, body = _get(srv.base, "/", host)
        text = body.decode()
        assert code == 200 and TITLES[key] in text, host
        assert 'id="hub-fallback"' in text and "<!--HUB-FALLBACK-->" not in text
        seen.add(text)
    assert len(seen) == 3
    old = render_skills_browse().encode()
    for host in (None, "localhost:8742", "example.com", "skills.axe.onl.evil.test", "evil-skills.axe.onl"):
        code, headers, body = _get(srv.base, "/", host)
        assert code == 200 and body == old, host
        assert headers["Content-Security-Policy"].startswith("default-src 'self' 'unsafe-inline'")


def test_host_is_matched_case_and_port_insensitively(srv):
    for host in ("SKILLS.AXE.ONL", "skills.axe.onl:443", "Skills.Axe.Onl:8742"):
        assert TITLES["axe"] in _get(srv.base, "/", host)[2].decode()


def test_forwarded_host_counts_only_from_loopback(srv):
    code, _, body = _get(srv.base, "/", None, {"X-Forwarded-Host": "barracks.0perator.co"})
    assert TITLES["barracks"] in body.decode()  # the test client is loopback, as the tunnel is
    assert host_pages.page_key("127.0.0.1:8742", "barracks.0perator.co", "127.0.0.1") == "barracks"
    assert host_pages.page_key("127.0.0.1:8742", "barracks.0perator.co", "203.0.113.9") is None
    assert host_pages.page_key("skills.axe.onl", "barracks.0perator.co", "203.0.113.9") == "axe"
    assert host_pages.page_key(None, None, "127.0.0.1") is None


def test_assets_follow_the_host_and_nothing_else_is_served(srv):
    bodies = {}
    for host, key in HOSTS.items():
        for name, ctype in (("app.js", "text/javascript"), ("app.css", "text/css"), ("common.js", "text/javascript")):
            code, headers, body = _get(srv.base, "/assets/" + name, host)
            assert code == 200 and headers["Content-Type"].startswith(ctype), (host, name)
            bodies[(key, name)] = body
    assert len({bodies[(k, "app.js")] for k in HOSTS.values()}) == 3
    assert len({bodies[(k, "common.js")] for k in HOSTS.values()}) == 1
    assert _get(srv.base, "/assets/app.js")[0] == 404
    for bad in ("/assets/nope.js", "/assets/../serve.py", "/assets/%2e%2e/serve.py", "/assets/index.html", "/assets/"):
        assert _get(srv.base, bad, "skills.axe.onl")[0] == 404, bad


def test_page_routes_carry_a_strict_content_security_policy(srv):
    for host in HOSTS:
        for path in ("/", "/assets/app.js", "/assets/app.css"):
            code, headers, _ = _get(srv.base, path, host)
            csp = headers["Content-Security-Policy"]
            assert csp == host_pages.CSP and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
            assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert "Host" in headers["Vary"]
    code, headers, _ = _get(srv.base, "/v1/kinds", "skills.axe.onl")
    assert headers["Content-Security-Policy"].startswith("default-src 'self' 'unsafe-inline'")


def test_api_contract_is_the_same_on_every_host(srv):
    for path in ("/v1/kinds", "/v1/skills?kind=plugin", "/v1/categories", "/v1/skills/search?q=docker"):
        # the install line names the host the request came in on, so that is the one thing allowed to differ
        base = _get(srv.base, path)[2].decode().replace(srv.base, "@H")
        for host in HOSTS:
            code, _, body = _get(srv.base, path, host)
            assert code == 200 and body.decode().replace("https://" + host, "@H") == base, (host, path)


def test_page_sources_hold_no_figures_and_no_unsafe_dom_writes():
    comma = re.compile(r"(?<![@;,\d])\b\d{1,3}(,\d{3})+\b")
    known = ("114134", "114,134", "2579", "2,579", "2545", "65738", "65,738", "116767", "116,767", "116686", "122050")
    named = re.compile(r"\b(81|21|13)\s+(verified|official|certified|quarantined|skills|plugins|connectors)\b", re.I)
    files = [p for d in ("axe", "barracks", "operator", "shared") for p in (PAGES / d).iterdir() if p.suffix in (".html", ".js", ".css")]
    assert len(files) >= 10
    for f in files:
        text = f.read_text()
        for m in comma.finditer(re.sub(r"<(svg|symbol)[\s\S]*?</\1>", "", text)):  # path data is not prose
            assert m.group(0) == "262,144", (f.name, m.group(0))  # the Athena context length, a fact about a model
        for k in known:
            assert k not in text, (f.parent.name, f.name, k)
        assert not named.search(text), (f.parent.name, f.name)
        for bad in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "outerHTML"):
            assert bad not in text, (f.parent.name, f.name, bad)
        if f.suffix == ".html":
            assert " style=" not in text and "<style" not in text and re.search(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)", text) is None, f.name
            assert re.search(r"\bon[a-z]+\s*=", text) is None, f.name


def test_the_embedded_fallback_is_computed_from_the_database_and_cannot_break_out(srv):
    code, _, body = _get(srv.base, "/", "barracks.0perator.co")
    text = body.decode()
    block = re.search(r'<script type="application/json" id="hub-fallback">(.*?)</script>', text, re.S).group(1)
    assert "</script" not in block.lower() and "<img" not in block and "<b>" not in block
    data = json.loads(block)
    assert [(k["kind"], k["count"]) for k in data["kinds"]] == [("skill", 4), ("plugin", 3), ("connector", 2)]
    assert data["stats"]["totals"] == {"skill": 4, "plugin": 3, "connector": 2}
    assert data["stats"]["verified"] == {"skill": 1, "plugin": 0, "connector": 0}
    assert [r["name"] for r in data["verified"]] == ["zeta-first-party"]
    assert all(r["metadata"].get("quarantined") for r in data["sample"]["plugin"] + data["sample"]["connector"])
    assert "@@HOST@@" not in block and "https://barracks.0perator.co/v1/skills/" in block.replace("\\u002f", "/")


def test_stats_endpoint_is_page_hosts_only_and_matches_the_database(srv):
    assert _get(srv.base, "/assets/stats.json")[0] == 404
    code, _, body = _get(srv.base, "/assets/stats.json", "skills.axe.onl")
    stats = json.loads(body)
    assert code == 200 and stats["totals"] == {"skill": 4, "plugin": 3, "connector": 2}
    assert stats["verified"]["skill"] == 1 and stats["defect"] == 0
    assert sum(stats["tiers"].values()) == 3
    assert sum(n for _, n in stats["sources"]["connector"]) == 2


def test_category_filter_on_the_list_is_optional_and_exact(srv):
    code, _, body = _get(srv.base, "/v1/skills?category=devops&envelope=1")
    d = json.loads(body)
    assert code == 200 and d["total"] == 1 and [r["card"]["category"] for r in d["data"]] == ["devops"]
    assert json.loads(_get(srv.base, "/v1/skills?category=nope&envelope=1")[2])["total"] == 0
    assert json.loads(_get(srv.base, "/v1/skills?envelope=1")[2])["total"] == 4
    plug = json.loads(_get(srv.base, "/v1/skills?kind=plugin&category=memory&envelope=1")[2])
    assert plug["total"] == 1 and plug["data"][0]["card"]["kind"] == "plugin"


def test_page_hosts_stay_read_only(srv):
    req = urllib.request.Request(srv.base + "/v1/skills", data=b"{}", method="POST", headers={"Host": "skills.axe.onl"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 405


def test_a_plain_registry_database_still_serves_the_page(tmp_path):
    from hub.evals import NoOpEvalStore
    from hub.serve import make_server
    from hub.store import Registry

    db = tmp_path / "plain.db"
    reg = Registry(db)
    reg.add_tenant("t1", "Test")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = make_server(Registry(db), NoOpEvalStore(), host="127.0.0.1", port=port, default_tenant="t1", read_only=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        code, _, body = _get(f"http://127.0.0.1:{port}", "/", "skills.axe.onl")
        assert code == 200 and b'id="hub-fallback">{}</script>' in body
        assert _get(f"http://127.0.0.1:{port}", "/assets/stats.json", "skills.axe.onl")[0] == 404
    finally:
        httpd.shutdown()
