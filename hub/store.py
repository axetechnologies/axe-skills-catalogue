"""Invariant: every read path that crosses a tenant boundary raises NotFound before returning data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class HubError(Exception):
    pass


class NotFound(HubError):
    pass


class Conflict(HubError):
    pass


_VALID_FORMATS = {"python", "skillmd", "catalog"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version_key(v: str) -> tuple:
    # Split at the first "-" to separate release from any pre-release label.
    # Pre-release versions (e.g. 1.1.0-candidate.20260909T120000Z) must sort BELOW
    # their corresponding release (1.1.0) so resolve() never hands a pending candidate
    # to a caller. The trailing (1,) vs (0,) tiebreaker achieves this: for the same
    # numeric triple, the release sorts strictly higher than any pre-release.
    release, _, pre = v.partition("-")
    numeric: list = []
    for p in release.split("."):
        try:
            numeric.append(int(p))
        except ValueError:
            numeric.append(p)
    is_release = (1,) if not pre else (0,)
    return tuple(numeric) + is_release


@dataclass(frozen=True)
class Skill:
    tenant_id: str
    name: str
    version: str
    format: str
    content: str
    checksum: str
    metadata: dict
    created_by: str
    created_at: str
    yanked_at: str | None

    @property
    def yanked(self) -> bool:
        return self.yanked_at is not None

    def record(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "version": self.version,
            "format": self.format,
            "checksum": self.checksum,
            "metadata": self.metadata,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "yanked_at": self.yanked_at,
        }


class Registry:
    def __init__(self, path: Path) -> None:
        self._path = path
        schema = (Path(__file__).parent / "schema.sql").read_text()
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema)
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def add_tenant(self, tenant_id: str, label: str) -> None:
        with self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO tenants (tenant_id, name, created_at) VALUES (?, ?, ?)",
                    (tenant_id, label, _now()),
                )
            except sqlite3.IntegrityError:
                raise Conflict(f"tenant {tenant_id!r} already exists")

    def tenants(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT tenant_id, name, created_at FROM tenants").fetchall()
        return [dict(r) for r in rows]

    def publish(
        self,
        tenant_id: str,
        name: str,
        version: str,
        content: str,
        *,
        actor: str,
        format: str = "skillmd",
        metadata: dict | None = None,
    ) -> Skill:
        if format not in _VALID_FORMATS:
            raise HubError(f"format must be one of {sorted(_VALID_FORMATS)}, got {format!r}")

        checksum = hashlib.sha256(content.encode()).hexdigest()
        meta_json = json.dumps(metadata or {})
        now = _now()

        with self._connect() as db:
            tenant_row = db.execute(
                "SELECT 1 FROM tenants WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
            if tenant_row is None:
                raise NotFound(f"tenant {tenant_id!r} not found")

            existing = db.execute(
                "SELECT 1 FROM skills WHERE tenant_id = ? AND name = ? AND version = ?",
                (tenant_id, name, version),
            ).fetchone()
            if existing is not None:
                raise Conflict(
                    f"{tenant_id!r}/{name}@{version} already exists; publish a new version"
                )

            db.execute(
                """INSERT INTO skills
                   (tenant_id, name, version, format, content, checksum, metadata,
                    created_by, created_at, yanked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (tenant_id, name, version, format, content, checksum, meta_json, actor, now),
            )
            # Publication is the event a client's compliance team asks about
            # first. skills.created_by answers "who", but only for versions that
            # still exist; the audit log has to answer it for yanked ones too.
            db.execute(
                "INSERT INTO audit (tenant_id, actor, action, skill_name, version, at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, actor, "publish", name, version, now),
            )

        return Skill(
            tenant_id=tenant_id,
            name=name,
            version=version,
            format=format,
            content=content,
            checksum=checksum,
            metadata=metadata or {},
            created_by=actor,
            created_at=now,
            yanked_at=None,
        )

    def yank(self, tenant_id: str, name: str, version: str, *, actor: str) -> None:
        now = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT yanked_at FROM skills WHERE tenant_id = ? AND name = ? AND version = ?",
                (tenant_id, name, version),
            ).fetchone()
            if row is None or row["yanked_at"] is not None:
                raise NotFound(f"{tenant_id!r}/{name}@{version} not found or already yanked")
            db.execute(
                "UPDATE skills SET yanked_at = ? WHERE tenant_id = ? AND name = ? AND version = ?",
                (now, tenant_id, name, version),
            )
            db.execute(
                "INSERT INTO audit (tenant_id, actor, action, skill_name, version, at) VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, actor, "yank", name, version, now),
            )

    def list(self, tenant_id: str, *, include_yanked: bool = False) -> list[dict]:
        sql = (
            "SELECT tenant_id, name, version, format, checksum, metadata, "
            "created_by, created_at, yanked_at FROM skills WHERE tenant_id = ?"
        )
        params: list = [tenant_id]
        if not include_yanked:
            sql += " AND yanked_at IS NULL"
        sql += " ORDER BY name, created_at"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def search(self, tenant_id: str, query: str) -> list[dict]:
        pattern = f"%{query}%"
        with self._connect() as db:
            rows = db.execute(
                "SELECT tenant_id, name, version, format, checksum, metadata, "
                "created_by, created_at, yanked_at "
                "FROM skills "
                "WHERE tenant_id = ? AND yanked_at IS NULL AND (name LIKE ? OR metadata LIKE ?) "
                "ORDER BY name",
                (tenant_id, pattern, pattern),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result

    def versions(self, tenant_id: str, name: str) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT version FROM skills WHERE tenant_id = ? AND name = ? ORDER BY created_at",
                (tenant_id, name),
            ).fetchall()
        return [r["version"] for r in rows]

    def resolve(self, tenant_id: str, name: str, version: str | None = None) -> Skill:
        with self._connect() as db:
            if version is not None:
                row = db.execute(
                    "SELECT * FROM skills WHERE tenant_id = ? AND name = ? AND version = ?",
                    (tenant_id, name, version),
                ).fetchone()
                if row is None:
                    raise NotFound(f"{tenant_id!r}/{name}@{version} not found")
            else:
                rows = db.execute(
                    "SELECT * FROM skills WHERE tenant_id = ? AND name = ? AND yanked_at IS NULL",
                    (tenant_id, name),
                ).fetchall()
                if not rows:
                    raise NotFound(f"{tenant_id!r}/{name} not found")
                row = max(rows, key=lambda r: _version_key(r["version"]))

        return Skill(
            tenant_id=row["tenant_id"],
            name=row["name"],
            version=row["version"],
            format=row["format"],
            content=row["content"],
            checksum=row["checksum"],
            metadata=json.loads(row["metadata"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            yanked_at=row["yanked_at"],
        )

    def fetch(self, tenant_id: str, name: str, version: str | None = None, *, actor: str) -> Skill:
        skill = self.resolve(tenant_id, name, version)
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit (tenant_id, actor, action, skill_name, version, at) VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_id, actor, "fetch", name, skill.version, now),
            )
        return skill

    def audit(self, tenant_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM audit WHERE tenant_id = ? ORDER BY id",
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_outcome(
        self,
        tenant_id: str,
        skill_name: str,
        version: str,
        *,
        actor: str,
        outcome: str,
        session_id: str | None = None,
        error_msg: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        if outcome not in ("success", "failure", "error"):
            raise HubError(f"outcome must be 'success', 'failure', or 'error', got {outcome!r}")
        with self._connect() as db:
            tenant_row = db.execute(
                "SELECT 1 FROM tenants WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
            if tenant_row is None:
                raise NotFound(f"tenant {tenant_id!r} not found")
            # Outcomes are the input to eval-gated promotion, so a row naming a
            # skill+version that was never published is worse than no row: a
            # typo'd version silently attributes real successes to something
            # nothing will ever read, leaving the version that actually ran
            # looking untested. yanked_at is ignored on purpose -- a skill that
            # ran before it was yanked still produced a real outcome.
            skill_row = db.execute(
                "SELECT 1 FROM skills WHERE tenant_id = ? AND name = ? AND version = ?",
                (tenant_id, skill_name, version),
            ).fetchone()
            if skill_row is None:
                raise NotFound(f"skill {skill_name!r} version {version!r} not found")
            db.execute(
                """INSERT INTO skill_outcomes
                   (tenant_id, skill_name, version, actor, session_id, outcome, error_msg, latency_ms, at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tenant_id, skill_name, version, actor, session_id, outcome, error_msg, latency_ms, _now()),
            )

    def outcomes(
        self,
        tenant_id: str,
        skill_name: str | None = None,
        version: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM skill_outcomes WHERE tenant_id = ?"
        params: list = [tenant_id]
        if skill_name is not None:
            sql += " AND skill_name = ?"
            params.append(skill_name)
        if version is not None:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY id"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def outcome_rate(self, tenant_id: str, skill_name: str, version: str) -> tuple[float, int]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT outcome FROM skill_outcomes WHERE tenant_id = ? AND skill_name = ? AND version = ?",
                (tenant_id, skill_name, version),
            ).fetchall()
        count = len(rows)
        if count == 0:
            return 0.0, 0
        successes = sum(1 for r in rows if r["outcome"] == "success")
        return successes / count, count

    def insert_candidate(
        self,
        tenant_id: str,
        skill_name: str,
        based_on_version: str,
        proposed_version: str,
        *,
        optimizer_run_id: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO skill_candidates
                   (tenant_id, skill_name, based_on_version, proposed_version,
                    optimizer_run_id, status, created_at, resolved_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)""",
                (tenant_id, skill_name, based_on_version, proposed_version,
                 optimizer_run_id, _now()),
            )

    def resolve_candidate(
        self,
        tenant_id: str,
        skill_name: str,
        proposed_version: str,
        *,
        status: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE skill_candidates SET status = ?, resolved_at = ?
                   WHERE tenant_id = ? AND skill_name = ? AND proposed_version = ?""",
                (status, _now(), tenant_id, skill_name, proposed_version),
            )

    def insert_promotion_decision(
        self,
        tenant_id: str,
        skill_name: str,
        candidate_version: str,
        incumbent_version: str,
        *,
        candidate_pass_rate: float,
        incumbent_pass_rate: float,
        decision: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO promotion_decisions
                   (tenant_id, skill_name, candidate_version, incumbent_version,
                    candidate_pass_rate, incumbent_pass_rate, decision, decided_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tenant_id, skill_name, candidate_version, incumbent_version,
                 candidate_pass_rate, incumbent_pass_rate, decision, _now()),
            )

    def promotion_decisions(self, tenant_id: str, skill_name: str | None = None) -> list[dict]:
        sql = "SELECT * FROM promotion_decisions WHERE tenant_id = ?"
        params: list = [tenant_id]
        if skill_name is not None:
            sql += " AND skill_name = ?"
            params.append(skill_name)
        sql += " ORDER BY id"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
