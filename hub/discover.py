"""Task-oriented discovery over the catalogue: rank tools, project them small.

Two jobs live here, and they live together because they are the same job seen
from two sides. `rank()` decides which tools answer a question. `compact()`
decides how little we can say about a tool and still have the answer be useful.
An agent choosing a tool and a web page rendering a picker want the same thing:
the few rows that matter, described in the few fields that matter.

Why this module exists rather than another LIKE clause in store.py:

  The catalogue keeps its prose in the `content` column, not in `metadata`.
  Registry.search() greps name and metadata only, so it could not see a single
  description -- 100% of rows carry one. Searching "kubernetes" matched 55 rows
  when 119 were relevant; 54% of the catalogue's own answer was invisible.

  It also ordered by name, so the best match for "docker" was whatever matched
  alphabetically first. Alphabetical order is not a ranking, and a caller that
  takes the top 5 of an alphabetical list is reading noise.

Both consumers -- the HTTP API and the portal -- import from here. That is the
point: a ranking that is only defined where it is measured is not the ranking
that ships.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Iterable

# Field weights. A name match is the strongest signal a catalogue has: an author
# who called their tool `kubernetes-deploy` was answering the query directly.
# Tags are curated, so they outrank prose. Category is coarse and matches too
# many rows to carry much, but it breaks ties usefully.
W_NAME_EXACT = 120.0
W_NAME_TOKEN = 30.0
W_TAG = 12.0
W_DESC = 4.0
W_CATEGORY = 2.0
W_SOURCE = 1.0

# Small, deliberate nudges applied after text scoring, never instead of it. A
# verified tool and a popular one are better bets among equals -- they are not a
# reason to return an irrelevant row.
BONUS_VERIFIED = 3.0
BONUS_USE = 2.0

# Words that match a large fraction of a software catalogue carry no signal but
# do carry cost: dropping them turns "a tool for managing docker containers"
# into "managing docker containers" before anything is scored.
STOP = frozenset("""
a an and are as at be by can do does for from get give has have how i in into is
it me my need of on or please that the their this to use using want was what
when where which who will with you your tool tools skill skills agent agents
""".split())

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric runs, stopwords dropped, order preserved."""
    return [t for t in _TOKEN.findall((text or "").lower())
            if t not in STOP and len(t) > 1]


def _doc(row: dict) -> dict:
    """Flatten one catalogue row into the fields discovery actually scores.

    The description lives inside the `content` JSON document; the category and
    tags live inside `metadata.taxonomy`. Callers should never need to know
    that, which is why every read of those shapes happens here.
    """
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    tax = meta.get("taxonomy") or {}

    # taxonomy first, content blob second. A mirrored `catalog` row keeps its
    # description inside the JSON document; a first-party `skillmd` row is
    # markdown and JSON-parsing it yields nothing, so reading only the blob
    # ranked our own skills on their name alone and served them with an empty
    # description -- the one field a picker needs. The blob stays as the
    # fallback that the ~111k mirrored rows depend on.
    desc = (tax.get("description") or "").strip()
    label = ""
    content = row.get("content")
    if content:
        try:
            doc = json.loads(content) if isinstance(content, str) else content
        except ValueError:
            doc = {}
        if isinstance(doc, dict):
            desc = desc or (doc.get("description") or "").strip()
            label = (doc.get("name") or "").strip()

    tags = tax.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    return {
        "name": row.get("name") or "",
        "label": label,
        "description": desc,
        "tags": [str(t) for t in tags],
        "category": tax.get("category") or "",
        "category_label": tax.get("category_label") or "",
        "source": meta.get("source") or "",
        "author": tax.get("author") or "",
        "license": tax.get("license") or "",
        "homepage": meta.get("homepage") or "",
        "verified": bool(meta.get("verified")),
        "use_count": int(meta.get("use_count") or 0),
        "version": row.get("version") or "",
    }


def score(doc: dict, qtokens: Iterable[str]) -> tuple[float, int]:
    """Relevance of one flattened doc, and how many query tokens it matched.

    Returns the match count alongside the score so a caller can require that
    every token appear. Score alone cannot express that: a single heavy name hit
    would otherwise outrank a row that answered the whole question.
    """
    qt = list(qtokens)
    if not qt:
        return 0.0, 0

    name = doc["name"].lower()
    label = doc["label"].lower()
    name_tokens = set(tokens(doc["name"])) | set(tokens(doc["label"]))
    tag_tokens = set()
    for t in doc["tags"]:
        tag_tokens |= set(tokens(t))
    desc_tokens = set(tokens(doc["description"]))
    cat_tokens = set(tokens(doc["category"])) | set(tokens(doc["category_label"]))
    src_tokens = set(tokens(doc["source"]))

    total = 0.0
    matched = 0
    for t in qt:
        hit = 0.0
        # An exact whole-name (or display-name) equality is a different event
        # from the name merely containing the token, and worth saying so.
        if t == name or t == label:
            hit += W_NAME_EXACT
        elif t in name_tokens:
            hit += W_NAME_TOKEN
        elif t in name or t in label:
            # Substring inside a longer word: real, but weaker than a token.
            hit += W_NAME_TOKEN * 0.4
        if t in tag_tokens:
            hit += W_TAG
        if t in desc_tokens:
            hit += W_DESC
        if t in cat_tokens:
            hit += W_CATEGORY
        if t in src_tokens:
            hit += W_SOURCE
        if hit:
            matched += 1
            total += hit

    if not total:
        return 0.0, 0

    # Coverage matters more than any single strong field: a row that answers
    # two of two tokens beats one that answers one of two twice as loudly.
    total *= matched / len(qt)

    if doc["verified"]:
        total += BONUS_VERIFIED
    if doc["use_count"]:
        total += BONUS_USE
    return total, matched


def compact(doc: dict) -> dict:
    """The smallest description of a tool that is still enough to choose it.

    A full catalogue record carries a checksum, a federation timestamp and a
    quarantine flag. None of that helps a model or a picker decide, and 200 of
    them is a 111 KB response. This is the shape that crosses the wire.
    """
    return {
        "name": doc["name"],
        "title": doc["label"] or doc["name"],
        "description": doc["description"],
        "category": doc["category"],
        "category_label": doc["category_label"],
        "tags": doc["tags"][:8],
        "source": doc["source"],
        # Who wrote it and on what terms. A catalogue meant to be a community
        # resource that cannot say either is not usable as one, and the tenant
        # split is what makes the answer meaningful rather than uniform.
        "author": doc["author"],
        "license": doc["license"],
        "verified": doc["verified"],
        "use_count": doc["use_count"],
        "version": doc["version"],
        "homepage": doc["homepage"],
    }


def _candidate_sql(qtokens: list[str]) -> tuple[str, list[Any]]:
    """Prefilter in SQL so scoring never walks the whole catalogue.

    One OR-group per token across the three columns that hold text. This is
    recall-only: it decides what MIGHT match, and rank() decides what does.
    """
    clauses, params = [], []
    for t in qtokens:
        like = f"%{t}%"
        clauses.append("(s.name LIKE ? OR s.content LIKE ? OR s.metadata LIKE ?)")
        params += [like, like, like]
    return " OR ".join(clauses), params


def rank(db_path, tenant_id: str, query: str, limit: int = 20,
         category: str | None = None, verified_only: bool = False,
         require_all: bool = True) -> list[dict]:
    """Best `limit` tools for a natural-language task or keyword query.

    `require_all` keeps precision high by dropping rows that miss a query token,
    then relaxes to any-token if that leaves nothing -- a strict AND over a
    long question would otherwise return an empty list for a query the
    catalogue can partly answer, which is worse than a ranked partial answer.
    """
    qt = tokens(query)
    if not qt:
        return []

    where, params = _candidate_sql(qt)
    sql = ("SELECT s.name, s.version, s.content, s.metadata FROM skills s "
           "JOIN (SELECT name, MAX(rowid) r FROM skills "
           "      WHERE tenant_id = ? AND yanked_at IS NULL GROUP BY name) l "
           "  ON s.rowid = l.r "
           f"WHERE ({where})")
    args = [tenant_id] + params

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, args).fetchall()
    finally:
        con.close()

    scored = []
    for r in rows:
        doc = _doc(dict(r))
        if category and doc["category"] != category:
            continue
        if verified_only and not doc["verified"]:
            continue
        s, matched = score(doc, qt)
        if not s:
            continue
        scored.append((s, matched, doc))

    # Coverage first, then score. Ranking by term coverage rather than FILTERING
    # on it keeps the precision of an AND without its cliff: "send a slack
    # message" has exactly one row matching all three terms, and discarding the
    # partial matches turned a good answer list into a list of one. Now the
    # full matches lead and the near-misses fill the page below them.
    # Name is the final tie-break purely so the order is stable across calls;
    # two rows with an identical score are genuinely indistinguishable here.
    if require_all and len(qt) > 1:
        scored.sort(key=lambda x: (-x[1], -x[0], x[2]["name"]))
    else:
        scored.sort(key=lambda x: (-x[0], x[2]["name"]))

    out = []
    for s, matched, doc in scored[:limit]:
        item = compact(doc)
        item["score"] = round(s, 2)
        item["matched_terms"] = matched
        out.append(item)
    return out
