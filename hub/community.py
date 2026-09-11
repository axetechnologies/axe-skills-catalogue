"""Community federation for the AXE Skills Hub.

Federated records are catalog metadata, NOT vetted executable content. A
listed entry is third-party code that runs outside this system control.
Nothing federated reaches a client tenant without an explicit human promote
call. The quarantine tenant is the sole landing zone for all federation.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from hub.store import Conflict, HubError, NotFound, Registry

_QUARANTINE_TENANT = "community-quarantine"
_SMITHERY_BASE = "https://registry.smithery.ai/servers"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CommunityEntry:
    source: str
    external_id: str
    name: str
    description: str
    homepage: str
    verified: bool
    use_count: int
    raw: dict


@dataclass
class FederationReport:
    added: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


class SmitheryCatalog:
    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key

    def _get_page(self, page: int, page_size: int) -> dict:
        params = urllib.parse.urlencode({"q": "", "limit": page_size, "page": page})
        url = f"{_SMITHERY_BASE}?{params}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        if self._api_key:
            req.add_header("Authorization", f"Bearer {self._api_key}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def fetch(self, limit: int | None = None, page_size: int = 100) -> Iterator[CommunityEntry]:
        yielded = 0
        page = 1
        total_pages = None

        while True:
            try:
                data = self._get_page(page, page_size)
            except urllib.error.URLError as exc:
                raise HubError(f"Smithery fetch failed on page {page}: {exc}") from exc

            servers = data.get("servers") or []
            pagination = data.get("pagination") or {}
            if total_pages is None:
                total_pages = pagination.get("totalPages", 1)

            for raw in servers:
                if limit is not None and yielded >= limit:
                    return
                try:
                    if raw.get("inactive") or raw.get("unlisted"):
                        continue
                    entry = CommunityEntry(
                        source="smithery",
                        external_id=str(raw.get("qualifiedName") or raw.get("id") or ""),
                        name=str(raw.get("displayName") or raw.get("slug") or raw.get("id") or ""),
                        description=str(raw.get("description") or ""),
                        homepage=str(raw.get("homepage") or ""),
                        verified=bool(raw.get("verified", False)),
                        use_count=int(raw.get("useCount") or 0),
                        raw=raw,
                    )
                    yield entry
                    yielded += 1
                except Exception:
                    continue

            if page >= (total_pages or 1):
                break
            page += 1


def _ensure_quarantine(registry: Registry) -> None:
    existing = [t["tenant_id"] for t in registry.tenants()]
    if _QUARANTINE_TENANT not in existing:
        try:
            registry.add_tenant(_QUARANTINE_TENANT, "Community Quarantine")
        except Conflict:
            pass


def _entry_name(entry: CommunityEntry) -> str:
    safe = entry.external_id.replace("/", "__").replace(" ", "_")
    return f"community__{entry.source}__{safe}"


_TAXONOMY_KEYS = {
    "category": ("category",),
    "category_label": ("categoryLabel", "category_label"),
    "tags": ("tags",),
    "platforms": ("platforms",),
    "author": ("author",),
    "license": ("license",),
    "upstream_version": ("version",),
    "env_vars": ("envVars", "env_vars"),
    "commands": ("commands",),
    "docs_path": ("docsPath", "docs_path"),
}


def _taxonomy(entry: CommunityEntry) -> dict:
    """Lift the provider's own classification out of entry.raw.

    Providers disagree on casing (the upstream is camelCase), so each field accepts
    several aliases. Kept generic on purpose: community.py must not learn the
    shape of any one upstream.
    """
    raw = entry.raw or {}
    out: dict = {}
    for field_name, aliases in _TAXONOMY_KEYS.items():
        for alias in aliases:
            if alias in raw and raw[alias] not in (None, "", [], {}):
                out[field_name] = raw[alias]
                break
    out.setdefault("category", "uncategorized")
    return out


def _bump(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        parts.append("1")
    return ".".join(parts)


def federate(
    registry: Registry,
    catalog: SmitheryCatalog,
    *,
    tenant_id: str,
    actor: str,
    limit: int | None = None,
    dry_run: bool = False,
) -> FederationReport:
    report = FederationReport()
    # NOTE: tenant_id is accepted but ignored -- everything lands in
    # _QUARANTINE_TENANT. Honouring it would relocate existing callers' rows,
    # so it is left as-is and tracked separately. Pass the constant knowingly.
    _ensure_quarantine(registry)

    for entry in catalog.fetch(limit=limit):
        if not entry.external_id or not entry.name:
            report.skipped += 1
            continue

        name = _entry_name(entry)
        descriptor = {
            "source": entry.source,
            "external_id": entry.external_id,
            "name": entry.name,
            "description": entry.description,
            "homepage": entry.homepage,
            "verified": entry.verified,
            "use_count": entry.use_count,
            "taxonomy": _taxonomy(entry),
        }
        content = json.dumps(descriptor, sort_keys=True)
        new_checksum = hashlib.sha256(content.encode()).hexdigest()

        meta = {
            "source": entry.source,
            "external_id": entry.external_id,
            "homepage": entry.homepage,
            "verified": entry.verified,
            "use_count": entry.use_count,
            "federated_at": _now(),
            "quarantined": True,
            "taxonomy": _taxonomy(entry),
        }

        try:
            existing_versions = registry.versions(_QUARANTINE_TENANT, name)
            if existing_versions:
                try:
                    latest = registry.resolve(_QUARANTINE_TENANT, name, existing_versions[-1])
                    if latest.checksum == new_checksum:
                        report.unchanged += 1
                        continue
                except NotFound:
                    pass
                next_ver = _bump(existing_versions[-1])
            else:
                next_ver = "1.0.0"

            if not dry_run:
                registry.publish(
                    _QUARANTINE_TENANT,
                    name,
                    next_ver,
                    content,
                    actor=actor,
                    format="catalog",
                    metadata=meta,
                )
            report.added += 1
        except Exception as exc:
            report.failed.append((name, str(exc)))

    return report


def promote(
    registry: Registry,
    *,
    name: str,
    from_tenant: str,
    to_tenant: str,
    actor: str,
    version: str = "1.0.0",
) -> None:
    skill = registry.resolve(from_tenant, name)
    if not skill.metadata.get("quarantined"):
        raise HubError(
            f"{from_tenant!r}/{name} is not marked quarantined; promote only accepts quarantined entries"
        )

    new_meta = dict(skill.metadata)
    new_meta["quarantined"] = False
    new_meta["promoted_by"] = actor
    new_meta["promoted_at"] = _now()

    existing = registry.versions(to_tenant, name)
    if existing:
        target_version = _bump(existing[-1])
    else:
        target_version = version

    registry.publish(
        to_tenant,
        name,
        target_version,
        skill.content,
        actor=actor,
        format=skill.format,
        metadata=new_meta,
    )

    with registry._connect() as db:
        db.execute(
            "INSERT INTO audit (tenant_id, actor, action, skill_name, version, at, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                to_tenant,
                actor,
                "promote",
                name,
                target_version,
                _now(),
                json.dumps({"from_tenant": from_tenant, "source_version": skill.version}),
            ),
        )
