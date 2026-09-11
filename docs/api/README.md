# Skills catalogue API (generated artifacts)

Two files, **generated in CI and served from the CDN**. There is no server and
no database in the read path.

| File | What it is |
|---|---|
| `skills.json` | Flat array of catalogue records, sorted by `name` |
| `skills-meta.json` | Manifest: counts, `bySource`, `byCategory` (top 50), `generatedAt`, `schemaVersion` |

Neither file is committed. Both are gitignored — see "Why not in git" below.

## Where durability actually comes from

Not from the file, and not from the database. From two things:

1. **The pipeline is reproducible from nothing.** `axeskills_federate_cron.py`
   pulls every provider into a fresh sqlite and `axeskills_export_catalog.py`
   exports it. No local state is required, so any runner can rebuild the whole
   catalogue from the upstreams. sqlite is a cache, not a source of truth.
2. **A watchdog probes the live URL, not the build.** A green build only proves
   the build was green. `axeskills-catalog-freshness.yml` fetches the deployed
   JSON every 4 hours and opens an issue if it is stale, missing, or malformed.
   This is the part that catches a silently stuck cron before users do.

## Why not in git

Committing the artifact was the original plan here and it was wrong. The
catalogue really does change as upstreams add skills, so every scheduled export
is a genuine ~10 MiB pack delta. Twice daily, that is a few GB a year of
unbounded repo growth, for a file that is fully derivable from its inputs.

Determinism (`sort_keys=True` plus the registry `checksum` per record) removes
*spurious* diffs — an unchanged catalogue serialises byte-identically, verified
with `shasum -a 256` across two runs. It does not remove real ones, so it is not
a reason to track the file.

These are **raw, uncompressed JSON** on purpose. It matches the shape Hermes
publishes, so one consumer works against either catalogue unchanged; and the
CDN compresses on the wire anyway, so gzipping in-repo would cost that
compatibility and buy nothing.

## Regenerating locally

```bash
python3 axeskills_federate_cron.py --db ./axeskills-federation.db   # pull providers
python3 axeskills_export_catalog.py --db ./axeskills-federation.db --out docs/api
```

The export takes ~1.4s for 83,408 skills.

## Record shape

Every record carries these keys (sorted):

```
author  category  categoryLabel  checksum  commands  description  envVars
homepage  license  name  platforms  quarantined  source  tags  upstreamVersion
verified  version
```

`quarantined: true` on everything federated from an external registry — nothing
lands in a client tenant without a deliberate promotion step.

## Counts worth knowing before you build on this

- **83,408 records, not 90,699.** Upstream has no stable ID: `docsPath` is empty
  for 90,501 of 90,699 records, so `source/name` is the only usable key, and
  7,291 records share one. Roughly 6,496 records sit behind another skill's
  name — worst case is 64 records all named `Skill`.
- **~82% of rows are category `other`**, and only 3,830 of those carry tags.
  Category-browse is weak on its own; search and `source` are the useful axes
  until we classify these ourselves.
