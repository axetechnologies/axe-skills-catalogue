"""Invariant: SkillSource.resolve is tenant-scoped; LegacySource violates this by design and is documented as such."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from hub.store import HubError, Registry


@runtime_checkable
class SkillSource(Protocol):
    name: str

    def list(self, tenant_id: str) -> list[dict]: ...
    def search(self, tenant_id: str, query: str) -> list[dict]: ...
    def resolve(self, tenant_id: str, name: str, version: str | None = None): ...


class LegacySource:
    """Adapter over on-disk skill_*.py files.

    tenant_id is intentionally ignored on every method. This is not an
    oversight — it is precisely the property that makes this backend
    unofferable to a client. It is preserved here rather than papered over
    so the comparison with RegistrySource is honest.
    """

    name = "legacy"

    def __init__(self, root: Path) -> None:
        self._root = root

    def _scan(self) -> list[dict]:
        skills = []
        for p in sorted(self._root.glob("skill_*.py")):
            skill_name = p.stem[len("skill_"):]
            description = ""
            try:
                source = p.read_text()
                tree = ast.parse(source)
                if (
                    tree.body
                    and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)
                ):
                    description = tree.body[0].value.value
            except Exception:
                pass
            skills.append({
                "name": skill_name,
                "version": "0",
                "created_by": "unknown",
                "description": description,
            })
        return skills

    def list(self, tenant_id: str) -> list[dict]:  # noqa: ARG002
        return self._scan()

    def search(self, tenant_id: str, query: str) -> list[dict]:  # noqa: ARG002
        q = query.lower()
        return [s for s in self._scan() if q in s["name"].lower() or q in s["description"].lower()]

    def resolve(self, tenant_id: str, name: str, version: str | None = None):  # noqa: ARG002
        from hub.store import NotFound
        for s in self._scan():
            if s["name"] == name:
                return s
        raise NotFound(f"legacy skill {name!r} not found")


class RegistrySource:
    name = "registry"

    def __init__(self, registry: Registry) -> None:
        self._reg = registry

    def list(self, tenant_id: str) -> list[dict]:
        return self._reg.list(tenant_id)

    def search(self, tenant_id: str, query: str) -> list[dict]:
        return self._reg.search(tenant_id, query)

    def resolve(self, tenant_id: str, name: str, version: str | None = None):
        return self._reg.resolve(tenant_id, name, version)


def source_from_env(env: dict | None = None) -> SkillSource:
    e = env if env is not None else dict(os.environ)
    backend = e.get("AXE_HUB_BACKEND", "registry")
    if backend == "legacy":
        root = Path(e.get("AXE_HUB_LEGACY_ROOT", str(Path.home() / ".axe" / "skills")))
        return LegacySource(root)
    if backend == "registry":
        db_path = Path(e.get("AXE_HUB_DB", "hub.db"))
        return RegistrySource(Registry(db_path))
    raise HubError(f"AXE_HUB_BACKEND={backend!r} is not valid; choose 'legacy' or 'registry'")


def compare(legacy: LegacySource, registry: RegistrySource, tenant_id: str) -> dict:
    legacy_names = {s["name"] for s in legacy.list(tenant_id)}
    registry_names = {s["name"] for s in registry.list(tenant_id)}
    return {
        "only_legacy": sorted(legacy_names - registry_names),
        "only_registry": sorted(registry_names - legacy_names),
        "both": sorted(legacy_names & registry_names),
    }
