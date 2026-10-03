"""Invariant: tenant identity is resolved from X-AXE-Tenant or key mapping, never a bare query param when a key is present.

Binds to loopback only (127.0.0.1): this is an internal hub component. Production exposure must go through a reverse proxy enforcing TLS and rate limits.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from hub import catalog as catalog_mod
from hub import discover
from hub.evals import EvalStore, NoOpEvalStore as _NoOpEvalStore
from hub.store import Conflict, HubError, NotFound, Registry

OPENAPI_PATH = Path(__file__).parent / "openapi.json"
CATEGORIES_USAGE = "pick a category, then /v1/tools/find?category=<slug>&q=<task>"
# Sent on every response, as the rich build does. HSTS is left to the TLS edge: sending it over plain
# HTTP from here would be ignored by browsers and wrong for a loopback client.
SECURITY_HEADERS = (
    ("X-Frame-Options", "SAMEORIGIN"),
    ("Content-Security-Policy",
     "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: https: wss:; frame-ancestors 'self'"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("X-Content-Type-Options", "nosniff"),
)
_LOOPBACK = ("127.", "localhost", "[::1]", "::1")


class _Cache:
    """Small LRU of rendered bodies for a read-only origin, where the database cannot change under it."""

    def __init__(self, entries: int = 256, max_bytes: int = 2_000_000) -> None:
        self._d: collections.OrderedDict = collections.OrderedDict()
        self._lock = threading.Lock()
        self._entries, self._max = entries, max_bytes

    def get(self, key):
        with self._lock:
            v = self._d.get(key)
            if v is not None:
                self._d.move_to_end(key)
            return v

    def put(self, key, value: bytes) -> None:
        if len(value) > self._max:
            return
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self._entries:
                self._d.popitem(last=False)


class _Handler(BaseHTTPRequestHandler):
    registry: Registry
    eval_store: EvalStore
    key_map: dict[str, str]
    default_tenant: str | None
    db_path: Any
    allow_origin: str | None

    # A browser refuses a cross-origin read unless the response says it may
    # have it, so without this header the whole API is unreachable from any web
    # surface that is not this exact host -- which is every web surface we want
    # to embed a tool picker in. It is deliberately opt-in per deployment: the
    # operator origin sits behind Cloudflare Access, and echoing "*" there
    # would let any page a signed-in operator visits read the catalogue with
    # their session.
    ALLOW_ORIGIN: str | None = None

    # A public origin has no Access gate and no key in front of it, so the
    # server itself has to be the thing that cannot be written to. This is a
    # mode rather than a deployment convention because a convention is one
    # forgotten flag away from an anonymous publish endpoint: with it on, every
    # POST is refused before it is parsed, and the audit log -- which names
    # actors and tenants -- is not served at all.
    READ_ONLY: bool = False

    # Bound by make_server when the database carries the serving tables of an imported snapshot
    # (hub/schema_serve.sql); None means the plain registry path below serves everything.
    catalog: Any = None
    cache: Any = None
    openapi_doc: Any = None

    # An idle or half-open client must not hold a thread for ever.
    timeout = 30

    def handle_one_request(self) -> None:
        self._rid = "req_" + uuid.uuid4().hex[:24]
        self._head = False
        super().handle_one_request()

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _resolve_tenant(self) -> str | None:
        # A presented key always decides, even when it maps to nothing: falling
        # back on a bad key would silently upgrade a rejected caller to the
        # default tenant, which is the invariant this docstring names.
        # A read-only origin with a default tenant serves exactly that tenant to everyone: the header is
        # ignored, as it is on the build this replaces, so a caller cannot probe other tenants by name and
        # a stale client header ("public") does not turn a working catalogue into an empty one.
        if self.READ_ONLY and self.default_tenant:
            return self.default_tenant
        key = self.headers.get("X-AXE-Key")
        if key:
            return self.key_map.get(key)
        return self.headers.get("X-AXE-Tenant") or self.default_tenant

    def _resolve_tenant_for_write(self) -> str | None:
        # Deliberately does NOT honour default_tenant. That fallback exists so a
        # browser behind Cloudflare Access can READ the catalogue; letting it
        # also publish would mean every human who can open the site can write to
        # the registry under a tenant they never named. A write must present a
        # key or a tenant header.
        key = self.headers.get("X-AXE-Key")
        if key:
            return self.key_map.get(key)
        return self.headers.get("X-AXE-Tenant")

    def _qs(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _cors(self) -> None:
        origin = self.ALLOW_ORIGIN
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "X-AXE-Tenant, X-AXE-Key, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # Vary matters when the allowed origin is anything but "*": a shared
        # cache must not hand a response minted for one origin to another.
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Max-Age", "600")

    def _common(self) -> None:
        self.send_header("X-Request-Id", self._rid)
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)

    def _finish(self, data: bytes) -> None:
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not self._head:
            self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        # A cross-origin GET carrying X-AXE-Tenant is not a simple request, so
        # the browser preflights it. Without this the tenant header can never
        # be sent and every embedded caller is stuck on the default tenant.
        self.send_response(204)
        self._cors()
        self._common()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self._head = True
        self.do_GET()

    def _send_json(self, code: int, body: Any) -> None:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self._common()
        self._finish(data)

    def _error(self, code: int, kind: str, message: str, param: str | None = None) -> None:
        self._send_json(code, {"error": {"type": "invalid_request_error", "code": kind,
                                         "message": message, "param": param}})

    def _no_tenant(self) -> None:
        self._error(403, "forbidden", "no tenant could be resolved for this request; send X-AXE-Tenant")

    def _not_found(self, message: str = "not found") -> None:
        self._error(404, "not_found", message)

    def _send_text(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "public, max-age=3600")
        self._cors()
        self._common()
        self._finish(data)

    def _send_html(self, code: int, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=300, stale-while-revalidate=86400")
        self.send_header("Vary", "Accept")
        self._common()
        self._finish(data)

    def _base(self) -> str:
        """Scheme and host this request arrived on; the install string follows it."""
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        if not proto:
            proto = "http" if host.startswith(_LOOPBACK) else "https"
        return f"{proto}://{host}"

    def _cached(self, key: tuple, render) -> str:
        """Rendered body for key. Cached only where the database is read-only, so it cannot go stale."""
        if self.cache is None or not self.READ_ONLY:
            return render()
        hit = self.cache.get(key)
        if hit is None:
            hit = render().encode()
            self.cache.put(key, hit)
        return hit.decode()

    # A tenant here holds 83,408 skills, so an unbounded list is not a
    # convenience -- /v1/skills was returning all 89,904 rows and the HTML
    # catalogue was a 21 MB response. Defaults are generous enough that small
    # tenants and the existing tests see whole result sets unchanged, and the
    # cap means one careless call cannot pin the box.
    # Overridable per deployment via make_server(): the right page size depends
    # on how big the tenant is and what is calling, and neither is knowable
    # here. These are the defaults, not the policy.
    PAGE_DEFAULT = 200
    PAGE_MAX = 1000
    HTML_DEFAULT = 500

    def _limit_offset(self, default: int | None = None) -> tuple[int, int]:
        qs = self._qs()

        def num(key, fallback):
            try:
                return max(0, int((qs.get(key) or [fallback])[0]))
            except (TypeError, ValueError):
                return fallback

        return min(num("limit", default or self.PAGE_DEFAULT), self.PAGE_MAX), num("offset", 0)

    def _page(self, rows: list, default: int | None = None) -> list:
        limit, offset = self._limit_offset(default)
        return rows[offset:offset + limit]

    def _limit_error(self, message: str) -> None:
        # The build this replaces repeats `param` at the top level of its limit errors; copied so a
        # client that reads either place keeps working.
        self._send_json(400, {"error": {"type": "invalid_request_error", "code": "bad_request",
                                        "message": message, "param": "limit"}, "param": "limit"})

    def _find_params(self) -> tuple[str, int, bool, str | None, bool] | None:
        """(query, limit, capped, category, verified_only), or None after sending the 400."""
        qs = self._qs()
        q = (qs.get("q") or qs.get("task") or [""])[0]
        if not q.strip():
            self._error(400, "bad_request", "q (or task) is required")
            return None
        raw = (qs.get("limit") or ["10"])[0]
        try:
            limit = int(raw)
        except ValueError:
            self._limit_error("limit must be an integer")
            return None
        if limit < 1:
            self._limit_error("limit must be at least 1")
            return None
        capped = limit > 50
        cat = (qs.get("category") or [None])[0] or None
        verified = (qs.get("verified") or ["0"])[0] in ("1", "true", "yes")
        return q, min(limit, 50), capped, cat, verified

    def _get_catalog_routes(self, path: str) -> bool:
        """Routes served from the imported snapshot. True when the request was answered."""
        cat = self.catalog
        if path == "/openapi.json":
            doc = dict(self.openapi_doc)
            doc["servers"] = [{"url": self._base()}]
            self._send_json(200, doc)
            return True
        if path not in ("/v1/skills", "/v1/skills/search", "/v1/categories", "/v1/tools/find",
                        "/v1/skills/find") and not path.startswith("/v1/skills/"):
            return False
        tenant = self._resolve_tenant()
        if not tenant:
            self._no_tenant()
            return True
        qs = self._qs()
        raw_query = urlparse(self.path).query
        base = self._base()

        if path == "/v1/categories":
            cats = cat.categories(tenant)
            self._send_json(200, {"count": len(cats), "categories": cats, "usage": CATEGORIES_USAGE})
            return True

        if path == "/v1/skills":
            limit, offset = self._limit_offset()
            envelope = (qs.get("envelope") or [""])[0] in ("1", "true", "yes")

            def render() -> str:
                rows = cat.list_page(tenant, limit, offset)
                if envelope:
                    total = cat.total(tenant)
                    body = (f'{{"object": "list", "data": [{", ".join(rows)}], "limit": {limit}, '
                            f'"offset": {offset}, "total": {total}, '
                            f'"has_more": {"true" if offset + len(rows) < total else "false"}}}')
                else:
                    body = "[" + ", ".join(rows) + "]"
                return body.replace(catalog_mod.HOST_TOKEN, base)

            self._send_json(200, self._cached((tenant, base, path, limit, offset, envelope), render))
            return True

        if path == "/v1/skills/search":
            q = (qs.get("q") or [""])[0]
            if not q.strip():
                self._error(400, "bad_request", "q (or task) is required")
                return True
            limit, offset = self._limit_offset()
            self._send_json(200, self._cached((tenant, base, path, q, limit, offset), lambda: (
                "[" + ", ".join(cat.search(tenant, q, limit, offset)) + "]"
            ).replace(catalog_mod.HOST_TOKEN, base)))
            return True

        if path in ("/v1/tools/find", "/v1/skills/find"):
            params = self._find_params()
            if params is None:
                return True
            q, limit, capped, category, verified = params

            def render() -> str:
                out = cat.find(tenant, q, limit, category, verified)
                if capped:
                    out["limit_capped"] = True
                    out["note_limit"] = "limit was reduced to the maximum of 50"
                return json.dumps(out).replace(catalog_mod.HOST_TOKEN, base)

            self._send_json(200, self._cached((tenant, base, path, raw_query), render))
            return True

        if path.endswith("/versions"):
            name = unquote(path[len("/v1/skills/"):-len("/versions")])
            versions = cat.versions(tenant, name)
            if versions is None:
                self._not_found(f"skill '{name}' not found")
            else:
                self._send_json(200, versions)
            return True

        name = unquote(path[len("/v1/skills/"):])
        version = (qs.get("version") or [None])[0]
        # A GET never writes. The audit row this route used to append on every read (and the caller-chosen
        # actor it recorded) is gone: reads are not publication events, and a public origin must not be
        # able to grow its own database from anonymous traffic.
        body = cat.get(tenant, name, version)
        if body is None:
            self._not_found()
            return True
        body = body.replace(catalog_mod.HOST_TOKEN, base)
        ev = self._latest_eval(tenant, name, version)
        if ev:
            body = json.dumps({**json.loads(body), "eval": ev})
        self._send_json(200, body)
        return True

    def _latest_eval(self, tenant: str, name: str, version: str | None):
        try:
            if isinstance(self.eval_store, _NoOpEvalStore):
                return None
            skill = self.registry.resolve(tenant, name, version)
            return self.eval_store.latest(tenant, name, skill.version)
        except (NotFound, NotImplementedError):
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return

        if self.catalog is not None and self._get_catalog_routes(path):
            return

        if path == "/v1/skills":
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            self._send_json(200, self._page(self.registry.list(tenant)))
            return

        if path == "/v1/skills/search":
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            q = (self._qs().get("q") or [""])[0]
            # Paged for the same reason the list is: a short query here matches
            # a large fraction of an 83k catalogue (a one-word prefix search
            # returned every row), so an unpaged search is a bigger response
            # than the unpaged list it was meant to be an alternative to.
            self._send_json(200, self._page(self.registry.search(tenant, q)))
            return

        if path in ("/v1/tools/find", "/v1/skills/find"):
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            params = self._find_params()
            if params is None:
                return
            q, limit, capped, cat, verified = params
            hits = discover.rank(self.db_path, tenant, q, limit=limit,
                                 category=cat, verified_only=verified)
            # The query is echoed because an agent that fired several searches
            # needs to tell the answers apart, and `count` because "no tool for
            # this" is a real, useful answer that an empty list states weakly.
            body = {"query": q, "count": len(hits), "results": hits, "limit": limit}
            if capped:
                body["limit_capped"] = True
                body["note_limit"] = "limit was reduced to the maximum of 50"
            self._send_json(200, body)
            return

        if path.startswith("/v1/skills/") and path.endswith("/versions"):
            name = unquote(path[len("/v1/skills/"):-len("/versions")])
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            self._send_json(200, self.registry.versions(tenant, name))
            return

        if path.startswith("/v1/skills/"):
            name = unquote(path[len("/v1/skills/"):])
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            qs = self._qs()
            version = (qs.get("version") or [None])[0]
            try:
                skill = self.registry.resolve(tenant, name, version)
            except NotFound:
                self._not_found()
                return
            body = skill.record()
            body["content"] = skill.content
            ev = self._latest_eval(tenant, name, version)
            if ev:
                body["eval"] = ev
            self._send_json(200, body)
            return

        if path == "/v1/audit":
            if self.READ_ONLY:
                # The audit trail names actors and tenants. It is an operator
                # tool, not catalogue data, so a public origin does not have it.
                self._not_found()
                return
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            self._send_json(200, self._page(self.registry.audit(tenant)))
            return

        if path in ("/robots.txt", "/llms.txt", "/.well-known/agent-skills.json"):
            from hub import discovery
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
            if path == "/robots.txt":
                self._send_text(200, discovery.render_robots(host))
            elif path == "/llms.txt":
                self._send_text(200, discovery.render_llms_txt(host), "text/markdown; charset=utf-8")
            else:
                self._send_text(200, json.dumps(discovery.render_agent_doc(host), indent=2), "application/json")
            return

        if path.startswith("/docs/skills"):
            # The browsable catalogue index: a static shell that fetches the public
            # read API (/v1/skills, /v1/skills/search) client-side — search box,
            # category chips, and skill cards linking to /portal/<name>. No tenant
            # or private portal needed (same public surface as the markdown docs).
            try:
                from hub.axeskills_docs_surface import render_skills_browse
            except ImportError:
                from axeskills_docs_surface import render_skills_browse
            self._send_html(200, render_skills_browse())
            return

        # The repo's markdown docs. Reachable on the public origin without a
        # tenant: they describe how to integrate, so gating them behind the
        # header a reader is trying to learn about would be circular. Ordered
        # after /docs/skills, which owns its own prefix.
        if path == "/docs" or path.startswith("/docs/"):
            # serve.py is imported both as `hub.serve` (the runners) and as a
            # top-level module (`python hub/serve.py`), and only one of those
            # puts hub/ on sys.path -- so the sibling import needs both forms.
            try:
                from hub.axeskills_docs_surface import (
                    render_doc, render_index as docs_index)
            except ImportError:
                from axeskills_docs_surface import (
                    render_doc, render_index as docs_index)

            if path in ("/docs", "/docs/"):
                self._send_html(200, docs_index())
                return
            page = render_doc(path[len("/docs/"):].strip("/"))
            if page is None:
                self._not_found("no such doc")
                return
            self._send_html(200, page)
            return

        if path.startswith("/portal"):
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            name = path[len("/portal/"):] if path not in ("/portal", "/portal/") else ""
            if name:
                qs = self._qs()
                version = (qs.get("version") or [None])[0]
                try:
                    skill = self.registry.resolve(tenant, name, version)
                except NotFound:
                    self._not_found()
                    return
                versions = self.registry.versions(tenant, name)
                ev = self.eval_store.latest(tenant, name, skill.version)
                from hub.portal import render_skill
                self._send_html(200, render_skill(skill, versions, ev))
            else:
                from hub.portal import render_catalog
                skills = self._page(
                    self.registry.list(tenant, include_yanked=True),
                    default=self.HTML_DEFAULT,
                )
                self._send_html(200, render_catalog(tenant, skills))
            return

        if path in ("/", ""):
            # The browsable index answers at the root with a 200, as the rich build does;
            # /portal keeps the flat view for anyone who wants it.
            try:
                from hub.axeskills_docs_surface import render_skills_browse
            except ImportError:
                from axeskills_docs_surface import render_skills_browse
            self._send_html(200, render_skills_browse())
            return

        self._not_found()


    def _method_not_allowed(self) -> None:
        data = json.dumps({"error": {"type": "invalid_request_error", "code": "method_not_allowed",
                                     "message": "this origin is read-only; use GET, HEAD or OPTIONS",
                                     "param": None}}).encode()
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self._cors()
        self._common()
        self._finish(data)

    def do_PUT(self) -> None:
        self._method_not_allowed()

    do_PATCH = do_DELETE = do_PUT

    def do_POST(self) -> None:
        if self.READ_ONLY:
            # Refused before the body is read: nothing about the request can
            # talk this origin into a write.
            self._method_not_allowed()
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/v1/skills":
            # Agents add skills over HTTP so the hub is usable from a fleet node
            # with no checkout. Immutability stays the registry's job, not this
            # handler's: republishing a version raises and comes back as 409, so
            # a retrying agent cannot quietly redefine a version something else
            # has already run.
            tenant = self._resolve_tenant_for_write()
            if not tenant:
                self._error(403, "forbidden", "writes require X-AXE-Key or X-AXE-Tenant")
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                self._error(400, "bad_request", "invalid JSON")
                return
            missing = [f for f in ("name", "version", "content") if not body.get(f)]
            if missing:
                self._error(400, "bad_request", f"missing required fields: {missing}")
                return
            try:
                skill = self.registry.publish(
                    tenant,
                    body["name"],
                    body["version"],
                    body["content"],
                    actor=tenant,
                    format=body.get("format", "skillmd"),
                    metadata=body.get("metadata"),
                )
            except NotFound as e:
                self._not_found(str(e))
                return
            except Conflict as e:
                self._error(409, "conflict", str(e))
                return
            except HubError as e:
                self._error(400, "bad_request", str(e))
                return
            self._send_json(201, skill.record())
            return

        if path.startswith("/v1/skills/") and path.endswith("/outcome"):
            name = path[len("/v1/skills/"):-len("/outcome")]
            tenant = self._resolve_tenant()
            if not tenant:
                self._no_tenant()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except Exception:
                self._error(400, "bad_request", "invalid JSON")
                return
            version = body.get("version")
            outcome = body.get("outcome")
            if not version or not outcome:
                self._error(400, "bad_request", "version and outcome are required")
                return
            if outcome not in ("success", "failure", "error"):
                self._error(400, "bad_request", "outcome must be success, failure, or error")
                return
            try:
                self.registry.record_outcome(
                    tenant,
                    name,
                    version,
                    actor=tenant,
                    outcome=outcome,
                    session_id=body.get("session_id"),
                    error_msg=body.get("error_msg"),
                    latency_ms=body.get("latency_ms"),
                )
            except NotFound:
                self._not_found()
                return
            self._send_json(200, {"recorded": True})
            return

        self._not_found()

def make_server(
    registry: Registry,
    eval_store: EvalStore,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    key_map: dict[str, str] | None = None,
    default_tenant: str | None = None,
    allow_origin: str | None = None,
    read_only: bool = False,
    page_default: int | None = None,
    page_max: int | None = None,
    html_default: int | None = None,
) -> ThreadingHTTPServer:
    # default_tenant serves headerless callers -- i.e. a browser behind
    # Cloudflare Access, which cannot set X-AXE-Tenant. Off unless asked for,
    # so the API surface and its tests keep 403-ing on a missing tenant.
    attrs = {
        "registry": registry,
        "eval_store": eval_store,
        "key_map": key_map or {},
        "default_tenant": default_tenant,
        # Discovery reads the catalogue read-only and by path, so it needs the
        # path rather than the Registry: it deliberately cannot write.
        "db_path": registry._path,
    }
    if allow_origin:
        attrs["ALLOW_ORIGIN"] = allow_origin
    if read_only:
        attrs["READ_ONLY"] = True
        # A read-only origin must not carry keys it cannot use, and a key that
        # maps to a writable tenant has no meaning here.
        attrs["key_map"] = {}
    for name, value in (
        ("PAGE_DEFAULT", page_default),
        ("PAGE_MAX", page_max),
        ("HTML_DEFAULT", html_default),
    ):
        if value is not None:
            attrs[name] = value
    if catalog_mod.available(registry._path):
        cat = catalog_mod.Catalog(registry._path)
        attrs["catalog"] = cat
        attrs["cache"] = _Cache()
        attrs["openapi_doc"] = json.loads(OPENAPI_PATH.read_text())
        # Build the find index before the socket opens, so the first caller does not pay for it.
        if default_tenant:
            cat.warm(default_tenant)
    handler = type("_BoundHandler", (_Handler,), attrs)
    server = ThreadingHTTPServer((host, port), handler)
    # Per-connection threads must not outlive the server or pile up behind a client that never closes.
    server.daemon_threads = True
    return server


def serve(db_path: Path, eval_db_path: Path | None, *, host: str = "127.0.0.1", port: int = 8741,
          key_map: dict[str, str] | None = None, default_tenant: str | None = None,
          allow_origin: str | None = None, read_only: bool = False) -> None:
    registry = Registry(db_path)
    eval_store = EvalStore(eval_db_path) if eval_db_path else _NoOpEvalStore()
    make_server(registry, eval_store, host=host, port=port, key_map=key_map,
                default_tenant=default_tenant, allow_origin=allow_origin,
                read_only=read_only).serve_forever()


def main() -> None:
    """Run from the environment, which is how the launchd job is configured (see README)."""
    env = os.environ
    db = Path(env.get("AXE_HUB_DB") or Path.home() / ".axe" / "hub" / "hub.db").expanduser()
    eval_db = env.get("AXE_HUB_EVAL_DB")
    serve(db, Path(eval_db).expanduser() if eval_db else None,
          host=env.get("AXE_HUB_HOST", "127.0.0.1"), port=int(env.get("AXE_HUB_PORT", "8742")),
          default_tenant=env.get("AXE_HUB_DEFAULT_TENANT"),
          allow_origin=env.get("AXE_HUB_ALLOW_ORIGIN"),
          read_only=env.get("AXE_HUB_READ_ONLY", "1") != "0")


if __name__ == "__main__":
    main()
