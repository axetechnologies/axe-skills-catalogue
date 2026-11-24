-- Serving layer for a database imported from a rich-build snapshot (scripts/import_snapshot.py).
--
-- Kept apart from schema.sql on purpose: Registry() runs schema.sql against whatever database it is
-- pointed at, and rolling back to the old database must not leave empty v2 tables in it. The server
-- looks for skill_cards at start-up and falls back to the plain registry path when it is absent.

-- One row per skill name as the list endpoint serves it. seq is the position in the order the rich
-- build lists (name, binary collation), so a page is a range scan rather than an OFFSET walk.
-- card holds the stored card object as JSON; its install string carries the literal @@HOST@@ where the
-- request host goes, because the rich build reports the host that served the request.
CREATE TABLE IF NOT EXISTS skill_cards (
    tenant_id  TEXT    NOT NULL REFERENCES tenants(tenant_id),
    name       TEXT    NOT NULL,
    version    TEXT    NOT NULL,
    seq        INTEGER NOT NULL,
    card       TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    verified   INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS skill_cards_seq ON skill_cards (tenant_id, seq);
CREATE INDEX IF NOT EXISTS skill_cards_category ON skill_cards (tenant_id, category, seq);

-- Version strings in publication order, for /versions. Where only the latest version of a skill is
-- known this is a single row; older versions have no skills row (their bodies were never captured).
CREATE TABLE IF NOT EXISTS skill_versions (
    tenant_id  TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    ord        INTEGER NOT NULL,
    version    TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, name, ord)
);

-- Stored category facets, served as given: the rule that derived them is not recoverable.
CREATE TABLE IF NOT EXISTS categories (
    tenant_id  TEXT    NOT NULL,
    ord        INTEGER NOT NULL,
    category   TEXT    NOT NULL,
    label      TEXT    NOT NULL,
    count      INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, ord)
);

CREATE TABLE IF NOT EXISTS import_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
