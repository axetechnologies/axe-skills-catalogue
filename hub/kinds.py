"""What kind of thing a catalogue entry is: a skill, a plugin or a connector.

The kind lives on the serving tables (skill_cards, categories) of an imported database, not on skills: the
registry schema is run against every database Registry() opens, and a column added there could not be added
to an existing file with CREATE TABLE IF NOT EXISTS. On the serving tables it is one ALTER TABLE ... ADD
COLUMN with a constant default, so the rows already there read as skills without being rewritten.

Within a tenant each kind is one contiguous range of seq, skills first, so a list page of one kind is still
a range scan and the skills keep the seq they had before any plugin or connector arrived.
"""
from __future__ import annotations

import sqlite3

KINDS = ("skill", "plugin", "connector")
DEFAULT = "skill"
LABELS = {"skill": "Skills", "plugin": "Plugins", "connector": "Connectors"}
META_KEY = "schema:kinds"
_CHECK = "CHECK (kind IN ('skill', 'plugin', 'connector'))"


def rank(kind: str) -> int:
    return KINDS.index(kind)


def present(con: sqlite3.Connection) -> bool:
    return any(r[1] == "kind" for r in con.execute("PRAGMA table_info(skill_cards)"))


def up(con: sqlite3.Connection) -> bool:
    """Add the kind columns. False when they are already there; the caller commits."""
    if present(con):
        return False
    con.execute(f"ALTER TABLE skill_cards ADD COLUMN kind TEXT NOT NULL DEFAULT 'skill' {_CHECK}")
    con.execute(f"ALTER TABLE categories ADD COLUMN kind TEXT NOT NULL DEFAULT 'skill' {_CHECK}")
    con.execute("CREATE INDEX IF NOT EXISTS skill_cards_kind ON skill_cards (tenant_id, kind, seq)")
    con.execute("INSERT OR REPLACE INTO import_meta (key, value) VALUES (?, '1')", (META_KEY,))
    return True


def down(con: sqlite3.Connection) -> dict:
    """Remove every non-skill entry and the kind columns. The skills keep their rows and seq; the caller commits."""
    if not present(con):
        return {"applied": False}
    gone = con.execute("SELECT tenant_id, name FROM skill_cards WHERE kind != ?", (DEFAULT,)).fetchall()
    out = {"applied": True, "entries_removed": len(gone)}
    for table in ("skills", "skill_versions"):
        out[f"{table}_rows_removed"] = sum(
            con.execute(f"DELETE FROM {table} WHERE tenant_id = ? AND name = ?", key).rowcount for key in gone)
    out["skill_cards_rows_removed"] = con.execute(
        "DELETE FROM skill_cards WHERE kind != ?", (DEFAULT,)).rowcount
    out["categories_rows_removed"] = con.execute("DELETE FROM categories WHERE kind != ?", (DEFAULT,)).rowcount
    con.execute("DROP INDEX IF EXISTS skill_cards_kind")
    con.execute("ALTER TABLE skill_cards DROP COLUMN kind")
    con.execute("ALTER TABLE categories DROP COLUMN kind")
    con.execute("DELETE FROM import_meta WHERE key = ?", (META_KEY,))
    return out
