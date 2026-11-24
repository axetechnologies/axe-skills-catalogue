#!/usr/bin/env python3
"""Add or remove the kind columns (hub/kinds.py) on a copy of a served hub database.

    python3 scripts/migrate_kinds.py --db COPY up      # add kind; every existing row reads as a skill
    python3 scripts/migrate_kinds.py --db COPY down    # delete the plugins and connectors, drop kind

up rewrites no row. down leaves the skills' rows, order and facets as they were, so the result serves exactly
what the database served before up. Live databases are refused, as by the merges.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_hermes_kinds import refuse, skills_digest  # noqa: E402
from hub import kinds  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True, help="a copy of the served database; written in place")
    ap.add_argument("direction", choices=("up", "down"))
    args = ap.parse_args()
    db = args.db.expanduser()
    why = refuse(db)
    if why:
        print(why, file=sys.stderr)
        return 2
    con = sqlite3.connect(db)
    before = skills_digest(con)
    with con:
        out = {"applied": kinds.up(con)} if args.direction == "up" else kinds.down(con)
    out["skills_untouched"] = skills_digest(con) == before
    out["integrity_check"] = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    print(json.dumps(out, indent=2))
    return 0 if out["skills_untouched"] and out["integrity_check"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
