"""Hermes Agent catalog provider for the federation tier.

Same `fetch() -> Iterator[CommunityEntry]` contract as SmitheryCatalog, so
`hub.community.federate()` drives it unchanged — including its sha256
content-addressing and quarantine landing.

The upstream is two static, unauthenticated JSON files on GitHub Pages. There
is no pagination and no rate limit, so the whole catalog arrives in one GET and
the correct consumer is a periodic full pull, not a crawler. Both URLs 302, so
every request must follow redirects.

Discovered via the `network-interception` skill; see that skill for the method.
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

from hub.community import CommunityEntry

_BASE = "https://hermes-agent.nousresearch.com/docs/api"
_SKILLS_URL = f"{_BASE}/skills.json"
_META_URL = f"{_BASE}/skills-meta.json"

# Hermes aggregates other registries. `built-in` is Hermes' own; the rest are
# third parties it federates, and ClawHub alone is ~76% of the catalog.
_FIRST_PARTY = {"built-in", "Anthropic", "OpenAI"}


def _read_source(src: str, timeout: int = 120) -> object:
    """Read a catalog source that may be a URL or a local path.

    Anything not starting with http(s):// is treated as a file on disk, so a
    cached copy can stand in for the live endpoint unchanged.
    """
    if not src.startswith(("http://", "https://")):
        return json.loads(pathlib.Path(src).read_text())
    return _get(src, timeout=timeout)


def _get(url: str, timeout: int = 120) -> object:
    # urllib follows 3xx by default; both endpoints redirect to
    # nousresearch.github.io. Losing this is the classic "endpoint is broken"
    # false negative -- a bare curl without -L returns "Redirecting...".
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "axe-skills-hub/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


@dataclass
class HermesManifest:
    total: int
    by_source: dict[str, int]
    generated_at: str

    @property
    def external_registries(self) -> list[str]:
        return sorted(s for s in self.by_source if s not in _FIRST_PARTY)


class HermesCatalog:
    name = "hermes"

    def __init__(self, *, skills_url: str | None = None, meta_url: str | None = None) -> None:
        self._skills_url = skills_url or os.environ.get("AXE_HERMES_SKILLS", _SKILLS_URL)
        self._meta_url = meta_url or os.environ.get("AXE_HERMES_META", _META_URL)

    def manifest(self) -> HermesManifest:
        data = _read_source(self._meta_url, timeout=30)
        return HermesManifest(
            total=data.get("totalSkills", 0),
            by_source=data.get("bySource", {}) or {},
            generated_at=data.get("indexGeneratedAt", ""),
        )

    def fetch(self, limit: int | None = None, page_size: int = 0) -> Iterator[CommunityEntry]:
        # page_size is accepted and ignored: the upstream is one static file.
        try:
            rows = _read_source(self._skills_url)
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(f"hermes catalog unreachable: {exc}") from exc

        if not isinstance(rows, list):
            raise RuntimeError(f"expected a JSON list, got {type(rows).__name__}")

        for i, row in enumerate(rows):
            if limit is not None and i >= limit:
                return
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            if not name:
                continue

            source = row.get("source") or "unknown"
            # Records carry metadata + a docsPath pointer, never a SKILL.md
            # body. Bodies need a per-skill fetch, so this tier is a catalogue.
            yield CommunityEntry(
                source=f"hermes:{source}",
                # No stable upstream ID exists: docsPath is empty for 90,501 of
                # 90,699 records, so source/name is the only available key. It
                # is not unique either -- 7,291 records share one -- so the
                # catalogue holds 83,408 distinct skills, not 90,699.
                external_id=f"{source}/{name}",
                name=name,
                description=(row.get("description") or "").strip(),
                homepage=self._homepage(row),
                verified=source in _FIRST_PARTY,
                use_count=0,  # upstream exposes no popularity signal
                raw=row,
            )

    def _homepage(self, row: dict) -> str:
        docs = (row.get("docsPath") or "").lstrip("/")
        return f"https://hermes-agent.nousresearch.com/{docs}" if docs else ""


def categorize(entry: CommunityEntry) -> dict:
    """The categorization/description block an agent needs to pick a skill.

Kept for callers that want the block directly. federate() now persists the
    same fields itself via hub.community._taxonomy, so ingest does not need
    this -- it is not a second source of truth.
    """
    raw = entry.raw or {}
    return {
        "category": raw.get("category") or "uncategorized",
        "category_label": raw.get("categoryLabel") or "Uncategorized",
        "tags": raw.get("tags") or [],
        "platforms": raw.get("platforms") or [],
        "author": raw.get("author") or "",
        "license": raw.get("license") or "",
        "version": raw.get("version") or "0",
        "env_vars": raw.get("envVars") or [],
        "commands": raw.get("commands") or [],
        "overview": raw.get("overview") or "",
        "docs_path": raw.get("docsPath") or "",
    }


if __name__ == "__main__":
    import argparse
    import collections

    ap = argparse.ArgumentParser(description="Inspect the Hermes catalog without ingesting.")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--manifest", action="store_true")
    args = ap.parse_args()

    cat = HermesCatalog()
    if args.manifest:
        m = cat.manifest()
        print(f"total={m.total} generated={m.generated_at}")
        print(f"external registries: {', '.join(m.external_registries)}")
        for src, n in sorted(m.by_source.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>7}  {src}")
        raise SystemExit(0)

    cats: collections.Counter = collections.Counter()
    for e in cat.fetch(limit=args.limit):
        c = categorize(e)
        cats[c["category"]] += 1
        print(f"{e.external_id:<45} [{c['category']}] {e.description[:60]}")
    print(f"\n{len(cats)} categories in sample: {dict(cats)}")
