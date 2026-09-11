"""Invariant: ingest never raises; failures accumulate in IngestReport.failed and the run continues."""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from hub.store import NotFound, Registry


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def parse_skillmd(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text

    end = text.find(chr(10) + "---", 3)
    if end == -1:
        return {}, text

    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip(chr(10))

    meta: dict = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1]
            meta[key.strip()] = [v.strip().strip(chr(39) + chr(34)) for v in inner.split(',') if v.strip()]
        else:
            meta[key.strip()] = raw

    return meta, body


def discover_skillmd(root: Path) -> Iterator[tuple[str, dict, str]]:
    for p in sorted(root.rglob("SKILL.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        meta, body = parse_skillmd(text)
        name = meta.get("name") or p.parent.name
        evals_path = p.parent / "evals.json"
        if evals_path.exists():
            try:
                import json as _json
                meta["evals"] = _json.loads(evals_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        yield name, meta, text


def discover_python(root: Path) -> Iterator[tuple[str, dict, str]]:
    for p in sorted(root.glob("skill_*.py")):
        name = p.stem[len("skill_"):]
        try:
            source = p.read_text(encoding="utf-8")
        except Exception:
            continue
        description = ""
        try:
            tree = ast.parse(source)
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
            ):
                description = tree.body[0].value.value
        except Exception:
            pass
        yield name, {"name": name, "description": description}, source


def _bump_patch(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        parts.append("1")
    return ".".join(parts)


def ingest(
    registry: Registry,
    tenant_id: str,
    source_root: Path,
    *,
    actor: str,
    format: str,
    version: str = "1.0.0",
    dry_run: bool = False,
) -> IngestReport:
    report = IngestReport()

    if format == "skillmd":
        items = list(discover_skillmd(source_root))
    elif format == "python":
        items = list(discover_python(source_root))
    else:
        report.failed.append(("*", f"unknown format {format!r}"))
        return report

    for name, meta, content in items:
        try:
            new_checksum = hashlib.sha256(content.encode()).hexdigest()
            existing_versions = registry.versions(tenant_id, name)

            if existing_versions:
                latest_version = existing_versions[-1]
                try:
                    existing_skill = registry.resolve(tenant_id, name, latest_version)
                    if existing_skill.checksum == new_checksum:
                        report.unchanged.append(name)
                        continue
                except NotFound:
                    pass
                next_version = _bump_patch(latest_version)
                if not dry_run:
                    registry.publish(
                        tenant_id, name, next_version, content,
                        actor=actor, format=format, metadata=meta,
                    )
                report.updated.append(name)
            else:
                if not dry_run:
                    registry.publish(
                        tenant_id, name, version, content,
                        actor=actor, format=format, metadata=meta,
                    )
                report.added.append(name)
        except Exception as exc:
            report.failed.append((name, str(exc)))

    return report
