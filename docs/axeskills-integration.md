# Adding the Skills Hub to a surface

## Live surfaces

Two hostnames, one `cloudflared` tunnel (`637b672b-89f7-4554-bd8a-6f4cf1d11b31`):

| Hostname | Purpose | Access | Verified |
|---|---|---|---|
| `https://operator.axe.onl` | Operator console — writable API + portal UI | Cloudflare Access (302 to login) | ✅ 2026-09-10 |
| `https://skills.axe.onl` | Public read-only catalogue | Open (`/healthz` → 200) | ✅ 2026-09-10 |

The public hostname is safe because the origin behind port 8742 runs in
`READ_ONLY` mode — a server-side flag, not a deployment convention. In that
mode every `POST` is refused with `405` before the request body is read, and
`GET /v1/audit` returns `404`. `key_map` is forced empty so no tenant key
grants write access via the public surface.

For brand rules that apply to the operator portal UI, see
[`docs/axeskills-brand.md`](axeskills-brand.md).

---

How to put 83,409 tools in front of an agent, an app, or a web page. Everything
here is the same HTTP server (`hub/serve.py`); the differences are which routes
you call and how the caller is authenticated.

If you only read one thing: **`GET /v1/tools/find?q=<task>` is the endpoint.**
It takes a plain-language task, returns a short ranked list of compact records,
and is the only route designed for something that has to *choose*.

## The four verbs

An agent needs exactly four things from a tool catalogue. Each is one call.

| Verb | Route | Notes |
|---|---|---|
| **Find** a tool for a task | `GET /v1/tools/find?q=...` | Ranked, compact, capped at 50. Start here. |
| **Use** a specific tool | `GET /v1/skills/<name>` | Returns the full record *and* its `content` (the skill body). |
| **Create / add** a tool | `POST /v1/skills` | Requires a tenant key or header — the default tenant is read-only by design. |
| **Report** what happened | `POST /v1/skills/<name>/outcome` | `success` / `failure` / `error`. This is what makes `use_count` mean anything. |

Supporting routes: `GET /v1/skills` (paged list), `GET /v1/skills/<name>/versions`,
`GET /v1/audit`, `GET /healthz`.

### Find

```bash
curl -s 'https://operator.axe.onl/v1/tools/find?q=deploy+a+container+to+kubernetes&limit=5'
```

```json
{
  "query": "deploy a container to kubernetes",
  "count": 5,
  "results": [
    {
      "name": "community__hermes:NVIDIA__NVIDIA__tao-run-on-kubernetes",
      "title": "tao-run-on-kubernetes",
      "description": "Kubernetes execution platform — submits TAO container jobs as ...",
      "category": "infrastructure",
      "category_label": "Infrastructure",
      "tags": ["kubernetes", "k8s", "gpu", "compute", "container"],
      "source": "hermes:NVIDIA",
      "verified": false,
      "use_count": 0,
      "version": "1.0.0",
      "homepage": "",
      "score": 41.33,
      "matched_terms": 2
    }
  ]
}
```

Parameters: `q` (or `task`), `limit` (default 10, max 50), `category`,
`verified=1`.

`score` is comparable *within one response* and meaningless across responses —
it is not a probability and must never be shown to an end user as one. Use
`matched_terms` to tell "answered the whole question" from "matched one word":
results are ordered by coverage first, then score.

`count: 0` is a real answer. "No tool for this" is information, and an agent
should say so rather than reach for the least-bad row.

### Why not `/v1/skills/search`

It still exists and still works, but it greps `name` and `metadata` with a
`LIKE` and returns rows **in alphabetical order**. It cannot see the
`description` column, where 100% of the catalogue's prose lives — for
"kubernetes" it matched 55 rows when 119 were relevant. Alphabetical order is
not a ranking. Prefer `/v1/tools/find` for anything that picks.

## Agents

### As a tool schema

Give a model these two tools and it can do the whole loop unaided:

```json
[
  {
    "name": "find_skill",
    "description": "Search the AXE Skills Hub for a tool that performs a task. Call this before saying a capability is unavailable. Returns a ranked shortlist; an empty list means no tool exists.",
    "input_schema": {
      "type": "object",
      "properties": {
        "q": {"type": "string", "description": "The task, in plain language, e.g. 'extract tables from a pdf'"},
        "limit": {"type": "integer", "default": 5},
        "category": {"type": "string", "description": "Optional category slug to narrow the search"}
      },
      "required": ["q"]
    }
  },
  {
    "name": "get_skill",
    "description": "Fetch one skill's full body by its exact name, as returned by find_skill.",
    "input_schema": {
      "type": "object",
      "properties": {"name": {"type": "string"}},
      "required": ["name"]
    }
  }
]
```

Two calls, not one: `find_skill` returns compact records precisely so a
shortlist costs a few hundred tokens instead of tens of thousands, and the
model pays for a full body only for the one tool it picked.

### Retrieve-then-choose, not retrieve-and-dump

Ask for `limit=5..15` and let the model choose from the shortlist. Do not paste
the taxonomy or a large slice of the catalogue into a prompt — measured work on
this exact shape (TELEClass, WWW 2025) finds that dumping a large label space
into the context performs *worse* than retrieving a shortlist first. The
shortlist is the feature.

### Python

```python
import urllib.parse, urllib.request, json

BASE = "https://operator.axe.onl"

def find_skill(task, limit=5):
    q = urllib.parse.urlencode({"q": task, "limit": limit})
    with urllib.request.urlopen(f"{BASE}/v1/tools/find?{q}", timeout=15) as r:
        return json.load(r)["results"]

def get_skill(name):
    path = urllib.parse.quote(name, safe="")
    with urllib.request.urlopen(f"{BASE}/v1/skills/{path}", timeout=15) as r:
        return json.load(r)
```

## App surfaces

Server-to-server, so there is no CORS question — send a tenant and go.

```
X-AXE-Key: <tenant key>        # preferred: maps to a tenant, and can write
X-AXE-Tenant: <tenant id>      # trusted-network only
```

A presented key always decides, **even when it maps to nothing**: a bad key is
rejected rather than quietly downgraded to the default tenant.

Anything behind `operator.axe.onl` is also behind Cloudflare Access, so a
non-browser caller needs an Access **service token** (`CF-Access-Client-Id` /
`CF-Access-Client-Secret`) in addition to its tenant header. That token does
not exist yet — creating it is an open task, and until it does, app surfaces
must talk to the hub on the internal network rather than through the public
hostname.

## Web surfaces

A browser will not read a cross-origin response unless the server permits it,
so CORS has to be on. It is **off unless configured**:

```bash
AXE_HUB_ALLOW_ORIGIN=https://axe.onl   # then restart the portal
```

The default is off on purpose, and it is not caution for its own sake: a
browser reaching `operator.axe.onl` carries a signed-in operator's Access
session. `Access-Control-Allow-Origin: *` on a session-bearing origin lets any
page that operator happens to visit read the whole catalogue as them.

**So do not put a wildcard on the operator origin.** The public web surface
has its own origin instead: **`https://skills.axe.onl`**, live, no Access in
front, CORS scoped to `https://axe.onl`. One origin per audience.

What makes it safe to leave ungated is not the hostname but the mode the
process runs in (`serve(..., read_only=True)`): every `POST` is refused with
`405` before its body is read, `/v1/audit` is `404`, and the key map is forced
empty so there is no credential on that origin worth stealing. Verified on the
live hostname, not just in tests:

```
GET  /v1/tools/find?q=pdf  200   (access-control-allow-origin: https://axe.onl)
OPTIONS /v1/tools/find     204
GET  /v1/audit             404
POST /v1/skills            405   (also 405 with a tenant header)
POST /v1/skills/x/outcome  405
```

It serves the `community-quarantine` tenant — federated data already public at
its source. No first-party tenant is reachable from that process at all, so a
bug in the read-only mode would still not expose private rows.

Use `skills.axe.onl` for browsers and anything unauthenticated;
`operator.axe.onl` for publishing and the audit log.

Named origins also need the preflight, which is why `OPTIONS` is implemented:
`X-AXE-Tenant` makes a cross-origin `GET` non-simple, so the browser asks
first, and a server that answers `501` means the real request is never sent.

### Minimal picker

```html
<input id="q" placeholder="What do you need to do?">
<ul id="out"></ul>
<script>
const BASE = "https://skills.axe.onl";   // public, read-only, no Access gate
let timer;
document.getElementById("q").addEventListener("input", (e) => {
  clearTimeout(timer);
  const q = e.target.value.trim();
  // Debounced: every keystroke is a full-catalogue scan server-side.
  timer = setTimeout(async () => {
    const out = document.getElementById("out");
    if (!q) { out.innerHTML = ""; return; }
    const r = await fetch(`${BASE}/v1/tools/find?q=${encodeURIComponent(q)}&limit=8`);
    const { results } = await r.json();
    out.innerHTML = results.length
      ? results.map(s => `<li><b>${s.title}</b> — ${s.description}</li>`).join("")
      : "<li>No tool for that yet.</li>";
  }, 200);
});
</script>
```

Two things this deliberately does not do. It does not render `score` — no
comparable catalogue shows users a confidence number, and it reads as an
excuse. And it does not interpolate `s.description` as trusted markup in a real
app: catalogue prose is third-party text, so escape it or set `textContent`.

## The operator front end

`https://operator.axe.onl/docs/skills` is the human surface: search box,
category rail, per-category browse, per-skill pages. Its search shares
`hub.discover.rank` with the API, so the UI and an agent asked the same
question get the same answer in the same order. Two copies of a ranking drift,
and the copy that ships is the one nobody measured.

`/portal` is the older, thinner list view — no search box, 500 rows in
alphabetical order. It is kept because it is linked from elsewhere; send people
to `/docs/skills`.

## Operating notes

- **Latency** is 150–750 ms for a ranked query over 83k rows: a SQL `LIKE`
  prefilter narrows the candidates and scoring happens in Python. There is no
  index to maintain and nothing to rebuild after ingest, which is the trade —
  correctness that survives a refresh, over speed that needs a cron job. If it
  ever needs to be faster, FTS5 is the move, and it brings an index-maintenance
  obligation with it.
- **Ranking weights** live in one block at the top of `hub/discover.py`. They
  are ordered judgements, not measurements: a name match beats a tag, a tag
  beats prose. Nothing has been tuned against a labelled relevance set, because
  none exists yet.
- **Restart** after changing `AXE_HUB_ALLOW_ORIGIN`:
  `launchctl kickstart -k gui/$(id -u)/com.axe.axeskills-portal`
- **Verify** end to end: `curl -s localhost:8741/healthz`, then
  `curl -s 'localhost:8741/v1/tools/find?q=pdf&limit=3'`. For the public
  origin, check the refusals rather than the successes — a `200` on
  `/v1/tools/find` proves it is up, but only a `405` on `POST /v1/skills` and
  a `404` on `/v1/audit` prove it is still read-only.
- **Two processes, two agents.** `com.axe.axeskills-portal` runs 8741
  (operator, writable); `com.axe.axeskills-public` runs 8742 (public,
  read-only). Both are LaunchAgents bound to loopback; the one path in is the
  shared cloudflared tunnel, whose ingress maps each hostname to its own port.
- **The tunnel config is deployed, not read in place.** `cloudflared` reads
  `~/.cloudflared/axeskills-operator-tunnel.yml`; the repo copy is the source
  of truth. Editing the repo file alone changes nothing, and the symptom is a
  flat `404` on every path of the new hostname — the tunnel's own catch-all,
  which looks exactly like an application error. Copy it across, then
  `launchctl kickstart -k gui/$(id -u)/com.axe.axeskills-tunnel`.
