# AXE Skills Catalogue

A read-only HTTP catalogue that federates skills from upstream registries — ClawHub, Smithery, Ollama, and first-party AXE authors — and exposes them through a unified JSON API.

Upstream sources are credited by name in every response. A skill published to ClawHub by its author arrives here as `"source": "ClawHub"`. A first-party AXE skill is labelled `"source": "axe"`. Attribution is data, not a display choice.

## Upstream sources and attribution

The catalogue federates from multiple upstream registries. Every skill carries the name of the registry it came from — attribution is data, not a display decision.

| Registry | Source label | What it contributes |
|---|---|---|
| **ClawHub** | `ClawHub` | Community-authored skills across models and runtimes (~76% of the catalogue) |
| **Smithery** | `smithery` | MCP-compatible tool servers |
| **AXE** | `axe` | First-party skills authored and maintained by AXE |

The `source` field in every `/v1/skills` response carries the upstream registry name. The transport hop is recorded separately (`"hermes:ClawHub"` means "arrived via Hermes, from ClawHub") and display layers strip only that hop, keeping the registry name visible:

```
GET /v1/skills/auto-tail

{
  "name": "auto-tail",
  "metadata": { "source": "hermes:ClawHub", ... }
}
```

Display label: **ClawHub** (strip before the first `:` to get the transport; the part after is the registry to credit).

Want to add a new upstream? See [CONTRIBUTING.md](CONTRIBUTING.md).

## API

The server runs read-only: every POST is refused before it is parsed. No authentication is required for read operations.

### List skills

```
GET /v1/skills
```

Query parameters:

| Parameter | Default | Description |
|---|---|---|
| `tenant` | deployment default | Which registry tenant to query |
| `limit` | 200 | Max rows (ceiling 1000) |
| `offset` | 0 | Pagination offset |

Response: array of skill records. Each record includes `name`, `description`, `source`, `version`, `checksum`, `category`, `verified`, `yanked`.

Example:

```bash
curl 'https://skills.axe.onl/v1/skills?limit=10'
```

### Search

```
GET /v1/skills/search?q=<query>
```

Full-text search across `name` and `description`. Same pagination parameters as list.

```bash
curl 'https://skills.axe.onl/v1/skills/search?q=log+tail'
```

### Find (agent-optimised)

```
GET /v1/skills/find?q=<natural language task>
```

Ranked match list tuned for agent callers. Returns up to 10 results by default (ceiling 50). Optional filters:

| Parameter | Description |
|---|---|
| `category` | Filter by category slug |
| `verified=1` | Only verified skills |
| `limit` | Result count (max 50) |

Response shape:

```json
{
  "query": "tail a log and alert on errors",
  "count": 3,
  "results": [
    { "name": "auto-tail", "description": "...", "source": "axe", "score": 0.94 }
  ]
}
```

### Fetch one skill

```
GET /v1/skills/<name>?tenant=<tenant>&version=<version>
```

Returns the full skill document including body content. Omit `version` to get the latest non-yanked version.

### List versions

```
GET /v1/skills/<name>/versions?tenant=<tenant>
```

Returns all versions with their status (`yanked`, `checksum`, `published_at`).

### Health

```
GET /healthz
```

Returns `{"status": "ok"}`.

## Integration

### Setting the tenant

Pass `X-AXE-Tenant: <tenant-id>` to scope responses to a specific registry partition. A deployment may set a default tenant so browser callers without the header still see a useful catalogue.

### Crediting upstream sources

When displaying results from this API, credit the upstream registry by its `source` label. The display layer should strip the federation hop prefix (`"ClawHub:auto-tail"` → `"ClawHub"`) but keep the registry name. Example:

```js
const sourceLabel = skill.source.includes(':')
  ? skill.source.split(':')[0]
  : skill.source;
```

### Client skill

`skills/skillshub-find/` is a shell skill agents can load to search the catalogue:

```bash
./skillshub-find.sh "tail a log and tell me when a build finishes"
./skillshub-find.sh --get auto-tail
```

## Running your own instance

```bash
AXE_HUB_DB=path/to/hub.db \
AXE_HUB_DEFAULT_TENANT=my-tenant \
AXE_HUB_HOST=0.0.0.0 AXE_HUB_PORT=8742 \
python3 -m hub.serve
```

`hub.serve` is configured from the environment only (no flags) and is read-only unless `AXE_HUB_READ_ONLY=0`.

Environment variables:

| Variable | Description |
|---|---|
| `AXE_HUB_DB` | Path to the SQLite database |
| `AXE_HUB_DEFAULT_TENANT` | Default tenant when no header is present |
| `AXE_HUB_ALLOW_ORIGIN` | CORS allowed origin (omit to disable CORS headers) |
| `AXE_HUB_HOST`, `AXE_HUB_PORT` | Bind address (default `127.0.0.1:8742`) |
| `AXE_HUB_CANONICAL_HOST` | The one host `robots.txt` lets crawlers index (default `skills.axe.onl`) |
| `AXE_HUB_EVAL_DB` | Eval database; omit for none |
| `AXE_HUB_READ_ONLY` | `0` enables writes; anything else, or unset, is read-only |

## Running the v2 build

The v2 build serves the same API and the same data as the rich build that answers most public traffic on
operator.axe.onl: `/openapi.json`, `/v1/categories`, a `card` and an `install` line on every row, the
structured error body `{"error": {"type", "code", "message", "param"}}`, `x-request-id` and the CORS and
security headers, `?envelope=1` paging, find with `limit_capped`/`searched_literally`, and HEAD. Its data
comes from a snapshot of that build (`~/.axe/skills-hub-v2/snapshot/`), loaded into a new database.

### Build the database

```bash
python3 scripts/import_snapshot.py            # -> ~/.axe/hub/hub-v2.db and hub-v2.verify.json
python3 scripts/import_snapshot.py --force    # replace an existing hub-v2.db
```

It refuses to overwrite an existing file without `--force`, refuses any file named `hub.db`, and builds beside
the target before renaming. Rows go into the repo's own `skills` table with the rich build's values; the card,
the stored categories and the version histories go into the tables of `hub/schema_serve.sql`. Nothing is
scanned or re-flagged: `quarantined` and `verified` are copied as the snapshot has them. The verification
report records the input checksums, 65,738 rows (names unique, in the rich build's order), every row read back
and compared, and that all 65,738 bodies hash to their reported checksum (381 captured; 65,357 catalog bodies
rebuilt from metadata and card and proven by that hash).

### Tenant

The rich build reports every row as tenant `community-quarantine` (the old DB says `public`) and ignores
`X-AXE-Tenant` on reads: `public`, `axe-internal` and a nonexistent tenant all got the same 200. The v2 build
does the same: with `AXE_HUB_DEFAULT_TENANT` set and the server read-only, every caller is served that tenant
and the header is not consulted. A headerless client therefore sees `community-quarantine`.

### launchd environment

`com.axe.skills-catalogue` keeps its wrapper (`axe-skills-catalogue-serve.py`, which calls `make_server`) and
the same label and port. Only these keys change:

| Key | v2 value | Old value |
|---|---|---|
| `AXE_HUB_DB` | `/Users/jl2/.axe/hub/hub-v2.db` | `/Users/jl2/.axe/hub/hub.db` |
| `AXE_HUB_DEFAULT_TENANT` | `community-quarantine` | `public` |
| `AXE_HUB_ALLOW_ORIGIN` | `https://axe.onl` (new; the rich build's CORS origin) | unset |
| `AXE_HUB_CANONICAL_HOST` | `skills.axe.onl` (new, explicit; operator.axe.onl then asks crawlers to stay out) | unset (same default) |
| `AXE_HUB_HOST` / `AXE_HUB_PORT` | `0.0.0.0` / `8742` | unchanged |
| `AXE_SKILLS_REPO` | the checkout that contains this branch | unchanged |

Start-up builds the find index (about 2 s, about 200 MB resident) before the socket opens.

### Roll back

Set `AXE_HUB_DB` back to `/Users/jl2/.axe/hub/hub.db` and `AXE_HUB_DEFAULT_TENANT` back to `public`, then
boot the job out and in (below). The server notices the database has no `skill_cards` table and serves the
plain registry path: the old data and old routes, with `/v1/categories` and `/openapi.json` answering 404 as
before. Rollback does not touch `hub-v2.db`.

### Cutover checklist

1. `python3 -m pytest -q` is green; `python3 scripts/import_snapshot.py --force` reports `ok: true`.
2. `python3 scripts/parity.py --live --bench` exits 0 (unexplained 0) and the p95s are under 150 ms.
3. Back up the live DB: `sqlite3 ~/.axe/hub/hub.db ".backup ~/.axe/hub/hub.db.pre-v2-$(date +%Y%m%d)"`, and
   `cp -p ~/.axe/hub/hub-v2.db ~/.axe/hub/hub-v2.db.bak`. Copy the plist to `*.pre-v2`.
4. Edit the plist keys above; `plutil -lint ~/Library/LaunchAgents/com.axe.skills-catalogue.plist`.
5. Restart so the environment is re-read. `launchctl kickstart -k` does NOT reload plist environment changes:
   it restarts the process with the environment launchd already holds. Boot the job out and in:
   `launchctl bootout gui/$(id -u)/com.axe.skills-catalogue` then
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.axe.skills-catalogue.plist`.
6. Smoke from the box: `/healthz`, `/v1/categories` (`count` 207), `/v1/skills?limit=1&envelope=1` (`total`
   65738, `tenant_id` community-quarantine), a find, and the same three through the tunnel. The healthcheck
   script polls `/v1/skills` every few minutes and logs a failure during the ~2 s start-up; that one is expected.
7. Only then stop sending traffic to the old connector.

### Parity harness and performance

`scripts/parity.py` starts the server on 127.0.0.1:8743 against `hub-v2.db`, replays about 150 requests
(40 recorded find queries, list pages at many offsets and limits, 30 skills as detail plus versions, errors,
tenant headers, HEAD, OPTIONS) and, with `--live`, a few fresh read-only GETs to operator.axe.onl (at most
5 requests a second, `User-Agent: axe-hub-parity/1.0`). Every difference is classified; unexplained ones fail
the run. `--bench` times uncached requests (each uses a unique key) against the running server.

What is served from stored values and cannot be reproduced from the snapshot:

- **Multi-term find ranking.** The rich build's scoring is not recoverable. Single-term queries match its
  scores exactly. Multi-term queries use the repo's field weights, scaled by term rarity and coverage, fitted to
  the 40 recorded answers: top-10 overlap about 84%, same top result in 34 of 41. Result shape, filters,
  limits, notes and errors match.
- **Derived categories.** The 15,002 `derived` categories and the 207 facets are served as stored; no rule
  re-derives them.
- **Older versions.** Version histories exist only for the 381 skills whose `/versions` was captured (seven
  have more than one). Every other skill lists its current version only; an older version's body was never
  captured, so `?version=<older>` is 404.
- **Skill bodies.** 80 skillmd bodies were captured, not the "about 95" the brief expected; the other catalog
  bodies are rebuilt and checksum-proven.
- **HTML.** `/docs/skills/c/<category>`, `/docs/skills/s/<name>`, `/static/*` and `/favicon.svg` are not
  reproduced; the repo's static `/docs/skills` shell answers `/` and `/docs/skills*`.
- **Edge-only headers.** HSTS comes from the Cloudflare edge. `/llms.txt` and `/.well-known/agent-skills.json`
  exist here and not on the rich build (kept from the discovery branch, and describe this API).
- **GET is read-only.** A GET writes nothing, including the audit row the old build appended on every skill
  fetch, and `?_actor=` is gone. POST actors are always the resolved tenant, never a caller-supplied name.

## Offline snapshot

A full JSON snapshot of the catalogue is published twice daily as the
`catalogue-latest` release asset (`skills.json` / `skills-meta.json`) -- see
`docs/api/README.md` for the sync/freshness contract and how to fetch it
without hitting the live API.

## Catalogue snapshot

The catalogue is live at `https://skills.axe.onl/v1/skills`. For a full snapshot:

```bash
curl 'https://skills.axe.onl/v1/skills?limit=1000&offset=0'
```

Paginate with `offset` for tenants with large catalogues.

## Eval surface

The `/v1/skills/<name>` response includes an `eval` key when the deployment has eval data for that skill version. This public deployment does not serve evals — the `eval` key will be absent from all responses. To distinguish "skill has no eval" from "this deployment does not serve evals at all", the `eval` key is simply absent from every response; `/healthz` returns `{"status": "ok"}` and does not report it.

## Schema

See `hub/schema.sql` for the database schema.

## Tests

```bash
pip install pytest
pytest tests/
```
