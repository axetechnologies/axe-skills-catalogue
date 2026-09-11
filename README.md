# AXE Skills Catalogue

A read-only HTTP catalogue that federates skills from upstream registries — ClawHub, Smithery, Ollama, and first-party AXE authors — and exposes them through a unified JSON API.

Upstream sources are credited by name in every response. A skill published to ClawHub by its author arrives here as `"source": "ClawHub"`. A first-party AXE skill is labelled `"source": "axe"`. Attribution is data, not a display choice.

## Upstream sources

| Registry | What it contributes |
|---|---|
| **ClawHub** | Community-authored skills across models and runtimes |
| **Smithery** | MCP-compatible tool servers |
| **AXE** | First-party skills authored and maintained by AXE |

Source labels appear verbatim in `/v1/skills` responses and in the web catalogue. The `source` field is `"<registry>:<skill-name>"` for federated skills (e.g. `"ClawHub:auto-tail"`) and `"axe"` for first-party skills.

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

## Schema

See `hub/schema.sql` for the database schema.

## Tests

```bash
pip install pytest
pytest tests/
```
