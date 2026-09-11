from __future__ import annotations
import hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from hub.store import NotFound, Registry

_DEFAULT_DEST = Path.home() / ".claude" / "skills"

def _checksum(content):
    return hashlib.sha256(content.encode()).hexdigest()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _dest_dir(dest):
    if dest:
        return dest
    raw = os.environ.get("AXE_SKILLS_DIR") or ""
    if raw:
        return Path(raw)
    return _DEFAULT_DEST

def install_skill(*, tenant, name, version, dest, actor, db_path, force=False):
    reg = Registry(db_path)
    try:
        skill = reg.fetch(tenant, name, version, actor=actor)
    except NotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if skill.yanked:
        print(f"error: {name}@{skill.version} is yanked and cannot be installed", file=sys.stderr)
        return 1
    base = _dest_dir(dest)
    skill_dir = base / name
    skill_file = skill_dir / "SKILL.md"
    prov_file = skill_dir / ".axe-provenance.json"
    if skill_file.exists() and not force:
        existing_cs = _checksum(skill_file.read_text(encoding="utf-8"))
        if existing_cs != skill.checksum:
            print(f"error: {skill_file} exists and its checksum differs from {name}@{skill.version}; use --force to overwrite", file=sys.stderr)
            return 1
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(skill.content, encoding="utf-8")
    provenance = {"tenant": tenant, "name": name, "version": skill.version, "checksum": skill.checksum, "source_db": str(db_path), "installed_at": _now(), "actor": actor}
    prov_file.write_text(json.dumps(provenance, indent=2) + chr(10), encoding="utf-8")
    print(f"installed: {name}@{skill.version} -> {skill_dir}")
    return 0

def list_installed(*, dest, db_path):
    base = _dest_dir(dest)
    if not base.exists():
        print("(no skills directory)")
        return 0
    reg = Registry(db_path)
    found_any = False
    for prov_file in sorted(base.glob("*/.axe-provenance.json")):
        skill_dir = prov_file.parent
        name = skill_dir.name
        found_any = True
        try:
            prov = json.loads(prov_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"{name}  [provenance unreadable: {e}]")
            continue
        pinned_version = prov.get("version", "?")
        pinned_cs = prov.get("checksum", "")
        tenant = prov.get("tenant", "")
        skill_file = skill_dir / "SKILL.md"
        flags = []
        if skill_file.exists():
            on_disk_cs = _checksum(skill_file.read_text(encoding="utf-8"))
            if on_disk_cs != pinned_cs:
                flags.append("MODIFIED")
        else:
            flags.append("MISSING")
        if tenant:
            try:
                hub_versions = reg.versions(tenant, name)
                if hub_versions and hub_versions[-1] != pinned_version:
                    flags.append(f"BEHIND (hub={hub_versions[-1]})")
            except Exception:
                pass
        flag_str = "  [" + ", ".join(flags) + "]" if flags else ""
        print(f"{name}  {pinned_version}{flag_str}")
    if not found_any:
        print("(no installed skills)")
    return 0
