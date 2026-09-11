# Skills catalogue API (generated artifacts)

Two files, **synced twice daily from the live catalogue and published as a
release asset**. Neither is committed -- both are gitignored.

| File | What it is |
|---|---|
| `skills.json` | Flat array of catalogue records, sorted by `name` |
| `skills-meta.json` | Manifest: counts, `bySource`, `byCategory` (top 50), `generatedAt`, `schemaVersion` |

## This repo is a mirror, not the origin

The federation pipeline that pulls upstream providers and builds these files
lives in the private hub, not here -- this repo has no federation credentials
(see `AXE.md` rule 2) and cannot rebuild the catalogue from scratch. What this
repo owns is a durable, offline-fetchable copy of whatever the hub last
published.

## Where durability comes from

1. **`axeskills-catalogue-sync.yml`**, twice daily, fetches the live
   `skills.json`/`skills-meta.json` from the canonical URL, refuses to publish
   anything empty, malformed, or below a 50,000-record floor, and uploads the
   result as the `catalogue-latest` release asset. That gives every consumer
   -- including an air-gapped one -- a stable URL that needs no deploy
   infrastructure on our side:

   `axetechnologies/axe-skills-catalogue` release `catalogue-latest`,
   asset `skills.json` / `skills-meta.json`.

2. **`axeskills-catalogue-freshness.yml`**, every 4 hours, probes both the live
   URL and the release asset and fails the job -- not just files an issue --
   if either is missing, empty, or more than 26h stale. A zero-row catalogue
   is treated as a failure shape, not a value.

## Why not in git

A committed multi-megabyte snapshot goes stale the moment it lands and grows
the clone forever, for a file that is fully derivable from the live source.
Twice-daily syncs would make that a permanent, unbounded pack-size cost. The
release asset gives the same durability without it.

## Fetching a snapshot offline

Download the `skills.json` and `skills-meta.json` assets from the
`catalogue-latest` release of this repo (`gh release download catalogue-latest`,
or the release page's asset links).

## Record shape

Every record carries these keys (sorted):

```
author  category  categoryLabel  checksum  commands  description  envVars
homepage  license  name  platforms  quarantined  source  tags  upstreamVersion
verified  version
```

`quarantined: true` on everything federated from an external registry -- nothing
lands in a client tenant without a deliberate promotion step.

## Counts worth knowing before you build on this

- **83,408 records, not 90,699.** Upstream has no stable ID: `docsPath` is empty
  for 90,501 of 90,699 records, so `source/name` is the only usable key, and
  7,291 records share one. Roughly 6,496 records sit behind another skill's
  name -- worst case is 64 records all named `Skill`.
- **~82% of rows are category `other`**, and only 3,830 of those carry tags.
  Category-browse is weak on its own; search and `source` are the useful axes
  until we classify these ourselves.
