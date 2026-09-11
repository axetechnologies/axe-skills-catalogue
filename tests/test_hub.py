"""Tests for hub.store and hub.backends."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hub.store import Conflict, HubError, NotFound, Registry
from hub.backends import LegacySource, RegistrySource, compare, source_from_env


@pytest.fixture
def reg(tmp_path):
    r = Registry(tmp_path / "hub.db")
    r.add_tenant("acme", "Acme Corp")
    return r


@pytest.fixture
def two_tenant_reg(tmp_path):
    r = Registry(tmp_path / "hub.db")
    r.add_tenant("acme", "Acme Corp")
    r.add_tenant("beta", "Beta Inc")
    return r


def test_cross_tenant_list_isolation(two_tenant_reg):
    r = two_tenant_reg
    r.publish("acme", "foo", "1.0.0", "content", actor="alice")
    assert r.list("beta") == []


def test_cross_tenant_search_isolation(two_tenant_reg):
    r = two_tenant_reg
    r.publish("acme", "foo", "1.0.0", "content", actor="alice")
    assert r.search("beta", "foo") == []


def test_cross_tenant_resolve_raises(two_tenant_reg):
    r = two_tenant_reg
    r.publish("acme", "foo", "1.0.0", "content", actor="alice")
    with pytest.raises(NotFound):
        r.resolve("beta", "foo")


def test_republish_same_version_raises_conflict(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    with pytest.raises(Conflict):
        reg.publish("acme", "foo", "1.0.0", "other", actor="alice")


def test_publish_new_version_succeeds(reg):
    reg.publish("acme", "foo", "1.0.0", "v1", actor="alice")
    s = reg.publish("acme", "foo", "2.0.0", "v2", actor="alice")
    assert s.version == "2.0.0"


def test_numeric_version_sort(reg):
    reg.publish("acme", "foo", "1.9.0", "old", actor="alice")
    reg.publish("acme", "foo", "1.10.0", "new", actor="alice")
    s = reg.resolve("acme", "foo")
    assert s.version == "1.10.0"


def test_yank_hides_from_resolve(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    with pytest.raises(NotFound):
        reg.resolve("acme", "foo")


def test_yank_hides_from_list(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    assert reg.list("acme") == []


def test_yank_row_survives_include_yanked(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    rows = reg.list("acme", include_yanked=True)
    assert len(rows) == 1
    assert rows[0]["yanked_at"] is not None


def test_yank_appears_in_audit(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    entries = reg.audit("acme")
    actions = [e["action"] for e in entries]
    assert "yank" in actions


def test_fetch_writes_audit_row(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    assert [e["action"] for e in reg.audit("acme")] == ["publish"]
    reg.fetch("acme", "foo", actor="bob")
    entries = reg.audit("acme")

    assert [(e["actor"], e["action"]) for e in entries] == [
        ("alice", "publish"),
        ("bob", "fetch"),
    ]


def test_resolve_does_not_write_audit(reg):
    """resolve is the internal read; fetch is the client-facing one.

    Keeping them distinct is what stops the log filling with the hub's own
    lookups until nobody reads it.
    """
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    before = len(reg.audit("acme"))
    reg.resolve("acme", "foo")

    assert len(reg.audit("acme")) == before


def test_list_never_returns_content(reg):
    reg.publish("acme", "foo", "1.0.0", "secret content", actor="alice")
    for row in reg.list("acme"):
        assert "content" not in row


def test_publish_unknown_tenant_raises(tmp_path):
    r = Registry(tmp_path / "hub.db")
    with pytest.raises(NotFound):
        r.publish("ghost", "foo", "1.0.0", "x", actor="alice")


def test_yank_already_yanked_raises(reg):
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    with pytest.raises(NotFound):
        reg.yank("acme", "foo", "1.0.0", actor="alice")


def test_invalid_format_raises(reg):
    with pytest.raises(HubError):
        reg.publish("acme", "foo", "1.0.0", "content", actor="alice", format="xml")


def test_checksum_is_sha256(reg):
    import hashlib
    s = reg.publish("acme", "foo", "1.0.0", "hello", actor="alice")
    assert s.checksum == hashlib.sha256(b"hello").hexdigest()


def test_legacy_source_reads_files(tmp_path):
    skill_file = tmp_path / "skill_greet.py"
    skill_file.write_text('"""Greet the user."""\n\ndef run(): pass\n')
    ls = LegacySource(tmp_path)
    skills = ls.list("any-tenant")
    assert len(skills) == 1
    assert skills[0]["name"] == "greet"
    assert skills[0]["version"] == "0"
    assert skills[0]["created_by"] == "unknown"


def test_legacy_source_same_results_for_different_tenants(tmp_path):
    (tmp_path / "skill_foo.py").write_text('"""foo skill."""\n')
    ls = LegacySource(tmp_path)
    r1 = ls.list("tenant-a")
    r2 = ls.list("tenant-b")
    # LegacySource leaks across tenants by design; this asserts the documented fact.
    assert r1 == r2


def test_source_from_env_registry(tmp_path):
    db = str(tmp_path / "h.db")
    src = source_from_env({"AXE_HUB_BACKEND": "registry", "AXE_HUB_DB": db})
    assert src.name == "registry"


def test_source_from_env_legacy(tmp_path):
    src = source_from_env({"AXE_HUB_BACKEND": "legacy", "AXE_HUB_LEGACY_ROOT": str(tmp_path)})
    assert src.name == "legacy"


def test_source_from_env_default_is_registry(tmp_path):
    src = source_from_env({"AXE_HUB_DB": str(tmp_path / "h.db")})
    assert src.name == "registry"


def test_source_from_env_unknown_raises():
    with pytest.raises(HubError, match="legacy.*registry"):
        source_from_env({"AXE_HUB_BACKEND": "postgres"})


def test_compare_only_legacy(tmp_path):
    (tmp_path / "skill_alpha.py").write_text('"""alpha."""\n')
    db_path = tmp_path / "h.db"
    reg = Registry(db_path)
    reg.add_tenant("t", "T")
    ls = LegacySource(tmp_path)
    rs = RegistrySource(reg)
    result = compare(ls, rs, "t")
    assert "alpha" in result["only_legacy"]
    assert result["only_registry"] == []
    assert result["both"] == []


def test_compare_only_registry(tmp_path):
    db_path = tmp_path / "h.db"
    reg = Registry(db_path)
    reg.add_tenant("t", "T")
    reg.publish("t", "bravo", "1.0.0", "content", actor="sys")
    ls = LegacySource(tmp_path)
    rs = RegistrySource(reg)
    result = compare(ls, rs, "t")
    assert "bravo" in result["only_registry"]
    assert result["only_legacy"] == []


def test_skill_record_excludes_content(reg):
    s = reg.publish("acme", "foo", "1.0.0", "body text", actor="alice")
    r = s.record()
    assert "content" not in r
    assert r["name"] == "foo"


def test_skill_yanked_property(reg):
    s = reg.publish("acme", "foo", "1.0.0", "x", actor="alice")
    assert not s.yanked
    reg.yank("acme", "foo", "1.0.0", actor="alice")
    s2 = reg.resolve("acme", "foo", "1.0.0")
    assert s2.yanked


def test_publish_is_audited(reg):
    """The event a compliance review asks about first."""
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    entry = reg.audit("acme")[0]

    assert (entry["action"], entry["actor"], entry["version"]) == (
        "publish",
        "alice",
        "1.0.0",
    )


def test_audit_survives_a_yank(reg):
    """A yanked version leaves the skills row reachable only via include_yanked,
    but the question "who published this" must stay answerable regardless."""
    reg.publish("acme", "foo", "1.0.0", "content", actor="alice")
    reg.yank("acme", "foo", "1.0.0", actor="bob")

    assert [(e["actor"], e["action"]) for e in reg.audit("acme")] == [
        ("alice", "publish"),
        ("bob", "yank"),
    ]
