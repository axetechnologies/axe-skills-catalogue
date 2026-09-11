# axe-skills-catalogue — conventions

Python 3.11+, stdlib only (no third-party deps for the server). SQLite for the catalogue database.

## Non-negotiable rules

1. `hub/serve.py` public deployments MUST set `READ_ONLY=True`. Never expose write routes publicly.
2. No credentials, tunnel tokens, or tenant key maps in this repo.
3. Database files (`*.db`) are never committed — they are runtime state.
4. The `AXE_HUB_DEFAULT_TENANT` env var is the only way to configure the default tenant on a public surface.

## Running

```bash
python -m hub.serve --db ~/.axe/hub/hub.db --read-only
```

## Tests

```bash
pytest tests/
```
