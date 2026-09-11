-- AXE Skills Hub — registry schema.
--
-- Tenancy is enforced in the schema rather than in the application, because an
-- application-layer tenant filter is one forgotten WHERE clause away from a
-- cross-tenant read. Every query path here takes tenant_id as part of a key.
--
-- Skills are immutable once written. Publishing "the same" skill writes a new
-- version row; nothing is ever updated in place. That is what makes provenance
-- answerable after the fact rather than a field somebody hopes was maintained.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    format      TEXT NOT NULL CHECK (format IN ('python', 'skillmd', 'catalog')),
    content     TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    yanked_at   TEXT,
    PRIMARY KEY (tenant_id, name, version)
);

-- Search and listing are always tenant-first; an index that did not lead with
-- tenant_id would let a scan cross the boundary the primary key protects.
CREATE INDEX IF NOT EXISTS skills_by_tenant ON skills (tenant_id, name);

-- Append-only. Every read of a skill body lands here, which is what makes the
-- hub something an enterprise client can be given access to rather than trusted with.
CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    skill_name  TEXT,
    version     TEXT,
    at          TEXT NOT NULL,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS skill_outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    skill_name  TEXT NOT NULL,
    version     TEXT NOT NULL,
    actor       TEXT NOT NULL,
    session_id  TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'error')),
    error_msg   TEXT,
    latency_ms  REAL,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_tsv ON skill_outcomes (tenant_id, skill_name, version);

CREATE TABLE IF NOT EXISTS skill_candidates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id),
    skill_name        TEXT NOT NULL,
    based_on_version  TEXT NOT NULL,
    proposed_version  TEXT NOT NULL,
    optimizer_run_id  TEXT,
    status            TEXT NOT NULL CHECK (status IN ('pending', 'promoted', 'rejected')),
    created_at        TEXT NOT NULL,
    resolved_at       TEXT
);

CREATE TABLE IF NOT EXISTS promotion_decisions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id             TEXT NOT NULL,
    skill_name            TEXT NOT NULL,
    candidate_version     TEXT NOT NULL,
    incumbent_version     TEXT NOT NULL,
    candidate_pass_rate   REAL NOT NULL,
    incumbent_pass_rate   REAL NOT NULL,
    decision              TEXT NOT NULL CHECK (decision IN ('promoted', 'tied', 'rejected', 'degraded-yanked')),
    decided_at            TEXT NOT NULL
);
