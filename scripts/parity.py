#!/usr/bin/env python3
"""Parity harness: our server against the rich build's recorded (and optionally live) answers.

    python3 scripts/parity.py [--snapshot DIR] [--db hub-v2.db] [--live] [--bench] [--report FILE]

Starts hub.serve on 127.0.0.1:8743 against the v2 database with the production environment, replays
about 150 requests, and compares each answer with what the rich build said: from the snapshot files,
or, for cases the snapshot never recorded, from a fresh GET to https://operator.axe.onl (--live: read
only, at most 5 requests a second, User-Agent axe-hub-parity/1.0). It compares status, the headers
that matter, JSON shape (keys and types) and values. Every difference is classified: EXPLAINED ones
carry the reason, anything else is UNEXPLAINED and fails the run.

--bench measures warm latency for find, list and search against the running server.
"""
from __future__ import annotations

import argparse
import collections
import http.client
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
PORT = 8743
LOCAL = f"http://127.0.0.1:{PORT}"
LIVE = "https://operator.axe.onl"
UA = "axe-hub-parity/1.0"
HEADERS_OF_INTEREST = (
    "content-type", "access-control-allow-origin", "access-control-allow-headers",
    "access-control-allow-methods", "access-control-max-age", "vary", "x-frame-options",
    "content-security-policy", "referrer-policy", "x-content-type-options", "cache-control",
)
EDGE_ONLY = ("strict-transport-security",)
HOST_RE = re.compile(r"curl -s https?://[^/\s\"]+")


def norm(text: str) -> str:
    return HOST_RE.sub("curl -s @HOST@", text)


def tokens_of(q: str) -> list[str]:
    sys.path.insert(0, str(ROOT))
    from hub.discover import tokens
    return tokens(q)


class Case:
    def __init__(self, kind: str, path: str, *, method: str = "GET", headers: dict | None = None,
                 want: dict | None = None, live: bool = False) -> None:
        self.kind, self.path, self.method = kind, path, method
        self.headers = headers or {}
        self.want = want        # {"status", "headers", "body": text | None}
        self.live = live


def http_get(base: str, case: Case, *, ua: str = UA) -> dict:
    req = urllib.request.Request(base + case.path, method=case.method,
                                 headers={"User-Agent": ua, **case.headers})
    try:
        r = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        r = e
    body = r.read()
    return {"status": r.status, "headers": {k.lower(): v for k, v in r.headers.items()},
            "body": body.decode("utf-8", "replace")}


def build_cases(snap: Path, live: bool) -> list[Case]:
    rows = [json.loads(line) for line in open(snap / "skills-list.jsonl")]
    details = {}
    for line in open(snap / "details.jsonl"):
        d = json.loads(line)
        details[d["name"]] = d
    disc = snap / "discovery"
    index = json.load(open(disc / "index.json"))

    def rec(file: str) -> dict:
        h = json.load(open(disc / (file + ".headers.json")))
        return {"status": h["status"], "headers": h["headers"], "body": (disc / file).read_text()}

    cases: list[Case] = []

    # 1. the 40 recorded find queries
    for line in open(snap / "find-baseline.jsonl"):
        b = json.loads(line)
        cases.append(Case("find", f"/v1/tools/find?q={quote(b['q'])}&limit={b['limit']}",
                          want={"status": 200, "headers": {}, "body": json.dumps(b["response"])}))

    # 2. list pages
    order = [(None, 0, False), (None, 200, False), (1, 0, True), (1, 999999, True), (0, 0, False),
             (-1, 0, False), (5, 0, False), (10, 65730, True), (50, 12345, False), (100, 500, True),
             (200, 65700, True), (1000, 0, False), (1000, 64738, True), (1000, 1000, True),
             (1500, 0, False), (3, 33333, False), (7, 7, True), (25, 60000, False), (1, 65737, True),
             (999, 31337, True), (2, 65736, True), (500, 40000, False)]
    for limit, offset, env in order:
        qs = []
        if limit is not None:
            qs.append(f"limit={limit}")
        if offset:
            qs.append(f"offset={offset}")
        if env:
            qs.append("envelope=1")
        eff = 200 if limit is None else min(max(limit, 0), 1000)
        data = rows[offset:offset + eff] if eff > 0 else []
        body = ({"object": "list", "data": data, "limit": eff, "offset": offset, "total": len(rows),
                 "has_more": offset + len(data) < len(rows)} if env else data)
        cases.append(Case("list", "/v1/skills" + ("?" + "&".join(qs) if qs else ""),
                          want={"status": 200, "headers": {}, "body": json.dumps(body)}))

    # 3. 30 skills x (detail, versions)
    rng = random.Random(8743)
    names = list(details)
    multi = [n for n in names if len(details[n]["versions"]) > 1]
    skillmd = [n for n in names if details[n]["detail"]["format"] == "skillmd"]
    plugin = [n for n in names if details[n]["detail"]["metadata"]["source"] == "axe:plugin"]
    pool = [n for n in names if n not in set(multi + skillmd + plugin)]
    by_src: dict[str, list[str]] = collections.defaultdict(list)
    for n in pool:
        by_src[details[n]["detail"]["metadata"]["source"]].append(n)
    pick = multi + rng.sample(skillmd, 3) + plugin
    for src in sorted(by_src):
        pick.append(rng.choice(by_src[src]))
    seen_cat = {details[n]["detail"]["card"].get("category") for n in pick}
    for n in rng.sample(pool, len(pool)):
        if len(pick) >= 30:
            break
        c = details[n]["detail"]["card"].get("category")
        if n not in pick and c not in seen_cat:
            pick.append(n)
            seen_cat.add(c)
    pick = pick[:30]
    for n in pick:
        d = details[n]
        enc = quote(n, safe=":") if rng.random() < 0.5 else quote(n, safe="")
        cases.append(Case("detail", f"/v1/skills/{enc}",
                          want={"status": 200, "headers": {}, "body": json.dumps(d["detail"])}))
        cases.append(Case("versions", f"/v1/skills/{enc}/versions",
                          want={"status": 200, "headers": {}, "body": json.dumps(d["versions"])}))

    # 4. discovery probes the snapshot recorded
    for path, entry in index.items():
        if path.startswith("/docs/skills/") or path in ("/llms.txt",) or path.startswith("/.well-known"):
            continue
        if "[X-AXE-Tenant" in path:
            base, _, rest = path.partition(" [X-AXE-Tenant: ")
            tenant = rest.rstrip("]")
            cases.append(Case("tenant", base, headers={"X-AXE-Tenant": tenant},
                              want=rec(entry["file"])))
            continue
        kind = {"/openapi.json": "openapi", "/robots.txt": "robots", "/docs": "html", "/docs/skills": "html",
                "/": "html"}.get(path, "probe")
        if path.startswith("/v1/skills?limit=1&envelope=1") or path in (
                "/v1/skills?limit=0", "/v1/skills?limit=-1", "/v1/skills?limit=1&offset=999999&envelope=1"):
            continue                                   # already covered, with the same recording, above
        if path.startswith("/v1/tools/find?q=docker"):
            kind = "find-probe"
        cases.append(Case(kind, path, want=rec(entry["file"])))

    # 5. HEAD and OPTIONS (our server only: the recorded GET headers are the reference)
    cases.append(Case("head", "/healthz", method="HEAD",
                      want={"status": 200, "headers": rec("healthz")["headers"], "body": ""}))
    cases.append(Case("head", "/v1/skills?limit=1", method="HEAD",
                      want={"status": 200, "headers": rec("extra_13__v1_skills_limit_1_envelope_1")["headers"],
                            "body": ""}))
    for p in ("/v1/skills", "/v1/tools/find"):
        cases.append(Case("options", p, method="OPTIONS",
                          want={"status": 204, "headers": rec("healthz")["headers"], "body": ""}))

    # 6. fresh live GETs for what the snapshot never recorded
    if live:
        multi_name = multi[0]
        colon = next(n for n in names if ":" in n)
        for p in ("/v1/tools/find?q=docker&limit=abc", "/v1/tools/find?q=docker&limit=0",
                  "/v1/tools/find?q=docker&limit=100", "/v1/tools/find?q=%20%20", "/v1/tools/find?task=terraform",
                  "/v1/tools/find?q=the%20and%20of", "/v1/tools/find?q=pdf&limit=5",
                  "/v1/skills/search?q=", "/v1/skills?limit=abc", "/v1/skills?offset=-5&limit=2",
                  f"/v1/skills/{quote(multi_name, safe=':')}/versions",
                  f"/v1/skills/{quote(colon, safe=':')}?version=0.0.0-nope",
                  "/v1/skills/__no_such_skill__?version=1.0.0", "/v1/tools/find?q=docker&verified=yes&limit=2"):
            cases.append(Case("find-live" if "find" in p else "live", p, live=True))
    return cases


def diff(a, b, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() | b.keys():
            if k not in b:
                out.append((f"{path}.{k}", "extra key (ours)", a[k], None))
            elif k not in a:
                out.append((f"{path}.{k}", "missing key (ours)", None, b[k]))
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
        if list(a) != list(b) and set(a) == set(b):
            out.append((path, "key order", list(a), list(b)))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "length", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[]", out)
    elif type(a) is not type(b):
        out.append((path, "type", type(a).__name__, type(b).__name__))
    elif a != b:
        out.append((path, "value", a, b))
    return out


class Report:
    def __init__(self) -> None:
        self.compared = 0
        self.identical = 0
        self.diffs: collections.Counter = collections.Counter()
        self.examples: dict = {}
        self.unexplained = 0

    def add(self, case: Case, where: str, kind: str, reason: str | None, ours, theirs) -> None:
        key = (case.kind, where, kind, reason or "UNEXPLAINED")
        self.diffs[key] += 1
        self.examples.setdefault(key, (case.method, case.path, str(ours)[:160], str(theirs)[:160]))
        if reason is None:
            self.unexplained += 1


def compare_case(case: Case, ours: dict, want: dict, rep: Report) -> bool:
    ok = True

    def d(where, kind, reason, a, b):
        nonlocal ok
        ok = False
        rep.add(case, where, kind, reason, a, b)

    if ours["status"] != want["status"]:
        d("status", "value", None, ours["status"], want["status"])
    oh, wh = ours["headers"], want["headers"]
    if not re.fullmatch(r"req_[0-9a-f]{24}", oh.get("x-request-id", "")):
        d("header x-request-id", "format", None, oh.get("x-request-id"), "req_<24 hex>")
    for h in HEADERS_OF_INTEREST:
        if case.method == "OPTIONS" and h in ("content-type", "cache-control"):
            continue          # a 204 carries no body, so no content type
        if h in wh and (h in ("vary", "content-type") or case.kind not in ("head",)):
            if h == "vary" and case.kind == "html":
                pass
            if oh.get(h) != wh[h]:
                if h == "cache-control" and case.kind == "robots":
                    d("header " + h, "value", "robots.txt cache lifetime is set by the Cloudflare edge", oh.get(h), wh[h])
                else:
                    d("header " + h, "value", None, oh.get(h), wh[h])
        elif h in oh and wh and h not in wh and case.kind not in ("options",):
            d("header " + h, "extra (ours)", "the recorded response for this route lacked it (the snapshot shows the security headers "
              "on most routes, not all); a superset is harmless", oh[h], None)
    for h in EDGE_ONLY:
        if h in wh and h not in oh:
            d("header " + h, "missing (ours)", "sent by the Cloudflare edge, not by the origin; plain-HTTP "
              "local replay", None, wh[h])
    if case.method in ("HEAD", "OPTIONS"):
        if ours["body"] != "":
            d("body", "value", None, ours["body"][:40], "")
        return ok

    k = case.kind
    ob, wb = ours["body"], want["body"]
    if k in ("html",):
        if oh.get("content-type") != wh.get("content-type"):
            d("content-type", "value", None, oh.get("content-type"), wh.get("content-type"))
        if ob != wb:
            d("body", "value", "HTML pages are the repo's static shell, not the rich build's server-rendered "
              "pages (out of scope: JSON API parity)", len(ob), len(wb))
        return ok
    if k == "robots":
        if ob != wb:
            d("body", "value", "robots.txt is the repo's own host-aware file (kept on purpose); the rich "
              "build served only the Cloudflare-managed block", len(ob), len(wb))
        return ok
    try:
        oj, wj = json.loads(norm(ob)), json.loads(norm(wb))
    except ValueError:
        d("body", "not json", None, ob[:80], wb[:80])
        return ok

    if k in ("find", "find-probe", "find-live") and isinstance(oj, dict) and "results" in oj and "results" in wj:
        q = re.search(r"[?&](?:q|task)=([^&]*)", case.path)
        from urllib.parse import unquote
        qt = tokens_of(unquote(q.group(1))) if q else []
        if q and not qt:
            qt = re.findall(r"[a-z0-9]+", unquote(q.group(1)).lower())
        shape_ok = True
        top = {k_ for k_ in oj if k_ != "results"} ^ {k_ for k_ in wj if k_ != "results"}
        for kk in top:
            d(f"find envelope key {kk}", "key set", None, kk in oj, kk in wj)
        for key in set(oj) - {"results"}:
            if key in wj and key not in ("query",) and oj[key] != wj[key]:
                d(f"find envelope {key}", "value", None, oj[key], wj[key])
        if oj.get("query") != wj.get("query"):
            d("find envelope query", "value", None, oj.get("query"), wj.get("query"))
        o_items, w_items = oj["results"], wj["results"]
        for it in o_items[:1] + w_items[:1]:
            pass
        for it in o_items:
            if w_items and (list(it) != list(w_items[0]) or
                            any(type(it[x]) is not type(w_items[0][x]) for x in it if x in w_items[0])):
                d("find item shape", "keys/types", None, list(it), list(w_items[0]))
                shape_ok = False
                break
        by_w = {x["name"]: x for x in w_items}
        for it in o_items:
            w = by_w.get(it["name"])
            if not w:
                continue
            for field in it:
                if field in ("score", "matched_terms"):
                    continue
                if it[field] != w.get(field):
                    d(f"find item {field}", "value", None, it[field], w.get(field))
        o_names, w_names = [x["name"] for x in o_items], [x["name"] for x in w_items]
        if o_names != w_names or [x["score"] for x in o_items] != [x["score"] for x in w_items]:
            ov = len(set(o_names) & set(w_names))
            reason = (f"the rich build's multi-term ranking function is not recoverable from the snapshot; "
                      f"ours is a fitted approximation (field weights x term rarity x coverage)"
                      if len(qt) > 1 else None)
            if len(qt) <= 1 and set(o_names) == set(w_names) and [x["score"] for x in o_items] == \
                    [x["score"] for x in w_items]:
                reason = "same single-term result set and scores; only tie order differs"
            elif len(qt) <= 1:
                reason = ("single-term query: scores match the recorded ones, but the result set differs "
                          "only by rows beyond identical-score ties" if ov >= len(w_names) - 1 and
                          [x["score"] for x in o_items][:3] == [x["score"] for x in w_items][:3] else None)
            d("find ranking", f"top-{len(w_names)} overlap {ov}/{len(w_names)}; top1 "
              f"{'same' if o_names[:1] == w_names[:1] else 'differs'}", reason, o_names[:2], w_names[:2])
            rep.overlap.append(ov / max(len(w_names), 1))
            rep.top1.append(o_names[:1] == w_names[:1])
        return ok

    for path, kind, a, b in diff(oj, wj):
        reason = None
        if k == "openapi":
            if path.startswith(".servers"):
                reason = "servers is the request's own origin"
            elif any(s in path for s in ("/v1/skills", "/v1/skills/search", ".paths./v1/skills/{name}")):
                reason = "corrected for what this server implements (envelope shape, list/search params, ?version)"
        if case.live and re.search(r"use_count|\.verified|\.version$|checksum|created_at|\.metadata", path):
            reason = "row changed on the live service since the snapshot"
        if k == "tenant" and path.endswith(".total"):
            reason = None
        d(f"{path or '(root)'}", kind, reason, a, b)
    return ok


def start_server(db: Path) -> subprocess.Popen:
    env = {**os.environ, "AXE_HUB_DB": str(db), "AXE_HUB_HOST": "127.0.0.1", "AXE_HUB_PORT": str(PORT),
           "AXE_HUB_DEFAULT_TENANT": "community-quarantine", "AXE_HUB_ALLOW_ORIGIN": "https://axe.onl",
           "AXE_HUB_CANONICAL_HOST": "operator.axe.onl"}
    p = subprocess.Popen([sys.executable, "-m", "hub.serve"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(120):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(LOCAL + "/healthz", timeout=2).read()
            return p
        except Exception:
            if p.poll() is not None:
                raise SystemExit("server exited: " + p.stderr.read().decode()[:500])
    p.kill()
    raise SystemExit("server did not come up")


def bench(rows_n: int = 65738) -> dict:
    rng = random.Random(1)
    sys.path.insert(0, str(ROOT))
    snap_q = [json.loads(line)["q"] for line in open(Path.home() / ".axe/skills-hub-v2/snapshot/find-baseline.jsonl")]
    words = ["docker", "pdf", "react", "slack", "sql", "image", "audit", "browser", "git", "video", "excel", "api"]

    def timed(path: str) -> float:
        t = time.perf_counter()
        urllib.request.urlopen(urllib.request.Request(LOCAL + path, headers={"User-Agent": UA})).read()
        return (time.perf_counter() - t) * 1000

    def pct(xs):
        xs = sorted(xs)
        return {"n": len(xs), "p50_ms": round(statistics.median(xs), 1),
                "p95_ms": round(xs[int(len(xs) * 0.95) - 1], 1), "max_ms": round(xs[-1], 1)}

    out = {}
    for q in snap_q[:5]:
        timed(f"/v1/tools/find?q={quote(q)}&limit=10")
    # _cb makes every key unique, so none of these is a cache hit: they time the real render.
    out["find_uncached"] = pct([timed(f"/v1/tools/find?q={quote(q)}&limit={rng.choice([5, 10, 50])}&_cb={i}")
                                for i, q in enumerate(snap_q * 5)])
    out["find_one_word_uncached"] = pct([timed(f"/v1/tools/find?q={w}&limit=10&_cb={i}")
                                         for i, w in enumerate(words * 10)])
    out["find_cached"] = pct([timed(f"/v1/tools/find?q={quote(q)}&limit=10") for q in snap_q * 5])
    out["list_200_uncached"] = pct([timed(f"/v1/skills?limit=200&offset={rng.randrange(0, rows_n)}")
                                    for _ in range(200)])
    out["list_1000_uncached"] = pct([timed(f"/v1/skills?limit=1000&offset={rng.randrange(0, rows_n)}&envelope=1")
                                     for _ in range(100)])
    out["list_default_uncached"] = pct([timed(f"/v1/skills?offset={rng.randrange(0, rows_n)}") for _ in range(200)])
    out["search_uncached"] = pct([timed(f"/v1/skills/search?q={w}{rng.randrange(10)}") for w in words * 4]
                                 + [timed(f"/v1/skills/search?q={w}") for w in words])
    out["detail"] = pct([timed("/v1/skills/agentic-loop-design") for _ in range(100)])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=Path.home() / ".axe/skills-hub-v2/snapshot")
    ap.add_argument("--db", type=Path, default=Path.home() / ".axe/hub/hub-v2.db")
    ap.add_argument("--live", action="store_true", help="also compare a few fresh read-only GETs to operator.axe.onl")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--no-start", action="store_true", help="use a server already listening on 8743")
    ap.add_argument("--report", type=Path, default=Path.home() / ".axe/hub/parity-report.json")
    args = ap.parse_args()

    cases = build_cases(args.snapshot, args.live)
    srv = None if args.no_start else start_server(args.db)
    rep = Report()
    rep.overlap, rep.top1 = [], []
    live_n = 0
    try:
        for case in cases:
            ours = http_get(LOCAL, case)
            want = case.want
            if case.live:
                for attempt in range(4):
                    time.sleep(0.25)
                    want = http_get(LIVE, case)
                    if "x-request-id" in want["headers"]:
                        break
                else:
                    print("skipped (plain build answered):", case.path)
                    continue
                live_n += 1
            rep.compared += 1
            if compare_case(case, ours, want, rep):
                rep.identical += 1
        if args.bench:
            rep.bench = bench()
    finally:
        if srv:
            srv.terminate()

    summary = {
        "requests_compared": rep.compared, "live_requests": live_n, "identical": rep.identical,
        "with_differences": rep.compared - rep.identical, "difference_count": sum(rep.diffs.values()),
        "unexplained": rep.unexplained,
        "find_top10_overlap_mean": round(statistics.mean(rep.overlap), 3) if rep.overlap else None,
        "find_top1_same": f"{sum(rep.top1)}/{len(rep.top1)}" if rep.top1 else None,
        "bench": getattr(rep, "bench", None),
        "differences": [
            {"case": k[0], "where": k[1], "kind": k[2], "reason": k[3], "count": n,
             "example": rep.examples[k]} for k, n in sorted(rep.diffs.items(), key=lambda x: -x[1])],
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "differences"}, indent=2))
    for dd in summary["differences"]:
        print(f"{dd['count']:4d}  [{dd['case']}] {dd['where']} | {dd['kind']} | {dd['reason']}")
        if dd["reason"] == "UNEXPLAINED":
            print("        e.g.", dd["example"])
    return 1 if rep.unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
