# axe-skills-catalogue — conventions

Python 3.11+, stdlib only. SQLite for the catalogue database.

## Rules

1. Public deployments MUST start with `--read-only`. Every POST is refused before parsing; the audit endpoint returns 404.
2. No credentials, tunnel tokens, or tenant key maps in this repo.
3. Database files (`*.db`) are never committed — they are runtime state.
4. `AXE_HUB_DEFAULT_TENANT` is the only way to configure the default tenant on a public surface.
5. Vendor names in `skills/**` are subject matter, not branding. A skill about Ollama must say Ollama. Do not genericise them.
6. Upstream `source` labels are attribution, not internal provenance. Display layers strip the federation hop prefix but keep the registry name. Do not remove upstream credit.

## Running

```bash
AXE_HUB_DB=~/.axe/hub/hub.db python3 -m hub.serve --read-only
```

## Tests

```bash
pytest tests/
```
