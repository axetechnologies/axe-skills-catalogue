#!/usr/bin/env bash
# Ask the AXE Skills Hub which skill fits a task, in plain words.
#
# Wraps GET /v1/tools/find, which is ranked, compact and capped. The older
# /v1/skills/search returns rows alphabetically and cannot see the description
# column, so it is not the endpoint to build on.
set -euo pipefail

URL="${SKILLSHUB_URL:-https://skills.axe.onl}"
TENANT="${SKILLSHUB_TENANT:-community-quarantine}"
LIMIT="${SKILLSHUB_LIMIT:-8}"

usage() {
    cat >&2 <<'EOF'
usage: skillshub-find.sh <task in plain words>
       skillshub-find.sh --get <skill-name>

  --get   fetch one skill's full body, ready to read or run

env: SKILLSHUB_URL     (default https://skills.axe.onl)
     SKILLSHUB_TENANT  (default community-quarantine; use "axe" for first-party)
     SKILLSHUB_KEY     sent as X-AXE-Key when set, instead of the tenant header
     SKILLSHUB_LIMIT   (default 8)
EOF
    exit 2
}

[ $# -ge 1 ] || usage

# A key maps to its tenant server-side. The header is the fallback for a local
# run, and an unauthenticated request is a 403 rather than a guessed tenant.
if [ -n "${SKILLSHUB_KEY:-}" ]; then
    AUTH=(-H "X-AXE-Key: ${SKILLSHUB_KEY}")
else
    AUTH=(-H "X-AXE-Tenant: ${TENANT}")
fi

fetch() {
    # --fail-with-body so a 403 prints the reason instead of an empty success.
    curl -sS --fail-with-body --max-time 30 "${AUTH[@]}" "$1"
}

if [ "$1" = "--get" ]; then
    [ $# -eq 2 ] || usage
    fetch "${URL%/}/v1/skills/$2" | python3 -c '
import json, sys
d = json.load(sys.stdin)
tax = (d.get("metadata") or {}).get("taxonomy") or {}
print("# %s %s" % (d.get("name"), d.get("version")))
print("# author: %s   license: %s" % (tax.get("author") or "unknown",
                                      tax.get("license") or "unstated"))
print()
print(d.get("content") or "")
'
    exit 0
fi

Q="$*"
fetch "${URL%/}/v1/tools/find?q=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$Q")&limit=${LIMIT}" \
    | python3 -c '
import json, sys
d = json.load(sys.stdin)
hits = d.get("results") or []
# "no skill for this" is a real answer, and an empty list states it weakly.
if not hits:
    print("no skill matched %r" % d.get("query", ""))
    raise SystemExit(0)
print("%d match(es) for %r\n" % (d["count"], d["query"]))
for h in hits:
    who = h.get("author") or h.get("source") or "unknown"
    print("%s  [%s]" % (h["name"], who))
    desc = (h.get("description") or "").strip()
    if desc:
        print("    %s" % desc[:160])
    print()
print("fetch one with:  skillshub-find.sh --get <name>")
'
