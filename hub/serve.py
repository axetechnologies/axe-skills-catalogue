"""Invariant: tenant identity is resolved from X-AXE-Tenant or key mapping, never a bare query param when a key is present.

Binds to loopback only (127.0.0.1): this is an internal hub component. Production exposure must go through a reverse proxy enforcing TLS and rate limits.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from hub import discover
from hub.evals import EvalStore
from hub.store import Conflict, HubError, NotFound, Registry


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

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _resolve_tenant(self) -> str | None:
        # A presented key always decides, even when it maps to nothing: falling
        # back on a bad key would silently upgrade a rejected caller to the
        # default tenant, which is the invariant this docstring names.
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

    def do_OPTIONS(self) -> None:
        # A cross-origin GET carrying X-AXE-Tenant is not a simple request, so
        # the browser preflights it. Without this the tenant header can never
        # be sent and every embedded caller is stuck on the default tenant.
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, code: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code: int, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

    def _page(self, rows: list, default: int | None = None) -> list:
        qs = self._qs()

        def num(key, fallback):
            try:
                return max(0, int((qs.get(key) or [fallback])[0]))
            except (TypeError, ValueError):
                return fallback

        limit = min(num("limit", default or self.PAGE_DEFAULT), self.PAGE_MAX)
        offset = num("offset", 0)
        return rows[offset:offset + limit]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/v1/skills":
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            self._send_json(200, self._page(self.registry.list(tenant)))
            return

        if path == "/v1/skills/search":
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
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
                self._send_json(403, {"error": "missing tenant"})
                return
            qs = self._qs()
            q = (qs.get("q") or qs.get("task") or [""])[0]
            if not q.strip():
                self._send_json(400, {"error": "q (or task) is required"})
                return
            try:
                limit = max(1, min(int((qs.get("limit") or ["10"])[0]), 50))
            except (TypeError, ValueError):
                limit = 10
            cat = (qs.get("category") or [None])[0]
            verified = (qs.get("verified") or ["0"])[0] in ("1", "true", "yes")
            hits = discover.rank(self.db_path, tenant, q, limit=limit,
                                 category=cat, verified_only=verified)
            # The query is echoed because an agent that fired several searches
            # needs to tell the answers apart, and `count` because "no tool for
            # this" is a real, useful answer that an empty list states weakly.
            self._send_json(200, {"query": q, "count": len(hits), "results": hits})
            return

        if path.startswith("/v1/skills/") and path.endswith("/versions"):
            name = path[len("/v1/skills/"):-len("/versions")]
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            self._send_json(200, self.registry.versions(tenant, name))
            return

        if path.startswith("/v1/skills/"):
            name = path[len("/v1/skills/"):]
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            qs = self._qs()
            version = (qs.get("version") or [None])[0]
            actor = (qs.get("_actor") or ["api"])[0]
            try:
                skill = self.registry.fetch(tenant, name, version, actor=actor)
            except NotFound:
                self._send_json(404, {"error": "not found"})
                return
            body = skill.record()
            body["content"] = skill.content
            ev = self.eval_store.latest(tenant, name, skill.version)
            if ev:
                body["eval"] = ev
            self._send_json(200, body)
            return

        if path == "/v1/audit":
            if self.READ_ONLY:
                # The audit trail names actors and tenants. It is an operator
                # tool, not catalogue data, so a public origin does not have it.
                self._send_json(404, {"error": "not found"})
                return
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            self._send_json(200, self._page(self.registry.audit(tenant)))
            return

        if path.startswith("/docs/skills"):
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            from axeskills_operator_portal import (
                OperatorCatalog,
                render_category,
                render_index,
                render_search,
            )

            cat = OperatorCatalog(self.registry._path, tenant)
            qs = self._qs()
            try:
                page = max(int((qs.get("page") or ["1"])[0]), 1)
            except ValueError:
                page = 1

            rest = path[len("/docs/skills"):]
            if rest.startswith("/c/") or rest == "/search":
                # The category sidebar is part of the page frame, so a listing
                # needs the same counts the index does. summary() is one pass
                # over a temp table, not three scans -- see OperatorCatalog.
                cats, total, _srcs, _tiers = cat.summary()
                if rest == "/search":
                    q = (qs.get("q") or [""])[0].strip()
                    self._send_html(200, render_search(
                        q, cat.search(q, page) if q else [], page, cats, total))
                else:
                    slug = rest[len("/c/"):]
                    label = next((c.label for c in cats if c.category == slug), slug)
                    self._send_html(200, render_category(
                        slug, label, cat.by_category(slug, page), page, cats, total))
            else:
                # A ?q= on the index used to be dropped on the floor: the page
                # rendered unfiltered and still answered 200, so a caller could
                # not tell its search had been ignored. Searching is one URL.
                q = (qs.get("q") or [""])[0].strip()
                if q:
                    target = "/docs/skills/search?q=" + quote(q, safe="")
                    if page > 1:
                        target += "&page=%d" % page
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                cats, total, srcs, tiers = cat.summary()
                self._send_html(200, render_index(cats, total, srcs, tiers))
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
                self._send_json(404, {"error": "no such doc",
                                      "index": "/docs"})
                return
            self._send_html(200, page)
            return

        if path.startswith("/portal"):
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            name = path[len("/portal/"):] if path not in ("/portal", "/portal/") else ""
            if name:
                qs = self._qs()
                version = (qs.get("version") or [None])[0]
                try:
                    skill = self.registry.resolve(tenant, name, version)
                except NotFound:
                    self._send_json(404, {"error": "not found"})
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
            # The root used to serve hub.portal's flat table: 500 rows of a
            # 83k catalogue, no categories, no search. That is a debugging
            # view, not a landing page. /docs/skills is the browsable index,
            # so root redirects there and /portal keeps the flat view for
            # anyone who wants it.
            self.send_response(302)
            self.send_header("Location", "/docs/skills")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self._send_json(404, {"error": "not found"})


    def do_POST(self) -> None:
        if self.READ_ONLY:
            # Refused before the body is read: nothing about the request can
            # talk this origin into a write.
            self.send_response(405)
            self.send_header("Allow", "GET, OPTIONS")
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
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
                self._send_json(403, {"error": "writes require X-AXE-Key or X-AXE-Tenant"})
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                self._send_json(400, {"error": "invalid JSON"})
                return
            missing = [f for f in ("name", "version", "content") if not body.get(f)]
            if missing:
                self._send_json(400, {"error": f"missing required fields: {missing}"})
                return
            try:
                skill = self.registry.publish(
                    tenant,
                    body["name"],
                    body["version"],
                    body["content"],
                    actor=body.get("actor") or tenant,
                    format=body.get("format", "skillmd"),
                    metadata=body.get("metadata"),
                )
            except NotFound as e:
                self._send_json(404, {"error": str(e)})
                return
            except Conflict as e:
                self._send_json(409, {"error": str(e)})
                return
            except HubError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(201, skill.record())
            return

        if path.startswith("/v1/skills/") and path.endswith("/outcome"):
            name = path[len("/v1/skills/"):-len("/outcome")]
            tenant = self._resolve_tenant()
            if not tenant:
                self._send_json(403, {"error": "missing tenant"})
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except Exception:
                self._send_json(400, {"error": "invalid JSON"})
                return
            version = body.get("version")
            outcome = body.get("outcome")
            if not version or not outcome:
                self._send_json(400, {"error": "version and outcome are required"})
                return
            if outcome not in ("success", "failure", "error"):
                self._send_json(400, {"error": f"outcome must be success, failure, or error"})
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
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, {"recorded": True})
            return

        self._send_json(404, {"error": "not found"})

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
) -> HTTPServer:
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
    handler = type("_BoundHandler", (_Handler,), attrs)
    return HTTPServer((host, port), handler)


def serve(db_path: Path, eval_db_path: Path, *, host: str = "127.0.0.1", port: int = 8741,
          key_map: dict[str, str] | None = None, default_tenant: str | None = None,
          allow_origin: str | None = None, read_only: bool = False) -> None:
    registry = Registry(db_path)
    eval_store = EvalStore(eval_db_path)
    make_server(registry, eval_store, host=host, port=port, key_map=key_map,
                default_tenant=default_tenant, allow_origin=allow_origin,
                read_only=read_only).serve_forever()
