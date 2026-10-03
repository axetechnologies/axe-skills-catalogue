"""Serve the repo's own markdown docs over the hub's existing hostname.

A Worker-hosted docs site needs a Cloudflare token with Workers Scripts
scope, which the axe.onl token does not have. The hub is already published
through the tunnel at skills.axe.onl, so the docs ride that hostname instead
of waiting on a credential -- same edge, same TLS, nothing new to deploy.

Rendering is deliberately small: headings, fenced code, tables, lists and
inline code. A markdown library would be a dependency for a page whose whole
job is to be readable, and the hub has no third-party runtime deps.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# Palette sampled from the shipped v7 cube planes, not transcribed by eye.
_CSS = """
:root{--ink:#0E0C0B;--bone:#F1EBE1;--oxblood:#4B0712;--olive:#3B3E2E;
--dim:#A29C90;--line:#2E3125;--panel:#14160F}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--bone);
font:15px/1.65 ui-sans-serif,-apple-system,"Helvetica Neue",sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:2.5rem 1.4rem 5rem}
a{color:var(--bone)}a:hover{color:#fff}
.eyebrow{font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;
color:var(--dim);margin:0 0 .3rem}
h1,h2,h3{font-family:'Instrument Serif',Didot,'Bodoni 72',Georgia,serif;
font-weight:400;line-height:1.2}
h1{font-size:2.4rem;margin:.2rem 0 1.6rem}
h2{font-size:1.5rem;margin:2.2rem 0 .6rem;padding-top:.7rem;
border-top:2px solid var(--oxblood)}
h3{font-size:1.15rem;margin:1.5rem 0 .4rem;color:var(--dim)}
code{background:var(--panel);border:1px solid var(--line);border-radius:3px;
padding:.08em .32em;font-size:.88em}
pre{background:var(--panel);border:1px solid var(--line);border-left:3px solid
var(--oxblood);padding:.9rem 1rem;overflow-x:auto}
pre code{background:none;border:0;padding:0}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92rem}
th,td{border:1px solid var(--line);padding:.42rem .6rem;text-align:left}
th{background:var(--panel);color:var(--dim);font-weight:600;
letter-spacing:.04em;text-transform:uppercase;font-size:.72rem}
blockquote{margin:1rem 0;padding:.2rem 0 .2rem 1rem;
border-left:3px solid var(--olive);color:var(--dim)}
ul{padding-left:1.2rem}
.idx{list-style:none;padding:0}
.idx li{border-top:1px solid var(--line);padding:.7rem 0}
.idx a{text-decoration:none;font-weight:600}
.idx span{display:block;color:var(--dim);font-size:.85rem}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);
color:var(--dim);font-size:.8rem}
"""

_FRAME = (
    "<!doctype html><html lang=en><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<meta name=theme-color content='#0E0C0B'>"
    "<title>{title} — AXe Skills Hub</title>"
    "<link rel=preconnect href='https://fonts.googleapis.com'>"
    "<link rel=stylesheet href='https://fonts.googleapis.com/css2?"
    "family=Instrument+Serif&display=swap'>"
    "<style>{css}</style></head><body><div class=wrap>"
    "<p class=eyebrow>AXe Skills Hub · docs</p>{body}"
    "<footer><a href='/docs'>docs index</a> · "
    "<a href='/docs/skills'>skills catalogue</a> · "
    "<a href='/healthz'>health</a></footer></div></body></html>"
)


_BULLET = re.compile(r"^([-*+]|\d+\.)\s+")


def _slug(p: Path) -> str:
    return p.stem


def available() -> list[tuple[str, str, str]]:
    """(slug, title, first prose line) for every markdown doc, sorted."""
    out: list[tuple[str, str, str]] = []
    for p in sorted(DOCS_DIR.glob("*.md")):
        title, blurb = _slug(p), ""
        for line in p.read_text(errors="replace").splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("# ") and title == _slug(p):
                title = s[2:].strip()
                continue
            if not s.startswith("#") and not blurb:
                blurb = re.sub(r"[*`\[\]]", "", s)[:150]
                break
        out.append((_slug(p), title, blurb))
    return out


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    # Only local and https links are rendered as links; anything else stays as
    # text, so a doc cannot turn into an outbound link the reader didn't expect.
    return re.sub(r"\[([^\]]+)\]\((/[^)\s]*|https://[^)\s]+)\)",
                  r"<a href='\2'>\1</a>", s)


def _row(line: str) -> str:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return "".join(f"<td>{_inline(c)}</td>" for c in cells)


def render_markdown(text: str) -> str:
    out: list[str] = []
    lines = text.splitlines()
    i, in_code, in_list, in_table = 0, False, False, False

    def close_blocks() -> None:
        nonlocal in_list, in_table
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                close_blocks()
                out.append("<pre><code>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(html.escape(line) + "\n")
            i += 1
            continue
        if not s:
            close_blocks()
            i += 1
            continue
        # A table needs its separator row to be a table at all, which also
        # keeps a lone pipe in prose from opening one.
        if (s.startswith("|") and i + 1 < len(lines)
                and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip() or "|")):
            close_blocks()
            out.append(f"<table><thead><tr>{_row(s).replace('td>', 'th>')}"
                       "</tr></thead><tbody>")
            in_table = True
            i += 2
            continue
        if in_table and s.startswith("|"):
            out.append(f"<tr>{_row(s)}</tr>")
            i += 1
            continue
        m = re.match(r"(#{1,4})\s+(.*)", s)
        if m:
            close_blocks()
            level = min(len(m.group(1)), 3)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if s.startswith("> "):
            close_blocks()
            out.append(f"<blockquote>{_inline(s[2:])}</blockquote>")
            i += 1
            continue
        if re.match(r"[-*+]\s+|\d+\.\s+", s):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = _inline(_BULLET.sub("", s))
            out.append(f"<li>{item}</li>")
            i += 1
            continue
        if set(s) <= {"-", "="} and len(s) > 2:
            i += 1
            continue
        close_blocks()
        out.append(f"<p>{_inline(s)}</p>")
        i += 1
    if in_code:
        out.append("</code></pre>")
    close_blocks()
    return "".join(out)


def render_index() -> str:
    items = "".join(
        f"<li><a href='/docs/{sl}'>{html.escape(t)}</a>"
        f"<span>{html.escape(b)}</span></li>"
        for sl, t, b in available())
    body = ("<h1>Documentation</h1><p>The hub's own docs, served from the "
            "repository over this hostname.</p>"
            f"<ul class=idx>{items}</ul>")
    return _FRAME.format(title="Docs", css=_CSS, body=body)


def render_doc(slug: str) -> str | None:
    """Render one doc, or None if the slug names no shipped markdown file."""
    # Compared against the glob rather than joined onto DOCS_DIR, so a slug
    # cannot traverse out of the docs directory.
    if slug not in {sl for sl, _, _ in available()}:
        return None
    p = DOCS_DIR / f"{slug}.md"
    return _FRAME.format(title=html.escape(slug), css=_CSS,
                         body=render_markdown(p.read_text(errors="replace")))


# The browsable catalogue index (/docs/skills). It renders a static shell and
# fetches the public, versioned read API client-side — /v1/skills (browse) and
# /v1/skills/search?q= (ranked). No server-side data and no new dependency, so it
# works on the read-only public origin exactly as the markdown docs do. Category
# chips are the known top categories; clicking one runs a ranked search for that
# term. Each card links to /portal/<name> for the full skill.
_BROWSE_CSS = _CSS + """
.tools{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin:1.2rem 0}
#q{flex:1 1 260px;min-width:0;background:var(--panel);border:1px solid var(--line);
border-radius:6px;color:var(--bone);padding:.6rem .8rem;font:inherit}
#q:focus{outline:0;border-color:var(--oxblood)}
.chips{display:flex;gap:.4rem;flex-wrap:wrap;margin:.2rem 0 1rem}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;
color:var(--dim);padding:.28rem .7rem;font-size:.78rem;cursor:pointer}
.chip:hover,.chip[aria-pressed=true]{color:var(--bone);border-color:var(--oxblood)}
#count{color:var(--dim);font-size:.8rem;margin:.2rem 0 1rem}
.grid{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{display:block;text-decoration:none;background:var(--panel);
border:1px solid var(--line);border-left:3px solid var(--oxblood);border-radius:6px;
padding:.8rem .9rem}
.card:hover{border-color:var(--oxblood)}
.card .nm{font-weight:600;color:var(--bone);word-break:break-word}
.card .ds{color:var(--dim);font-size:.85rem;margin:.35rem 0 0;
display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.card .mt{margin-top:.5rem;display:flex;gap:.4rem;flex-wrap:wrap}
.badge{font-size:.66rem;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);
border:1px solid var(--line);border-radius:3px;padding:.05rem .32rem}
"""

# Known top categories (from the catalogue's own category counts). Seeded rather
# than aggregated so the page needs no extra endpoint; a chip runs a ranked search.
_TOP_CATEGORIES = [
    "software-development", "security", "productivity", "research", "devops",
    "data-science", "autonomous-ai-agents", "creative", "media", "social-media",
    "communication", "blockchain", "vision-ai", "mlops", "networking",
]


def render_skills_browse() -> str:
    chips = "".join(
        f"<button class=chip data-cat=\"{html.escape(c)}\">{html.escape(c.replace('-', ' '))}</button>"
        for c in _TOP_CATEGORIES)
    body = (
        "<h1>Skills catalogue</h1>"
        "<p>Reusable, model-agnostic playbooks — curated by AXE and mirrored from the "
        "community. Search the catalogue or pick a category; open a skill for its full "
        "instructions.</p>"
        "<div class=tools><input id=q type=search autocomplete=off "
        "placeholder='Search skills — e.g. code review, baidu, kubernetes'></div>"
        f"<div class=chips>{chips}</div>"
        "<p id=count>Loading…</p>"
        "<div id=grid class=grid></div>"
        "<script>" + _BROWSE_JS + "</script>"
    )
    return _FRAME.format(title="Skills", css=_BROWSE_CSS, body=body)


# Client logic: fetch the public read API, render cards, debounce search, and let
# a category chip run a ranked search for that term. Defensive about the record
# shape (array | {results} | {skills}) and about where a field lives (top-level
# metadata vs metadata.taxonomy), so it renders both first-party and community rows.
_BROWSE_JS = r"""
(function(){
  var grid=document.getElementById('grid'),count=document.getElementById('count'),
      q=document.getElementById('q');
  function esc(s){var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML;}
  function field(r,ks){var m=r.metadata||{},t=m.taxonomy||{};
    for(var i=0;i<ks.length;i++){var k=ks[i];
      if(t[k])return t[k]; if(m[k])return m[k]; if(r[k])return r[k];}
    return '';}
  function desc(r){var m=r.metadata||{},t=m.taxonomy||{},c=r.content;
    if(t.description)return t.description;
    if(typeof c==='string'){try{var o=JSON.parse(c);if(o&&o.description)return o.description;}catch(e){}}
    return m.description||r.description||'';}
  function card(r){
    var name=r.name||'', cat=field(r,['category_label','categoryLabel','category']),
        src=field(r,['source']);
    var a=document.createElement('a');a.className='card';
    a.href='/portal/'+encodeURIComponent(name).replace(/%3A/gi,':');
    var mt='';
    if(cat)mt+='<span class=badge>'+esc(String(cat).replace(/-/g,' '))+'</span>';
    if(src)mt+='<span class=badge>'+esc(src)+'</span>';
    a.innerHTML='<div class=nm>'+esc(name)+'</div>'+
      '<div class=ds>'+esc(desc(r))+'</div>'+(mt?'<div class=mt>'+mt+'</div>':'');
    return a;}
  function rows(data){return Array.isArray(data)?data:(data&&(data.results||data.skills))||[];}
  function render(data,label){
    var rs=rows(data);grid.innerHTML='';
    rs.forEach(function(r){grid.appendChild(card(r));});
    count.textContent=rs.length?(rs.length+' skill'+(rs.length>1?'s':'')+(label?' · '+label:'')):('no skills'+(label?' for '+label:''));
  }
  function load(url,label){
    count.textContent='Loading…';
    fetch(url,{headers:{'Accept':'application/json'}}).then(function(r){return r.json();})
      .then(function(d){render(d,label);})
      .catch(function(){count.textContent='catalogue unreachable — try again';});
  }
  function browse(){load('/v1/skills?limit=60','browsing');}
  function search(term){term=term.trim();
    if(!term){browse();return;}
    load('/v1/skills/search?q='+encodeURIComponent(term)+'&limit=60','"'+term+'"');}
  var t;q.addEventListener('input',function(){clearTimeout(t);t=setTimeout(function(){
    document.querySelectorAll('.chip').forEach(function(c){c.setAttribute('aria-pressed','false');});
    search(q.value);},250);});
  document.querySelectorAll('.chip').forEach(function(c){c.addEventListener('click',function(){
    document.querySelectorAll('.chip').forEach(function(x){x.setAttribute('aria-pressed','false');});
    c.setAttribute('aria-pressed','true');var cat=c.getAttribute('data-cat');
    q.value=cat.replace(/-/g,' ');search(cat.replace(/-/g,' '));});});
  browse();
})();
"""
