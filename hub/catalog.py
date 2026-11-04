"""Read path for a database imported from a rich-build snapshot (see hub/schema_serve.sql).

The plain registry path loads every row into Python per request; at 65k rows that is the whole cost of a
request. Here a list page is a range scan on skill_cards.seq, a search is one LIKE with LIMIT, a detail is
one primary-key read, and find ranks against an in-memory inverted index built once at start-up. Rows are
assembled as JSON text from the stored columns, never parsed and re-dumped, so what is served is what was
stored, byte for byte.

Nothing here writes: connections are opened read-only.
"""
from __future__ import annotations

import collections
import json
import math
import sqlite3
import threading
from pathlib import Path
from typing import Any

from hub.discover import (
    W_CATEGORY, W_NAME_EXACT, W_NAME_TOKEN, W_SOURCE, W_TAG, W_DESC, BONUS_USE,
    BONUS_VERIFIED, tokens, _TOKEN,
)

HOST_TOKEN = "@@HOST@@"
_COLS = ("s.tenant_id, s.name, s.version, s.format, s.checksum, s.metadata, s.created_by, "
         "s.created_at, s.yanked_at")
_W_NAME_SUBSTRING = W_NAME_TOKEN * 0.4


def available(db_path: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_cards'").fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _row_json(r: tuple, card: str, content: str | None = None) -> str:
    d = json.dumps
    head = (f'{{"tenant_id": {d(r[0])}, "name": {d(r[1])}, "version": {d(r[2])}, "format": {d(r[3])}, '
            f'"checksum": {d(r[4])}, "metadata": {r[5]}, "created_by": {d(r[6])}, '
            f'"created_at": {d(r[7])}, "yanked_at": {d(r[8])}')
    if content is not None:
        head += f', "content": {d(content)}'
    return head + f', "card": {card}}}'


class _FindIndex:
    """Everything find needs to score a row, held as inverted postings per field.

    Scoring keeps the repo's field weights (name, tag, description, category, source). Two things differ
    from hub.discover.rank, both fitted to the rich build's recorded answers: a query token is weighted by
    its rarity in this catalogue, and coverage multiplies the total. A one-word query scores exactly as
    before (weights 120/30/12/4/2/1 plus the verified and use bonuses).
    """

    def __init__(self, rows: list[dict]) -> None:
        self.n = len(rows)
        self.names = [r["name"] for r in rows]
        self.names_l = [r["name"].lower() for r in rows]
        self.labels_l = [(r["title"] or "").lower() for r in rows]
        self.verified = [r["verified"] for r in rows]
        self.bonus = [(BONUS_VERIFIED if r["verified"] else 0.0) + (BONUS_USE if r["use_count"] else 0.0)
                      for r in rows]
        self.category = [r["category"] for r in rows]
        self.exact: dict[str, list[int]] = collections.defaultdict(list)
        self.nt: dict[str, list[int]] = collections.defaultdict(list)
        self.tg: dict[str, list[int]] = collections.defaultdict(list)
        self.ds: dict[str, list[int]] = collections.defaultdict(list)
        self.ct: dict[str, list[int]] = collections.defaultdict(list)
        self.sr: dict[str, list[int]] = collections.defaultdict(list)
        self.df: collections.Counter = collections.Counter()
        for i, r in enumerate(rows):
            nl, ll = self.names_l[i], self.labels_l[i]
            self.exact[nl].append(i)
            if ll != nl:
                self.exact[ll].append(i)
            name_t = set(tokens(r["name"])) | set(tokens(r["title"] or ""))
            tag_t: set = set()
            for t in r["tags"]:
                tag_t |= set(tokens(t))
            desc_t = set(tokens(r["description"]))
            cat_t = set(tokens(r["category"])) | set(tokens(r["category_label"]))
            src_t = set(tokens(r["source"]))
            for field, toks in ((self.nt, name_t), (self.tg, tag_t), (self.ds, desc_t),
                                (self.ct, cat_t), (self.sr, src_t)):
                for t in toks:
                    field[t].append(i)
            self.df.update(name_t | tag_t | desc_t | cat_t | src_t)

    def _hits(self, t: str) -> dict[int, float]:
        h: dict[int, float] = {}
        for i in range(self.n):
            if t in self.names_l[i] or t in self.labels_l[i]:
                h[i] = _W_NAME_SUBSTRING
        for i in self.nt.get(t, ()):
            h[i] = W_NAME_TOKEN
        for i in self.exact.get(t, ()):
            h[i] = W_NAME_EXACT
        for postings, w in ((self.tg, W_TAG), (self.ds, W_DESC), (self.ct, W_CATEGORY), (self.sr, W_SOURCE)):
            for i in postings.get(t, ()):
                h[i] = h.get(i, 0.0) + w
        return h

    def rank(self, qt: list[str], limit: int, category: str | None, verified_only: bool) -> list[tuple[float, int, int]]:
        n = len(qt)
        idf = [math.log((self.n + 1) / (self.df.get(t, 0) + 1)) for t in qt]
        mean = sum(idf) / n
        weights = [(x / mean) ** 3 if mean > 0 else 1.0 for x in idf]
        total: dict[int, float] = collections.defaultdict(float)
        matched: dict[int, int] = collections.defaultdict(int)
        for t, w in zip(qt, weights):
            for i, h in self._hits(t).items():
                total[i] += h * w
                matched[i] += 1
        scored = []
        for i, s in total.items():
            if category and self.category[i] != category:
                continue
            if verified_only and not self.verified[i]:
                continue
            scored.append((round(s * matched[i] / n + self.bonus[i], 2), matched[i], i))
        scored.sort(key=lambda x: (-x[0], self.names[x[2]]))
        return scored[:limit]


class Catalog:
    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._local = threading.local()
        self._index: dict[str, _FindIndex] = {}
        self._index_lock = threading.Lock()
        self._totals: dict[str, int] = {}
        self._texts: dict[str, list[str]] = {}

    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
            con.execute("PRAGMA query_only = ON")
            con.execute("PRAGMA cache_size = -65536")
            self._local.con = con
        return con

    def total(self, tenant: str) -> int:
        if tenant not in self._totals:
            self._totals[tenant] = self._con().execute(
                "SELECT COUNT(*) FROM skill_cards WHERE tenant_id = ?", (tenant,)).fetchone()[0]
        return self._totals[tenant]

    def list_page(self, tenant: str, limit: int, offset: int) -> list[str]:
        if limit <= 0:
            return []
        rows = self._con().execute(
            f"SELECT {_COLS}, c.card FROM skill_cards c JOIN skills s "
            "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version "
            "WHERE c.tenant_id = ? AND c.seq >= ? AND c.seq < ? AND s.yanked_at IS NULL ORDER BY c.seq",
            (tenant, offset, offset + limit)).fetchall()
        return [_row_json(r[:9], r[9]) for r in rows]

    def _search_texts(self, tenant: str) -> list[str]:
        texts = self._texts.get(tenant)
        if texts is None:
            with self._index_lock:
                texts = self._texts.get(tenant)
                if texts is None:
                    # name and metadata, lower-cased, in seq (= name) order: a substring test over this
                    # list is the same match as `name LIKE %q% OR metadata LIKE %q%`, in C rather than
                    # in SQLite's row-by-row LIKE, which is what took ~120 ms over 65k rows.
                    texts = self._texts[tenant] = [
                        (n + "\x00" + m).lower() for n, m in self._con().execute(
                            "SELECT s.name, s.metadata FROM skill_cards c JOIN skills s "
                            "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version "
                            "WHERE c.tenant_id = ? ORDER BY c.seq", (tenant,))]
        return texts

    def search(self, tenant: str, q: str, limit: int, offset: int) -> list[str]:
        if limit <= 0:
            return []
        needle = q.lower()
        texts = self._search_texts(tenant)
        hits = [i for i, t in enumerate(texts) if needle in t] if needle else range(len(texts))
        page = list(hits[offset:offset + limit])
        if not page:
            return []
        marks = ",".join("?" * len(page))
        rows = self._con().execute(
            f"SELECT {_COLS}, c.card FROM skill_cards c JOIN skills s "
            "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version "
            f"WHERE c.tenant_id = ? AND c.seq IN ({marks}) AND s.yanked_at IS NULL ORDER BY c.seq",
            [tenant] + page).fetchall()
        return [_row_json(r[:9], r[9]) for r in rows]

    def get(self, tenant: str, name: str, version: str | None) -> str | None:
        sql = (f"SELECT {_COLS}, s.content, c.card FROM skills s JOIN skill_cards c "
               "ON s.tenant_id = c.tenant_id AND s.name = c.name AND s.version = c.version "
               "WHERE s.tenant_id = ? AND s.name = ?")
        args: list[Any] = [tenant, name]
        if version is not None:
            sql += " AND s.version = ?"
            args.append(version)
        r = self._con().execute(sql, args).fetchone()
        return None if r is None else _row_json(r[:9], r[10], content=r[9])

    def versions(self, tenant: str, name: str) -> list[str] | None:
        rows = self._con().execute(
            "SELECT version FROM skill_versions WHERE tenant_id = ? AND name = ? ORDER BY ord",
            (tenant, name)).fetchall()
        return [r[0] for r in rows] if rows else None

    def categories(self, tenant: str) -> list[dict]:
        rows = self._con().execute(
            "SELECT category, label, count FROM categories WHERE tenant_id = ? ORDER BY ord",
            (tenant,)).fetchall()
        return [{"category": c, "label": lbl, "count": n,
                 "find": f"/v1/tools/find?category={c}&q=<task>"} for c, lbl, n in rows]

    def _find_index(self, tenant: str) -> _FindIndex:
        idx = self._index.get(tenant)
        if idx is None:
            with self._index_lock:
                idx = self._index.get(tenant)
                if idx is None:
                    idx = self._index[tenant] = self._build_index(tenant)
        return idx

    def warm(self, tenant: str) -> None:
        self._find_index(tenant)
        self._search_texts(tenant)

    def _build_index(self, tenant: str) -> _FindIndex:
        rows = []
        cur = self._con().execute(
            "SELECT card FROM skill_cards WHERE tenant_id = ? ORDER BY seq", (tenant,))
        for (card_json,) in cur:
            c = json.loads(card_json)
            rows.append({
                "name": None, "title": c.get("title", ""), "description": c.get("description", ""),
                "tags": c.get("tags") or [], "category": c.get("category") or "other",
                "category_label": c.get("category_label") or "Other", "source": c.get("source", ""),
                "verified": bool(c.get("verified")), "use_count": c.get("use_count") or 0,
            })
        for r, (name,) in zip(rows, self._con().execute(
                "SELECT name FROM skill_cards WHERE tenant_id = ? ORDER BY seq", (tenant,))):
            r["name"] = name
        return _FindIndex(rows)

    def find(self, tenant: str, query: str, limit: int, category: str | None,
             verified_only: bool) -> dict:
        qt = tokens(query)
        literal = None
        if not qt:
            literal = _TOKEN.findall(query.lower())
            qt = list(literal)
        out: dict[str, Any] = {"query": query, "count": 0, "results": [], "limit": limit}
        if literal:
            out["searched_literally"] = literal
            out["note"] = ("every word in this query is a common filler word in the catalogue, so it was "
                           "matched literally instead of being dropped")
        if not qt:
            return out
        idx = self._find_index(tenant)
        top = idx.rank(qt, limit, category, verified_only)
        by_name: dict[str, dict] = {}
        names = [idx.names[i] for _, _, i in top]
        if names:
            marks = ",".join("?" * len(names))
            for name, version, card in self._con().execute(
                    f"SELECT name, version, card FROM skill_cards WHERE tenant_id = ? AND name IN ({marks})",
                    [tenant] + names):
                by_name[name] = {"version": version, "card": json.loads(card)}
        results = []
        for score, matched, i in top:
            name = idx.names[i]
            v = by_name[name]
            c = v["card"]
            results.append({
                "name": name,
                "title": c.get("title", name),
                "description": c.get("description", ""),
                "category": c.get("category") or "other",
                "category_label": c.get("category_label") or "Other",
                "category_source": c.get("category_source") or "upstream",
                "tags": (c.get("tags") or [])[:8],
                "source": c.get("source", ""),
                "author": c.get("author", ""),
                "license": c.get("license", ""),
                "verified": bool(c.get("verified")),
                "use_count": c.get("use_count") or 0,
                "version": v["version"],
                "homepage": c.get("homepage", ""),
                "score": score,
                "matched_terms": matched,
                "install": c.get("install", ""),
            })
        out["count"] = len(results)
        out["results"] = results
        return out
