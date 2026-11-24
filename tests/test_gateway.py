"""Marketplace gateway: identity, subscription, tenant isolation, quarantine on publish, limits."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hub.evals import EvalStore
from hub.gateway import Authenticator, make_gateway
from hub.serve import make_server
from hub.store import Registry

TOKENS = {
    "op_sub": {"account": {"external_id": "a@x.io", "status": "active"}, "subscription": {"plan": "pro", "status": "active"}},
    "op_sub2": {"account": {"external_id": "b@x.io", "status": "active"}, "subscription": {"plan": "pro", "status": "active"}},
    "op_lapsed": {"account": {"external_id": "c@x.io", "status": "active"}, "subscription": {"plan": "pro", "status": "canceled"}},
    "op_nosub": {"account": {"external_id": "d@x.io", "status": "active"}, "subscription": None},
    "op_pending": {"account": {"external_id": "e@x.io", "status": "pending"}},
}


class _Verify(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        tok = self.headers.get("Authorization", "").replace("Bearer ", "")
        body = TOKENS.get(tok)
        if body is None:
            self.send_response(401); self.end_headers(); return
        if body["account"]["status"] != "active":
            self.send_response(403); self.end_headers(); return
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)


def _serve(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture()
def stack(tmp_path):
    ver = ThreadingHTTPServer(("127.0.0.1", 0), _Verify)
    vurl = _serve(ver)
    rdb, wdb = tmp_path / "r.db", tmp_path / "w.db"
    rreg = Registry(rdb); rreg.add_tenant("pub", "pub")
    rreg.publish("pub", "hello", "1.0.0", "body", actor="t")
    wreg = Registry(wdb)
    rurl = _serve(make_server(rreg, EvalStore(tmp_path / "re.db"), default_tenant="pub", read_only=True))
    wurl = _serve(make_server(wreg, EvalStore(tmp_path / "we.db")))
    auth = Authenticator(vurl, {"pro", "beta"}, legacy_beta=False, ttl=0.0, miss_ttl=0.0)
    gw = make_gateway(auth, read_upstream=rurl, write_upstream=wurl, writes_per_hour=3, max_body=2000,
                      audit_path=str(tmp_path / "audit.jsonl"), write_db=str(wdb))
    yield _serve(gw), tmp_path
    for s in (gw, ver):
        s.shutdown()


def call(base, path, token=None, method="GET", body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


SKILL = {"name": "my-skill", "version": "1.0.0", "content": "# do it"}


def test_health_is_open(stack):
    assert call(stack[0], "/healthz")[0] == 200


@pytest.mark.parametrize("tok,status,code", [
    (None, 401, "not_signed_in"), ("op_bad", 401, "not_signed_in"),
    ("op_pending", 403, "account_not_active"), ("op_nosub", 403, "subscription_required"),
    ("op_lapsed", 403, "subscription_required"),
])
def test_unentitled_callers_are_refused_everywhere(stack, tok, status, code):
    for method, path, body in (("GET", "/v1/skills/hello", None), ("POST", "/v1/skills", SKILL)):
        s, b = call(stack[0], path, tok, method, body)
        assert (s, b["error"]) == (status, code)


def test_subscriber_reads_the_catalogue(stack):
    s, b = call(stack[0], "/v1/skills/hello", "op_sub")
    assert s == 200 and b["name"] == "hello"


def test_publish_lands_quarantined_and_cannot_claim_verified(stack):
    s, b = call(stack[0], "/v1/skills", "op_sub", "POST", {**SKILL, "metadata": {"verified": True, "quarantined": False, "source": "axe"}})
    assert s == 201
    m = b["metadata"]
    assert m["quarantined"] is True and m["verified"] is False and m["source"] == "user"


def test_tenants_are_isolated_and_scope_mine_reads_own_only(stack):
    base = stack[0]
    assert call(base, "/v1/skills", "op_sub", "POST", SKILL)[0] == 201
    assert call(base, "/v1/skills/my-skill?scope=mine", "op_sub")[0] == 200
    assert call(base, "/v1/skills/my-skill?scope=mine", "op_sub2")[0] == 404
    assert call(base, "/v1/skills/my-skill", "op_sub")[0] == 404


def test_republishing_a_version_conflicts(stack):
    call(stack[0], "/v1/skills", "op_sub", "POST", SKILL)
    assert call(stack[0], "/v1/skills", "op_sub", "POST", SKILL)[0] == 409


def test_validation_and_limits(stack):
    base = stack[0]
    assert call(base, "/v1/skills", "op_sub", "POST", {**SKILL, "name": "Bad Name"})[0] == 400
    assert call(base, "/v1/skills", "op_sub", "POST", {**SKILL, "version": "v1"})[0] == 400
    assert call(base, "/v1/skills", "op_sub2", "POST", {**SKILL, "content": "x" * 3000})[0] == 413
    for i in range(3):
        call(base, "/v1/skills", "op_sub", "POST", {**SKILL, "version": f"1.0.{i + 1}"})
    assert call(base, "/v1/skills", "op_sub", "POST", {**SKILL, "version": "2.0.0"})[0] == 429


def test_client_tenant_headers_are_ignored_and_unknown_routes_404(stack):
    req = urllib.request.Request(stack[0] + "/v1/skills", data=json.dumps(SKILL).encode(), method="POST",
                                 headers={"Authorization": "Bearer op_sub", "X-AXE-Tenant": "pub", "Content-Type": "application/json"})
    assert urllib.request.urlopen(req).status == 201
    assert call(stack[0], "/v1/skills/my-skill", "op_sub")[0] == 404
    assert call(stack[0], "/v1/audit", "op_sub")[0] == 404
    assert call(stack[0], "/v1/skills/hello", "op_sub", "DELETE")[0] == 405


def test_audit_log_records_hashed_identity_only(stack):
    call(stack[0], "/v1/skills/hello", "op_sub")
    text = (stack[1] / "audit.jsonl").read_text()
    assert "a@x.io" not in text and '"s": 200' in text


def test_legacy_beta_maps_active_accounts_until_subscriptions_ship(tmp_path):
    ver = ThreadingHTTPServer(("127.0.0.1", 0), _Verify)
    vurl = _serve(ver)
    try:
        legacy = Authenticator(vurl, {"beta"}, legacy_beta=True, ttl=0, miss_ttl=0)
        assert legacy.check("op_nosub").plan == "beta"
        strict = Authenticator(vurl, {"beta"}, legacy_beta=False, ttl=0, miss_ttl=0)
        with pytest.raises(Exception):
            strict.check("op_nosub")
    finally:
        ver.shutdown()
