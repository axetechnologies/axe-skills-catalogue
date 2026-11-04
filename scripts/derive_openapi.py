#!/usr/bin/env python3
"""Derive hub/openapi.json from the rich build's document, corrected to what this server implements.

    python3 scripts/derive_openapi.py [SNAPSHOT_DIR]

Changes from the snapshot document: the list route documents its real parameters and its real envelope
(object/data/limit/offset/total/has_more, not data/meta), the search route documents q/limit/offset,
the get route documents ?version, the servers block is a placeholder the server replaces with the
request's own origin, and the 405 text names HEAD.
"""
import json
import sys
from pathlib import Path

snap = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".axe/skills-hub-v2/snapshot"
doc = json.loads((snap / "discovery" / "openapi.json").read_text())
paths = doc["paths"]

def param(name, desc, schema, where="query"):
    return {"name": name, "in": where, "required": False, "schema": schema, "description": desc}

lst = paths["/v1/skills"]["get"]
row_schema = lst["responses"]["200"]["content"]["application/json"]["schema"]["items"]
lst["description"] = ("Paged: default 200, maximum 1000 (larger values are capped). limit<=0 returns an empty "
                      "array. Without envelope the body is a bare array; with ?envelope=1 it is "
                      "{object, data, limit, offset, total, has_more}.")
lst["parameters"] = [
    param("limit", "Page size, 1..1000, default 200.", {"type": "integer", "default": 200, "maximum": 1000}),
    param("offset", "Rows to skip, in name order.", {"type": "integer", "default": 0, "minimum": 0}),
    param("envelope", "1 returns the paged envelope instead of a bare array.", {"type": "string", "enum": ["0", "1"]}),
] + lst["parameters"]
lst["responses"]["200"]["content"]["application/json"]["schema"] = {"oneOf": [
    {"type": "array", "items": row_schema},
    {"type": "object", "properties": {
        "object": {"type": "string", "enum": ["list"]}, "data": {"type": "array", "items": row_schema},
        "limit": {"type": "integer"}, "offset": {"type": "integer"}, "total": {"type": "integer"},
        "has_more": {"type": "boolean"}}, "required": ["object", "data", "limit", "offset", "total", "has_more"]},
]}

srch = paths["/v1/skills/search"]["get"]
srch["description"] = ("Case-insensitive substring match over the skill name and its stored metadata, ordered "
                       "by name and paged like the list. A miss is an empty array.")
srch["parameters"] = [
    param("q", "Text to look for.", {"type": "string"}),
    param("limit", "Page size, 1..1000, default 200.", {"type": "integer", "default": 200, "maximum": 1000}),
    param("offset", "Rows to skip.", {"type": "integer", "default": 0}),
] + srch.get("parameters", [])

get = paths["/v1/skills/{name}"]["get"]
get["parameters"] = get["parameters"] + [
    param("version", "Exact version. Only the current version of a skill has a stored body.", {"type": "string"})]

for p in paths.values():
    for op in p.values():
        r405 = op.get("responses", {}).get("405")
        if r405:
            r405["description"] = "Verb refused. A read-only origin accepts GET, HEAD and OPTIONS."

doc["servers"] = [{"url": "http://localhost"}]
Path(__file__).resolve().parent.parent.joinpath("hub", "openapi.json").write_text(json.dumps(doc, indent=2) + "\n")
print("wrote hub/openapi.json")
