"""Integration tests for the read-only HTTP surface.

Spins up a real server against an in-process SQLite database and fires
HTTP requests. Covers /healthz, /v1/skills (list + pagination),
/v1/skills/search, /v1/skills/<name>, /v1/skills/<name>/versions, and
verifies that POST is blocked in READ_ONLY mode and /v1/audit returns 404.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_db(db_path: Path) -> None:
    from hub.store import Registry

    reg = Registry(db_path)
    reg.add_tenant("t1", "Test")
    reg.publish(
        "t1",
        "auto-tail",
        "1.0.0",
        "#!/bin/bash\ntail -f $1",
        actor="test",
        format="python",
        metadata={"description": "Tail a log file and print new lines.", "source": "axe"},
    )
    reg.publish(
        "t1",
        "log-grep",
        "1.0.0",
        "grep $1 $2",
        actor="test",
        format="python",
        metadata={
            "description": "Search a log file for a pattern.",
            "source": "ClawHub:log-grep",
        },
    )


class _Server:
    def __init__(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = Path(name)
        _seed_db(self.db_path)

        from hub.serve import make_server
        from hub.store import Registry
        from hub.evals import EvalStore

        port = _free_port()
        self.base = f"http://127.0.0.1:{port}"
        self.httpd = make_server(
            Registry(self.db_path),
            EvalStore(),
            host="127.0.0.1",
            port=port,
            default_tenant="t1",
            read_only=True,
        )
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        for _ in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)

    def get(self, path: str, headers: dict | None = None) -> tuple[int, object]:
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                body = r.read().decode()
                try:
                    return r.status, json.loads(body)
                except json.JSONDecodeError:
                    return r.status, body
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, body

    def post(self, path: str, payload: dict) -> tuple[int, object]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, body

    def teardown(self) -> None:
        self.httpd.shutdown()
        os.unlink(self.db_path)


@pytest.fixture(scope="module")
def srv():
    s = _Server()
    yield s
    s.teardown()


def test_healthz(srv):
    code, body = srv.get("/healthz")
    assert code == 200
    assert body.get("status") == "ok"


def test_list_skills_returns_seeded_rows(srv):
    code, body = srv.get("/v1/skills")
    assert code == 200
    names = {s["name"] for s in body}
    assert "auto-tail" in names
    assert "log-grep" in names


def test_list_pagination_limit(srv):
    code, body = srv.get("/v1/skills?limit=1&offset=0")
    assert code == 200
    assert len(body) == 1


def test_list_pagination_offset_advances(srv):
    _, b0 = srv.get("/v1/skills?limit=1&offset=0")
    _, b1 = srv.get("/v1/skills?limit=1&offset=1")
    assert b0[0]["name"] != b1[0]["name"]


def test_list_body_excludes_content(srv):
    code, body = srv.get("/v1/skills")
    assert code == 200
    for row in body:
        assert "content" not in row


def test_search_returns_relevant(srv):
    code, body = srv.get("/v1/skills/search?q=log")
    assert code == 200
    names = {s["name"] for s in body}
    assert "log-grep" in names


def test_search_empty_q_returns_empty(srv):
    code, body = srv.get("/v1/skills/search?q=")
    assert code == 200
    assert isinstance(body, list)


def test_fetch_one_skill_has_content(srv):
    code, body = srv.get("/v1/skills/auto-tail")
    assert code == 200
    assert body["name"] == "auto-tail"
    assert "content" in body


def test_fetch_missing_skill_404(srv):
    code, _ = srv.get("/v1/skills/no-such-skill")
    assert code == 404


def test_versions_endpoint(srv):
    code, body = srv.get("/v1/skills/auto-tail/versions")
    assert code == 200
    assert "1.0.0" in body


def test_upstream_source_label_preserved(srv):
    code, body = srv.get("/v1/skills/log-grep")
    assert code == 200
    # ClawHub attribution must survive the round-trip verbatim in metadata
    meta = body.get("metadata") or {}
    assert "ClawHub" in meta.get("source", "")


def test_post_blocked_in_read_only(srv):
    code, _ = srv.post(
        "/v1/skills",
        {
            "tenant": "t1",
            "name": "x",
            "version": "1.0.0",
            "content": "x",
            "format": "python",
            "actor": "test",
        },
    )
    assert code == 405


def test_audit_returns_404_in_read_only(srv):
    code, _ = srv.get("/v1/audit")
    assert code == 404
