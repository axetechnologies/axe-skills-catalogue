"""Tests for hub.review and the `review` CLI group; temp databases only."""
from __future__ import annotations

import json
import sqlite3

import pytest

from hub import cli, review
from hub.store import Conflict, HubError, NotFound, Registry

QMETA = {"quarantined": True, "verified": False, "source": "user", "created_by": "abc123", "plan": "beta"}


@pytest.fixture
def dbs(tmp_path):
    write = Registry(tmp_path / "write.db")
    write.add_tenant("u-abc", "user")
    write.publish("u-abc", "hello", "1.0.0", "# hello\nbody", actor="u-abc", metadata=dict(QMETA))
    return tmp_path / "write.db", tmp_path / "cat.db"


def _run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def _promote_args(w, c, name="hello", version="1.0.0"):
    return ["review", "promote", "--db", str(w), "u-abc", name, version,
            "--to", str(c), "--tenant", "reviewed", "--reviewer", "james"]


def test_list_shows_quarantined_user_skills(dbs, capsys):
    w, _ = dbs
    code, out, _ = _run(capsys, "review", "list", "--db", str(w))
    assert code == 0
    assert "u-abc  hello  1.0.0  " in out
    assert str(len("# hello\nbody".encode())) in out


def test_list_skips_yanked_and_non_user(dbs, capsys):
    w, _ = dbs
    reg = Registry(w)
    reg.add_tenant("other", "x")
    reg.publish("other", "legacy", "1.0.0", "x", actor="a", metadata={"quarantined": True, "source": "smithery"})
    reg.publish("other", "clean", "1.0.0", "x", actor="a", metadata={"verified": True})
    reg.yank("u-abc", "hello", "1.0.0", actor="x")
    code, out, _ = _run(capsys, "review", "list", "--db", str(w))
    assert code == 0 and "(no quarantined user skills)" in out


def test_list_missing_db_errors_without_creating(tmp_path, capsys):
    p = tmp_path / "nope.db"
    code, _, err = _run(capsys, "review", "list", "--db", str(p))
    assert code == 1 and "not found" in err
    assert not p.exists()


def test_show_prints_metadata_and_content(dbs, capsys):
    w, _ = dbs
    code, out, _ = _run(capsys, "review", "show", "--db", str(w), "u-abc", "hello", "1.0.0")
    assert code == 0
    assert '"quarantined": true' in out and "# hello\nbody" in out


def test_show_unknown_is_error(dbs, capsys):
    w, _ = dbs
    code, _, err = _run(capsys, "review", "show", "--db", str(w), "u-abc", "hello", "9.9.9")
    assert code == 1 and "not found" in err


def test_promote_copies_and_marks_verified(dbs, capsys):
    w, c = dbs
    code, out, _ = _run(capsys, *_promote_args(w, c))
    assert code == 0 and "promoted: reviewed/hello@1.0.0" in out
    cat = Registry(c)
    s = cat.resolve("reviewed", "hello", "1.0.0")
    assert s.content == "# hello\nbody"
    assert s.metadata["verified"] is True and s.metadata["quarantined"] is False
    assert s.metadata["reviewed_by"] == "james"
    assert s.metadata["reviewed_at"]
    assert s.metadata["promoted_from"] == "u-abc/hello@1.0.0"
    assert any(a["action"] == "promote" for a in cat.audit("reviewed"))


def test_promote_leaves_source_row_intact(dbs, capsys):
    w, c = dbs
    before = Registry(w).resolve("u-abc", "hello", "1.0.0")
    _run(capsys, *_promote_args(w, c))
    after = Registry(w).resolve("u-abc", "hello", "1.0.0")
    assert after == before
    assert after.metadata["quarantined"] is True and after.metadata["verified"] is False
    assert after.yanked_at is None


def test_promote_creates_tenant_and_reuses_existing(dbs, capsys):
    w, c = dbs
    Registry(c).add_tenant("reviewed", "Reviewed")
    code, _, _ = _run(capsys, *_promote_args(w, c))
    assert code == 0
    assert [t["tenant_id"] for t in Registry(c).tenants()] == ["reviewed"]


def test_repromote_refused_and_target_unchanged(dbs, capsys):
    w, c = dbs
    assert _run(capsys, *_promote_args(w, c))[0] == 0
    first = Registry(c).resolve("reviewed", "hello", "1.0.0")
    code, _, err = _run(capsys, *_promote_args(w, c))
    assert code == 2 and "already" in err
    assert Registry(c).resolve("reviewed", "hello", "1.0.0") == first


def test_promote_refuses_not_quarantined(dbs, capsys):
    w, c = dbs
    Registry(w).publish("u-abc", "clean", "1.0.0", "x", actor="a", metadata={"verified": True, "quarantined": False})
    code, _, err = _run(capsys, *_promote_args(w, c, "clean"))
    assert code == 1 and "not quarantined" in err
    assert not c.exists() or Registry(c).tenants() == []


def test_promote_refuses_oversize(dbs, capsys):
    w, c = dbs
    Registry(w).publish("u-abc", "big", "1.0.0", "x" * (256 * 1024 + 1), actor="a", metadata=dict(QMETA))
    code, _, err = _run(capsys, *_promote_args(w, c, "big"))
    assert code == 1 and "limit" in err


def test_promote_accepts_exactly_the_cap(dbs, capsys):
    w, c = dbs
    Registry(w).publish("u-abc", "edge", "1.0.0", "x" * (256 * 1024), actor="a", metadata=dict(QMETA))
    assert _run(capsys, *_promote_args(w, c, "edge"))[0] == 0


def test_promote_refuses_yanked_and_unknown(dbs, capsys):
    w, c = dbs
    Registry(w).yank("u-abc", "hello", "1.0.0", actor="x")
    assert _run(capsys, *_promote_args(w, c))[0] == 1
    assert _run(capsys, *_promote_args(w, c, "ghost"))[0] == 1


def test_promote_refuses_same_database(dbs, capsys):
    w, _ = dbs
    code, _, err = _run(capsys, *_promote_args(w, w))
    assert code == 1 and "differ" in err


def test_promote_requires_reviewer(dbs):
    w, c = dbs
    with pytest.raises(HubError):
        review.promote(w, c, "u-abc", "hello", "1.0.0", to_tenant="reviewed", reviewer=" ")


def test_reject_yanks_in_write_db(dbs, capsys):
    w, _ = dbs
    code, out, _ = _run(capsys, "review", "reject", "--db", str(w), "u-abc", "hello", "1.0.0", "--reviewer", "james")
    assert code == 0 and "rejected" in out
    s = Registry(w).resolve("u-abc", "hello", "1.0.0")
    assert s.yanked
    assert any(a["action"] == "yank" and a["actor"] == "james" for a in Registry(w).audit("u-abc"))
    assert _run(capsys, "review", "list", "--db", str(w))[1].startswith("(no quarantined")


def test_reject_twice_and_non_quarantined_refused(dbs, capsys):
    w, _ = dbs
    args = ["review", "reject", "--db", str(w), "u-abc", "hello", "1.0.0", "--reviewer", "james"]
    assert _run(capsys, *args)[0] == 0
    assert _run(capsys, *args)[0] == 1
    Registry(w).publish("u-abc", "clean", "1.0.0", "x", actor="a", metadata={"verified": True})
    code, _, err = _run(capsys, "review", "reject", "--db", str(w), "u-abc", "clean", "1.0.0", "--reviewer", "j")
    assert code == 1 and "not quarantined" in err
    assert not Registry(w).resolve("u-abc", "clean", "1.0.0").yanked
