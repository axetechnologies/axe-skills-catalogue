"""Invariant: a user skill becomes verified only through promote(), which copies it to another database and never edits the source row."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from hub.store import Conflict, HubError, NotFound, Registry

MAX_CONTENT_BYTES = 256 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise NotFound(f"database {str(path)!r} not found")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _is_quarantined(meta: dict) -> bool:
    return meta.get("quarantined") is True


def list_quarantined(db_path: Path) -> list[dict]:
    with _open_ro(db_path) as db:
        rows = db.execute(
            "SELECT tenant_id, name, version, metadata, length(CAST(content AS BLOB)) AS size, created_at "
            "FROM skills WHERE yanked_at IS NULL ORDER BY created_at, tenant_id, name"
        ).fetchall()
    out = []
    for r in rows:
        meta = json.loads(r["metadata"])
        if _is_quarantined(meta) and meta.get("source") == "user":
            out.append({"tenant": r["tenant_id"], "name": r["name"], "version": r["version"],
                        "size": r["size"], "created_at": r["created_at"]})
    return out


def get_skill(db_path: Path, tenant: str, name: str, version: str) -> dict:
    with _open_ro(db_path) as db:
        row = db.execute(
            "SELECT * FROM skills WHERE tenant_id = ? AND name = ? AND version = ?",
            (tenant, name, version),
        ).fetchone()
    if row is None:
        raise NotFound(f"{tenant!r}/{name}@{version} not found")
    d = dict(row)
    d["metadata"] = json.loads(d["metadata"])
    return d


def _check_reviewer(reviewer: str) -> None:
    if not reviewer or not reviewer.strip():
        raise HubError("--reviewer is required")


def promote(src_db: Path, dst_db: Path, tenant: str, name: str, version: str, *,
            to_tenant: str, reviewer: str) -> str:
    _check_reviewer(reviewer)
    if src_db.resolve() == dst_db.resolve():
        raise HubError("source and target databases must differ")
    row = get_skill(src_db, tenant, name, version)
    if row["yanked_at"] is not None:
        raise HubError(f"{tenant!r}/{name}@{version} is yanked")
    if not _is_quarantined(row["metadata"]):
        raise HubError(f"{tenant!r}/{name}@{version} is not quarantined; only quarantined skills can be promoted")
    size = len(row["content"].encode())
    if size > MAX_CONTENT_BYTES:
        raise HubError(f"content is {size} bytes, over the {MAX_CONTENT_BYTES} byte limit")

    dst = Registry(dst_db)
    if version in dst.versions(to_tenant, name):
        raise Conflict(f"{to_tenant!r}/{name}@{version} already exists in the target; already promoted")
    if to_tenant not in [t["tenant_id"] for t in dst.tenants()]:
        dst.add_tenant(to_tenant, to_tenant)

    now = _now()
    meta = dict(row["metadata"])
    meta.update({"verified": True, "quarantined": False, "reviewed_by": reviewer,
                 "reviewed_at": now, "promoted_from": f"{tenant}/{name}@{version}"})
    dst.publish(to_tenant, name, version, row["content"], actor=reviewer,
                format=row["format"], metadata=meta)
    with dst._connect() as db:
        db.execute(
            "INSERT INTO audit (tenant_id, actor, action, skill_name, version, at, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (to_tenant, reviewer, "promote", name, version, now,
             json.dumps({"from_tenant": tenant, "source_db": src_db.name})),
        )
    return f"{to_tenant}/{name}@{version}"


def reject(db_path: Path, tenant: str, name: str, version: str, *, reviewer: str) -> None:
    _check_reviewer(reviewer)
    row = get_skill(db_path, tenant, name, version)
    if not _is_quarantined(row["metadata"]):
        raise HubError(f"{tenant!r}/{name}@{version} is not quarantined; only quarantined skills can be rejected")
    Registry(db_path).yank(tenant, name, version, actor=reviewer)
