"""Marketplace gateway: the one authenticated door in front of the skills hub.

Every call must carry an Operator bearer token. The token is verified against AuthGate, the account must
be active and hold a subscription, and only then is the call proxied: reads to the public read-only hub,
writes to a separate write-enabled hub under a tenant derived from the account. The client never names a
tenant, and nothing a user publishes can arrive verified.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")
FORMATS = {"skillmd", "markdown", "python", "catalog"}
READ_PATHS = ("/v1/skills", "/v1/tools/find")


class Entitlement:
    def __init__(self, account: str, plan: str):
        self.account = account
        self.plan = plan

    @property
    def tenant(self) -> str:
        return "u-" + hashlib.sha256(self.account.encode()).hexdigest()[:16]


class Denied(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class Authenticator:
    """Bearer token to Entitlement through AuthGate's /operator/verify, cached briefly in both directions.

    AuthGate answers `subscription: {plan, status}` once it carries subscriptions. Until then `legacy_beta`
    reads an active account as plan "beta", so existing testers keep working and a new sign-up with
    no active account is still refused.
    """

    def __init__(self, verify_url: str, plans: set[str], legacy_beta: bool, ttl: float = 60.0, miss_ttl: float = 10.0):
        self.verify_url, self.plans, self.legacy_beta = verify_url, plans, legacy_beta
        self.ttl, self.miss_ttl = ttl, miss_ttl
        self._cache: dict[str, tuple[float, Entitlement | Denied]] = {}
        self._lock = threading.Lock()

    def _lookup(self, token: str) -> Entitlement:
        req = urllib.request.Request(self.verify_url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise Denied(401 if e.code == 401 else 403, "not_signed_in" if e.code == 401 else "account_not_active",
                             "sign in with an active account")
            raise Denied(503, "auth_unavailable", "identity service error")
        except Exception:
            raise Denied(503, "auth_unavailable", "identity service unreachable")
        acct = body.get("account") or {}
        who = acct.get("external_id") or acct.get("email")
        if not who or acct.get("status") != "active":
            raise Denied(403, "account_not_active", "account is not active")
        sub = body.get("subscription")
        if sub is None and self.legacy_beta:
            sub = {"plan": "beta", "status": "active"}
        if not sub or sub.get("status") != "active" or sub.get("plan") not in self.plans:
            raise Denied(403, "subscription_required", "an active subscription is required for the marketplace")
        return Entitlement(who, sub["plan"])

    def check(self, token: str) -> Entitlement:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
        if hit and hit[0] > now:
            if isinstance(hit[1], Denied):
                raise hit[1]
            return hit[1]
        try:
            ent = self._lookup(token)
        except Denied as d:
            if d.status != 503:
                with self._lock:
                    self._cache[key] = (now + self.miss_ttl, d)
            raise
        with self._lock:
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[key] = (now + self.ttl, ent)
        return ent


class RateLimiter:
    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(who, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


class _Handler(BaseHTTPRequestHandler):
    auth: Authenticator
    limiter: RateLimiter
    read_upstream: str
    write_upstream: str
    max_body: int
    audit_path: str | None
    registry = None
    _known: set = set()

    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _err(self, status: int, code: str, detail: str):
        self._send(status, json.dumps({"error": code, "detail": detail}).encode())

    def _audit(self, ent: Entitlement | None, status: int):
        if not self.audit_path:
            return
        who = hashlib.sha256(ent.account.encode()).hexdigest()[:12] if ent else "-"
        line = json.dumps({"t": int(time.time()), "who": who, "m": self.command,
                           "p": urlparse(self.path).path, "s": status})
        try:
            with open(self.audit_path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _forward(self, base: str, ent: Entitlement | None, body: bytes | None = None) -> tuple[int, bytes, str]:
        headers = {"Accept": "application/json", "User-Agent": "axe-marketplace-gateway"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if ent is not None:
            headers["X-AXE-Tenant"] = ent.tenant
        req = urllib.request.Request(base + self.path, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "application/json")
        except Exception:
            return 502, json.dumps({"error": "upstream_unavailable"}).encode(), "application/json"

    def _entitlement(self) -> Entitlement:
        h = self.headers.get("Authorization", "")
        if not h.lower().startswith("bearer ") or not h.split(" ", 1)[1].strip():
            raise Denied(401, "not_signed_in", "sign in to use the marketplace")
        return self.auth.check(h.split(" ", 1)[1].strip())

    def _read_body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise Denied(400, "bad_request", "bad Content-Length")
        if n <= 0:
            raise Denied(400, "bad_request", "empty body")
        if n > self.max_body:
            raise Denied(413, "too_large", f"body over {self.max_body} bytes")
        return self.rfile.read(n)

    def do_GET(self):
        ent = None
        status = 500
        try:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/healthz":
                status = 200
                return self._send(200, b'{"status":"ok"}')
            if not any(path == p or path.startswith(p + "/") for p in READ_PATHS):
                raise Denied(404, "not_found", "no such route")
            ent = self._entitlement()
            mine = parse_qs(urlparse(self.path).query).get("scope", [""])[0] == "mine"
            status, data, ctype = self._forward(self.write_upstream if mine else self.read_upstream, ent if mine else None)
            self._send(status, data, ctype)
        except Denied as d:
            status = d.status
            self._err(d.status, d.code, d.detail)
        finally:
            self._audit(ent, status)

    do_HEAD = do_GET

    def do_POST(self):
        ent = None
        status = 500
        try:
            path = urlparse(self.path).path.rstrip("/")
            publish = path == "/v1/skills"
            outcome = path.startswith("/v1/skills/") and path.endswith("/outcome")
            if not (publish or outcome):
                raise Denied(404, "not_found", "no such route")
            ent = self._entitlement()
            if not self.limiter.allow(ent.account):
                raise Denied(429, "rate_limited", "too many writes; try again later")
            raw = self._read_body()
            try:
                body = json.loads(raw)
            except ValueError:
                raise Denied(400, "bad_request", "invalid JSON")
            if not isinstance(body, dict):
                raise Denied(400, "bad_request", "body must be an object")
            if publish:
                body = self._vet_publish(body, ent)
            self._ensure_tenant(ent)
            status, data, ctype = self._forward(self.write_upstream, ent, json.dumps(body).encode())
            self._send(status, data, ctype)
        except Denied as d:
            status = d.status
            self._err(d.status, d.code, d.detail)
        finally:
            self._audit(ent, status)

    def _ensure_tenant(self, ent: Entitlement) -> None:
        if self.registry is None or ent.tenant in self._known:
            return
        from .store import Conflict
        try:
            self.registry.add_tenant(ent.tenant, "user")
        except Conflict:
            pass
        self._known.add(ent.tenant)

    def _no_method(self):
        self._err(405, "method_not_allowed", "this gateway only reads and publishes")

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _no_method

    def _vet_publish(self, body: dict, ent: Entitlement) -> dict:
        name, version, content = body.get("name"), body.get("version"), body.get("content")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise Denied(400, "bad_request", "name must be lowercase letters, digits, . _ - (max 64)")
        if not isinstance(version, str) or not VERSION_RE.match(version):
            raise Denied(400, "bad_request", "version must look like 1.2.3")
        if not isinstance(content, str) or not content.strip():
            raise Denied(400, "bad_request", "content is required")
        fmt = body.get("format", "skillmd")
        if fmt not in FORMATS:
            raise Denied(400, "bad_request", f"format must be one of {sorted(FORMATS)}")
        meta = body.get("metadata") or {}
        if not isinstance(meta, dict):
            raise Denied(400, "bad_request", "metadata must be an object")
        meta = {k: v for k, v in meta.items() if k not in ("quarantined", "verified", "source", "created_by", "tenant_id")}
        meta.update({"quarantined": True, "verified": False, "source": "user",
                     "created_by": hashlib.sha256(ent.account.encode()).hexdigest()[:12], "plan": ent.plan})
        return {"name": name, "version": version, "content": content, "format": fmt, "metadata": meta}


def make_gateway(auth: Authenticator, *, read_upstream: str, write_upstream: str, host: str = "127.0.0.1",
                 port: int = 0, max_body: int = 262144, writes_per_hour: int = 30,
                 audit_path: str | None = None, write_db: str | None = None) -> ThreadingHTTPServer:
    registry = None
    if write_db:
        from .store import Registry
        registry = Registry(write_db)
    attrs = {"registry": registry, "_known": set(), "auth": auth, "limiter": RateLimiter(writes_per_hour, 3600.0), "read_upstream": read_upstream.rstrip("/"),
             "write_upstream": write_upstream.rstrip("/"), "max_body": max_body, "audit_path": audit_path}
    server = ThreadingHTTPServer((host, port), type("_GW", (_Handler,), attrs))
    server.daemon_threads = True
    return server


def main() -> None:
    env = os.environ
    verify = env.get("AXE_MKT_VERIFY_URL")
    if not verify:
        raise SystemExit("AXE_MKT_VERIFY_URL is required")
    auth = Authenticator(verify, set((env.get("AXE_MKT_PLANS") or "beta,pro,team,enterprise").split(",")),
                         legacy_beta=env.get("AXE_MKT_LEGACY_BETA", "1") != "0")
    make_gateway(auth, read_upstream=env.get("AXE_MKT_READ_UPSTREAM", "http://127.0.0.1:8742"),
                 write_upstream=env.get("AXE_MKT_WRITE_UPSTREAM", "http://127.0.0.1:8744"),
                 host=env.get("AXE_MKT_HOST", "127.0.0.1"), port=int(env.get("AXE_MKT_PORT", "8743")),
                 audit_path=env.get("AXE_MKT_AUDIT"), write_db=env.get("AXE_MKT_WRITE_DB")).serve_forever()


if __name__ == "__main__":
    main()
