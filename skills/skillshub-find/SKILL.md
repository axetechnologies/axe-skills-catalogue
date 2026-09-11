---
name: skillshub-find
description: Search the AXE Skills Hub for a skill that fits a task described in plain words, and fetch its full body. Use when you need a capability you do not already have loaded, before writing one from scratch.
---

# skillshub-find

There are ~111k skills in the AXE Skills Hub and none of them help if you write
the thing from scratch instead. Ask first.

## Search

```bash
./skillshub-find.sh tail a log and tell me when a build finishes
```

Prints ranked matches, each with who wrote it, because a mirrored third-party
skill and one AXE wrote are not the same claim.

## Fetch one

```bash
./skillshub-find.sh --get auto-tail
```

The catalogue is metadata only, so discovery and the body are two calls: search
finds the name, `--get` returns the document you actually read or run.

## Which tenant you are asking

| env | default | what it selects |
|---|---|---|
| `SKILLSHUB_TENANT` | `community-quarantine` | the ~111k mirrored from Hermes |
| | `axe` | first-party, written and verified by AXE |
| `SKILLSHUB_KEY` | unset | sent as `X-AXE-Key`; maps to its tenant server-side |
| `SKILLSHUB_URL` | `https://skills.axe.onl` | point at `http://127.0.0.1:8741` for a local hub |

A write never honours a default tenant, and an unauthenticated request is a 403
rather than a request served under a tenant nobody named. Reads over the public
surface are fine without a key.

## Why this endpoint

`/v1/tools/find` is ranked, compact and capped. `/v1/skills/search` returns rows
in alphabetical order and cannot see the description column, so a one-word query
there can match most of the corpus — it is not the one to build on.

## Known limit

Ranking is lexical, not semantic: it scores the words in your task against the
name, description and tags. Phrase it with the words the skill would use
("tail a log", not "watch the thing churn"). A miss is worth a second query with
different words before concluding nothing exists.

## Related

- [auto-tail](../auto-tail/SKILL.md) — follow a log a background job is writing
- [first-party conventions](../axeskills-first-party-conventions.md) — how a skill here gets published as ours
