# AXE Skills Catalogue

A read-only HTTP catalogue for AXE skills. Exposes a JSON API that agents and web surfaces use to discover, search, and fetch skill metadata.

## API

All reads are unauthenticated on a public deployment. The server runs in `READ_ONLY` mode: every POST is refused before it is parsed.

### List skills

```
GET /v1/skills?tenant=<tenant>&limit=<n>&offset=<n>
```

Returns paginated skill metadata for the given tenant.

### Search

```
GET /v1/skills/search?q=<query>&tenant=<tenant>&limit=<n>
```

Full-text search across name and description.

### Find (agent-optimised)

```
GET /v1/tools/find?q=<query>&tenant=<tenant>
GET /v1/skills/find?q=<query>&tenant=<tenant>
```

Ranked match list. Designed for agent callers that need a tool for a described task.

### Fetch one skill

```
GET /v1/skills/<name>?tenant=<tenant>&version=<version>
```

Returns the full skill document including body content.

### List versions

```
GET /v1/skills/<name>/versions?tenant=<tenant>
```

## Running

```bash
python -m hub.serve --db path/to/hub.db --host 0.0.0.0 --port 8742 --read-only
```

Environment variables:
- `AXE_HUB_DB` — path to the SQLite database
- `AXE_HUB_DEFAULT_TENANT` — tenant to use when no `X-AXE-Tenant` header is present
- `AXE_HUB_ALLOW_ORIGIN` — CORS allowed origin (omit to disable CORS headers)

## Client skill

`skills/skillshub-find/` contains a shell skill that agents can load to search the catalogue:

```bash
./skillshub-find.sh <natural language description>
./skillshub-find.sh --get <skill-name>
```

## Schema

See `hub/schema.sql` for the database schema.

## Tests

```bash
pip install pytest
pytest tests/
```
