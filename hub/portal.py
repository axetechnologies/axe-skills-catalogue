"""Invariant: the portal never renders another tenant's data; yanked versions are labelled."""
from __future__ import annotations

import html
from typing import Any


def _e(s: Any) -> str:
    return html.escape(str(s))


_CSS = (
    "*{box-sizing:border-box;margin:0;padding:0}"
    "body{font-family:system-ui,sans-serif;background:#f8f9fa;color:#212529;padding:1.5rem}"
    "h1{font-size:1.5rem;margin-bottom:1rem}h2{font-size:1.1rem;margin-bottom:.5rem}"
    "a{color:#0d6efd;text-decoration:none}a:hover{text-decoration:underline}"
    "table{border-collapse:collapse;width:100%;background:#fff;border-radius:6px;"
    "overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)}"
    "th,td{padding:.6rem 1rem;text-align:left;border-bottom:1px solid #dee2e6}"
    "th{background:#e9ecef;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em}"
    ".yanked{opacity:.5;text-decoration:line-through}"
    ".badge{display:inline-block;padding:.2em .5em;border-radius:4px;font-size:.75rem;font-weight:600}"
    ".badge-pass{background:#d1e7dd;color:#0a3622}.badge-fail{background:#f8d7da;color:#58151c}"
    ".badge-yanked{background:#fff3cd;color:#664d03}"
    ".meta{font-size:.85rem;color:#6c757d;margin-bottom:1rem}"
    "pre{background:#212529;color:#f8f9fa;padding:1rem;border-radius:6px;overflow-x:auto;font-size:.85rem}"
)


def _base(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title>"
        f"<style>{_CSS}</style>"
        f"</head><body>{body}</body></html>"
    )


def render_catalog(tenant: str, skills: list[dict]) -> str:
    parts = []
    for s in skills:
        yanked = s.get("yanked_at") is not None
        cls = ' class="yanked"' if yanked else ""
        badge = '<span class="badge badge-yanked">yanked</span>' if yanked else ""
        name = s["name"]
        link = f'<a href="/portal/{_e(name)}">{_e(name)}</a>'
        parts.append(
            f"<tr{cls}><td>{link} {badge}</td>"
            f"<td>{_e(s.get('version', ''))}</td>"
            f"<td>{_e(s.get('format', ''))}</td>"
            f"<td>{_e(s.get('created_by', ''))}</td>"
            f"<td>{_e(str(s.get('created_at', ''))[:19])}</td></tr>"
        )
    rows = "".join(parts) or '<tr><td colspan="5">No skills found.</td></tr>'
    body = (
        f"<h1>Skills — {_e(tenant)}</h1>"
        f'<p class="meta">{len(skills)} skill(s) total (including yanked)</p>'
        "<table><thead><tr><th>Name</th><th>Version</th><th>Format</th>"
        "<th>Published by</th><th>Published at</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return _base(f"Skills — {tenant}", body)


def render_skill(skill: Any, versions: list[str], eval_result: dict | None) -> str:
    yanked_banner = ""
    if skill.yanked:
        yanked_banner = (
            '<p class="badge badge-yanked" style="margin-bottom:1rem">'
            "YANKED — this version has been removed</p>"
        )

    version_links = " | ".join(
        f'<a href="/portal/{_e(skill.name)}?version={_e(v)}">{_e(v)}</a>'
        for v in versions
    )

    if eval_result:
        total = eval_result.get("total", 0)
        passed = eval_result.get("passed", 0)
        failed = eval_result.get("failed", 0)
        errors = eval_result.get("errors", 0)
        ok = failed == 0 and errors == 0 and total > 0
        cls = "badge-pass" if ok else "badge-fail"
        summary = f'<span class="badge {cls}">{passed}/{total} passed</span>'
        rows_parts = []
        for r in eval_result.get("results", []):
            bc = "badge-pass" if r["passed"] else "badge-fail"
            st = "pass" if r["passed"] else "fail"
            err = f" — {_e(r.get('error') or '')}" if r.get("error") else ""
            rows_parts.append(
                f"<tr><td>{_e(r.get('name', ''))}</td>"
                f'<td><span class="badge {bc}">{st}</span>{err}</td></tr>'
            )
        rh = "".join(rows_parts) or '<tr><td colspan="2">No cases.</td></tr>'
        eval_html = (
            f'<h2 style="margin-top:1rem">Eval results {summary}</h2>'
            f"<table><thead><tr><th>Case</th><th>Result</th></tr></thead>"
            f"<tbody>{rh}</tbody></table>"
        )
    else:
        eval_html = '<p class="meta">No eval results recorded.</p>'

    if skill.yanked:
        content_html = '<p class="meta">Content hidden — version is yanked.</p>'
    else:
        content_html = f"<pre>{_e(skill.content[:4000])}</pre>"

    body = (
        '<p><a href="/portal">← catalog</a></p>'
        f"<h1>{_e(skill.name)}</h1>{yanked_banner}"
        f'<p class="meta">Version: {_e(skill.version)} | Format: {_e(skill.format)} | '
        f"Published by {_e(skill.created_by)} at {_e(skill.created_at[:19])}</p>"
        f'<div style="margin-top:1rem"><strong>Versions:</strong> {version_links}</div>'
        f'{eval_html}<h2 style="margin-top:1rem">Content</h2>{content_html}'
    )
    return _base(f"{skill.name} — {skill.version}", body)
