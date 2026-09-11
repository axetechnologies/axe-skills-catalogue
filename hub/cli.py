"""Invariant: every write path checks tenant existence before mutating; exit codes are 0/1/2 only."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from hub.ingest import _bump_patch, parse_skillmd
from hub.store import Conflict, NotFound, Registry


def _db_path(args):
    raw = getattr(args, "db", None) or os.environ.get("AXE_HUB_DB") or ""
    if raw:
        return Path(raw)
    return Path.home() / ".axe" / "hub" / "hub.db"


def _registry(args):
    p = _db_path(args)
    p.parent.mkdir(parents=True, exist_ok=True)
    return Registry(p)


def _checksum(content):
    return hashlib.sha256(content.encode()).hexdigest()


def _resolve_skill_from_path(path, name_override, version_override, actor):
    if path.is_dir():
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            print(f"error: {path} is a directory but contains no SKILL.md", file=sys.stderr)
            sys.exit(1)
        content = skill_md.read_text(encoding="utf-8")
        meta, _ = parse_skillmd(content)
        evals_path = path / "evals.json"
        if evals_path.exists():
            import json as _json
            try:
                meta["evals"] = _json.loads(evals_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        name = name_override or meta.get("name") or path.name
        fmt = "skillmd"
    elif path.suffix == ".py":
        content = path.read_text(encoding="utf-8")
        name = name_override or path.stem
        meta = {"name": name}
        fmt = "python"
    elif path.suffix == ".md":
        content = path.read_text(encoding="utf-8")
        meta, _ = parse_skillmd(content)
        name = name_override or meta.get("name") or path.stem
        fmt = "skillmd"
    else:
        print(f"error: {path} must be a directory, .md, or .py file", file=sys.stderr)
        sys.exit(1)
    return name, version_override, fmt, content, meta


def _cmd_add(args):
    path = Path(args.path)
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 1
    reg = _registry(args)
    try:
        name, version_hint, fmt, content, meta = _resolve_skill_from_path(
            path, args.name, args.version, args.actor
        )
    except SystemExit as e:
        return e.code
    new_cs = _checksum(content)
    existing_versions = reg.versions(args.tenant, name)
    if existing_versions:
        latest = existing_versions[-1]
        try:
            existing_skill = reg.resolve(args.tenant, name, latest)
            if existing_skill.checksum == new_cs:
                print(f"unchanged: {name}@{latest}")
                return 0
        except NotFound:
            pass
        version = version_hint or _bump_patch(latest)
    else:
        version = version_hint or "1.0.0"
    try:
        reg.publish(
            args.tenant, name, version, content,
            actor=args.actor, format=fmt, metadata=meta,
        )
    except NotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Conflict as e:
        print(f"conflict: {e}", file=sys.stderr)
        return 2
    action = "updated" if existing_versions else "added"
    print(f"{action}: {name}@{version}")
    return 0


_SCAFFOLD = """---
name: {name}
description: |
  Describe what this skill does.
---

# {name}

Write skill instructions here.
"""


def _cmd_new(args):
    name = args.name
    content = _SCAFFOLD.format(name=name)
    meta, _ = parse_skillmd(content)
    reg = _registry(args)
    existing = reg.versions(args.tenant, name)
    version = "1.0.0"
    if existing:
        latest = existing[-1]
        try:
            ex = reg.resolve(args.tenant, name, latest)
            if ex.checksum == _checksum(content):
                print(f"unchanged: {name}@{latest}")
                return 0
        except NotFound:
            pass
        version = _bump_patch(latest)
    try:
        reg.publish(
            args.tenant, name, version, content,
            actor=args.actor, format="skillmd", metadata=meta,
        )
    except NotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Conflict as e:
        print(f"conflict: {e}", file=sys.stderr)
        return 2
    action = "updated" if existing else "added"
    print(f"{action}: {name}@{version} (scaffold)")
    return 0


def _cmd_list(args):
    reg = _registry(args)
    skills = reg.list(args.tenant)
    if not skills:
        print("(no skills)")
    for s in skills:
        print(f"{s['name']}  {s['version']}")
    return 0


def _cmd_versions(args):
    reg = _registry(args)
    versions = reg.versions(args.tenant, args.skill_name)
    if not versions:
        print(f"no versions for {args.skill_name!r}")
        return 1
    for v in versions:
        print(v)
    return 0


def _cmd_yank(args):
    reg = _registry(args)
    try:
        reg.yank(args.tenant, args.skill_name, args.version, actor=args.actor)
    except NotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"yanked: {args.skill_name}@{args.version}")
    return 0


def _cmd_install(args):
    from hub.install import install_skill
    dest = Path(args.dest) if args.dest else None
    return install_skill(
        tenant=args.tenant,
        name=args.name,
        version=getattr(args, "version", None),
        dest=dest,
        actor=args.actor,
        db_path=_db_path(args),
        force=getattr(args, "force", False),
    )


def _cmd_installed(args):
    from hub.install import list_installed
    dest = Path(args.dest) if args.dest else None
    return list_installed(dest=dest, db_path=_db_path(args))


def build_parser():
    p = argparse.ArgumentParser(prog="hub", description="AXE Skills Hub CLI")
    p.add_argument("--db", metavar="PATH", help="Hub database path")
    sub = p.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Publish a skill from disk")
    add_p.add_argument("path")
    add_p.add_argument("--tenant", required=True)
    add_p.add_argument("--name")
    add_p.add_argument("--version")
    add_p.add_argument("--actor", default="cli")
    add_p.add_argument("--message")

    new_p = sub.add_parser("new", help="Scaffold and publish a minimal skill")
    new_p.add_argument("name")
    new_p.add_argument("--tenant", required=True)
    new_p.add_argument("--actor", default="cli")

    list_p = sub.add_parser("list", help="List skills in a tenant")
    list_p.add_argument("--tenant", required=True)

    ver_p = sub.add_parser("versions", help="List versions of a skill")
    ver_p.add_argument("skill_name")
    ver_p.add_argument("--tenant", required=True)

    yank_p = sub.add_parser("yank", help="Yank a specific version")
    yank_p.add_argument("skill_name")
    yank_p.add_argument("version")
    yank_p.add_argument("--tenant", required=True)
    yank_p.add_argument("--actor", default="cli")

    inst_p = sub.add_parser("install", help="Install a skill from the hub")
    inst_p.add_argument("name")
    inst_p.add_argument("--tenant", required=True)
    inst_p.add_argument("--version")
    inst_p.add_argument("--dest")
    inst_p.add_argument("--actor", default="cli")
    inst_p.add_argument("--force", action="store_true")

    ins2_p = sub.add_parser("installed", help="List installed skills and flag drift")
    ins2_p.add_argument("--dest")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "add": _cmd_add,
        "new": _cmd_new,
        "list": _cmd_list,
        "versions": _cmd_versions,
        "yank": _cmd_yank,
        "install": _cmd_install,
        "installed": _cmd_installed,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
