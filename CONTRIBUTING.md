# Contributing to the AXE Skills Catalogue

The catalogue is a community aggregator. Its value is breadth of absorption and honest attribution. Skills from any upstream registry are welcome; the quarantine flow described here is what keeps that open without being reckless.

## How a skill enters the catalogue

There are two paths: **federation** (pulling from an upstream registry automatically) and **direct submission** (submitting a skill via the CLI or HTTP API).

### Federation

Upstream registries are absorbed by periodic federation runs. Each adapter (`SmitheryCatalog`, `HermesCatalog`) implements `fetch() -> Iterator[CommunityEntry]`. Adding a new upstream means writing a class with that interface.

When `federate()` runs:

1. Every entry from the upstream is SHA-256 content-addressed. If the checksum matches the existing record, the row is marked `unchanged` and skipped.
2. New and updated entries land in the `community-quarantine` tenant — a walled partition that is never served to client callers through the public API.
3. The entry's `metadata.quarantined = True` flag is set at write time and cleared only on an explicit promote call.
4. The federation report (added / unchanged / skipped / failed counts) is logged.

Nothing federated reaches a client tenant without an explicit human promote call.

### Direct submission

A skill author can submit a `.md` or directory-based skill via the CLI:

```bash
python3 -m hub.cli publish path/to/my-skill/ --tenant community-quarantine --actor github:you
```

Or via the HTTP API with an `X-AXE-Key` header mapping to a write-capable tenant. The API spec is in `README.md`.

Submitted skills also land in quarantine unless the submitting key maps to a promoted tenant.

## Promotion from quarantine

A human reviewer calls `promote()` to move a skill from `community-quarantine` to a serving tenant:

```python
from hub.community import promote
from hub.store import Registry

reg = Registry("hub.db")
promote(reg, name="community__smithery__my-skill", from_tenant="community-quarantine", to_tenant="public", actor="reviewer")
```

Or via the CLI (operator-only):

```bash
python3 -m hub.cli promote community__smithery__my-skill --from community-quarantine --to public --actor reviewer
```

The `promotion_decisions` table records every decision (promoted / tied / rejected / degraded-yanked) with pass rates so the record is auditable.

The `skill_candidates` table records pending candidates with status `pending → promoted | rejected`.

## Attribution

Every federated row carries its source label verbatim:

- `"source": "hermes:ClawHub"` — arrived via the Hermes adapter, from the ClawHub registry
- `"source": "smithery"` — arrived via the Smithery adapter
- `"source": "axe"` — first-party AXE skill

Display layers strip only the transport hop and keep the registry name:

```js
// "hermes:ClawHub" → "ClawHub"
const label = source.includes(':') ? source.split(':')[1] : source;
```

Do not genericise or remove upstream credit. The source label is attribution, not internal plumbing.

## Adding a new upstream adapter

1. Implement `fetch(limit, page_size) -> Iterator[CommunityEntry]` in a new module.
2. Set `entry.source` to a stable identifier for your registry (e.g. `"myregistry"`).
3. Call `hub.community.federate(registry, your_catalog, tenant_id=..., actor=...)`.
4. Credentials stay out of the repo — pass them via the constructor or an env var.

The quarantine flow, attribution, and deduplication are handled by `federate()` automatically.

## What stays private

The following are never committed here:

- API keys, bearer tokens, Cloudflare tunnel tokens
- `hub.db` / `axeskills-federation.db` database files
- The operator write console (`axeskills_operator_portal.py`)
- Tenant provisioning scripts
- The federation ledger directory

Adapter CODE is public. Adapter CREDENTIALS are externalised to env vars or caller-supplied constructor arguments.
