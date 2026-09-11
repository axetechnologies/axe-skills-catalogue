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

Returns `{"ok": true}`.

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
python3 -m hub.serve --host 0.0.0.0 --port 8742 --read-only
```

Environment variables:

| Variable | Description |
|---|---|
| `AXE_HUB_DB` | Path to the SQLite database |
| `AXE_HUB_DEFAULT_TENANT` | Default tenant when no header is present |
| `AXE_HUB_ALLOW_ORIGIN` | CORS allowed origin (omit to disable CORS headers) |

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

The `/v1/skills/<name>` response includes an `eval` key when the deployment has eval data for that skill version. This public deployment does not serve evals — the `eval` key will be absent from all responses. To distinguish "skill has no eval" from "this deployment does not serve evals at all", check the deployment's `/healthz` response:

```json
{ "status": "ok", "evals": false }
```

A deployment with evals enabled will show `"evals": true`.

## Schema

See `hub/schema.sql` for the database schema.

## Tests

```bash
pip install pytest
pytest tests/
```
