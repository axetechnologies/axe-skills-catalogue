(function () {
  "use strict";
  var $ = Hub.$, el = Hub.el, n = Hub.n;
  var PER = 12;
  var KINDS = [], CATS = {};
  var ST = { verified: {}, totals: {}, tiers: {}, flags: {}, licence: {}, sources: {}, verified_records: [] };
  var RANK = {
    verified: { label: "Verified", cls: "vf", note: "Promoted by the owner. Operators may install it." },
    quarantined: { label: "Quarantined", cls: "", note: "Federated, not yet reviewed. Operators cannot install it." }
  };
  var ONE = { skill: "skill", plugin: "plugin", connector: "connector" };
  var KLABEL = { skill: "Skills", plugin: "Plugins", connector: "Connectors" };
  var SKILL_FLAGS = ["Read-only", "Needs an account", "Spends money", "Anti-bot", "Personal data"];

  function count(kind) { var k = KINDS.filter(function (x) { return x.kind === kind; })[0]; return k ? k.count : 0; }
  function rank(r) { return r.verified ? "verified" : "quarantined"; }
  function sq(rk) { var i = document.createElement("i"); i.className = "sq " + RANK[rk].cls; i.setAttribute("aria-hidden", "true"); return i; }
  function srcName(s) { return s === "axe:first-party" ? "Operator" : s === "axe:plugin" ? "Operator plugin" : String(s || "").replace(/^axehub:/, ""); }
  function federated(s) { return /^axehub:/.test(s); }
  function monogram(r) { var w = r.title.replace(/[^a-z0-9]/gi, ""); return (w.slice(0, 2) || "sk").toLowerCase(); }

  /* the signature move: hollow until promoted */
  function art(r) {
    var rk = rank(r), box = el("div", "art " + RANK[rk].cls); box.setAttribute("aria-hidden", "true");
    var svg = Hub.svg("svg", { viewBox: "0 0 300 136", preserveAspectRatio: "xMinYMid slice" });
    var t = Hub.svg("text", { x: "-4", y: "150", "font-size": "210", "class": rk === "verified" ? "v" : "q" });
    t.textContent = monogram(r); svg.appendChild(t); box.appendChild(svg);
    if (rk === "verified") box.appendChild(el("i", "pin"));
    return box;
  }
  function copyBtn(name) {
    var b = el("button", "btn", "Copy command"); b.type = "button";
    b.addEventListener("click", function () { Hub.copy(Hub.recordLine(name), b, "Copy command"); });
    return b;
  }

  /* chrome */
  Hub.theme("barracks-theme", [].slice.call(document.querySelectorAll(".theme")));
  var menu = $("menu"), nav = $("nav");
  menu.addEventListener("click", function () { var o = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", o); });

  /* hero: every figure from the live catalogue */
  function hero() {
    var T = KINDS.reduce(function (a, k) { return a + k.count; }, 0);
    var V = Object.keys(ST.verified || {}).reduce(function (a, k) { return a + ST.verified[k]; }, 0), Q = T - V;
    var fed = ((ST.sources || {}).skill || []).filter(function (s) { return federated(s[0]); }).length;
    var meta = $("meta");
    meta.textContent = n(T) + " entries · " + n(fed) + " federated skill indexes + Operator's own · ";
    meta.appendChild(el("span", null, ST.snapshot ? "Snapshot " + ST.snapshot : "Snapshot not recorded"));
    $("snap").textContent = Hub.offline ? "Live read failed: showing figures embedded when the page was served" : "Counts from the live hub" + (ST.snapshot ? ", " + ST.snapshot : "");
    var cap = matchMedia("(max-width: 520px)").matches ? 300 : 1300;
    var unit = Math.pow(10, Math.max(0, Math.ceil(Math.log10(T / cap))));
    var field = $("field"), frag = document.createDocumentFragment(), idx = 0;
    function add(c, rk) { for (var k = 0; k < Math.ceil(c / unit); k++) { var s = sq(rk); s.style.setProperty("--i", idx++); frag.appendChild(s); } }
    add(V, "verified"); add(Q, "quarantined"); field.appendChild(frag);
    var st = $("stats");
    [["verified", V], ["quarantined", Q]].forEach(function (p) {
      var d = el("div"), dt = el("dt"); dt.appendChild(sq(p[0])); dt.appendChild(document.createTextNode(RANK[p[0]].label));
      d.appendChild(dt); d.appendChild(el("dd", null, n(p[1]))); st.appendChild(d);
    });
    var d3 = el("div"), dt3 = el("dt", null, "Reviewed"); d3.appendChild(dt3); d3.appendChild(el("dd", "dim", "—")); st.appendChild(d3);
    $("unit").textContent = "One square, " + n(unit) + " entries, rounded up. The red one is every verified entry. The data records no review step between the two.";
    $("api").textContent = ["/v1/kinds", "/v1/skills?kind=plugin", "/v1/skills/search?q=", "/v1/categories", "/v1/skills/{name}"]
      .map(function (p) { return "GET " + location.origin + p; }).join("\n");
  }

  /* featured: verified, first party first */
  var FEAT = [], fi = 0;
  function featSetup() {
    FEAT = (ST.verified_records || []).map(Hub.norm).filter(function (r) { return r.verified; });
    var own = FEAT.filter(function (r) { return r.source === "axe:first-party"; });
    FEAT = (own.length >= 3 ? own : FEAT).slice(0, 5);
    if (FEAT.length < 1) { $("feat-sec").hidden = true; return; }
    var dots = $("dots");
    FEAT.forEach(function (r, i) {
      var b = el("button", "dot"); b.type = "button"; b.setAttribute("aria-label", "Featured " + (i + 1) + " of " + FEAT.length);
      b.appendChild(el("i")); b.addEventListener("click", function () { fi = i; feat(); }); dots.appendChild(b);
    });
    feat();
  }
  function feat() {
    var r = FEAT[fi], box = el("article", "feat"), tx = el("div", "feat-txt");
    var host = $("feat"); host.textContent = "";
    tx.appendChild(el("div", "lbl", RANK.verified.label + " · " + srcName(r.source)));
    tx.appendChild(el("h3", null, r.title));
    tx.appendChild(el("p", null, r.description));
    tx.appendChild(el("code", null, Hub.recordLine(r.name)));
    tx.appendChild(el("span", "by", "by " + (r.author || "unknown") + " · " + (r.license || "no licence") + " · " + r.version));
    var act = el("div", "feat-act"), d = el("a", "btn solid", "Details"); d.href = "#/skill/" + encodeURIComponent(r.name);
    act.appendChild(d); act.appendChild(copyBtn(r.name)); tx.appendChild(act);
    box.appendChild(tx); box.appendChild(art(r)); host.appendChild(box);
    [].forEach.call($("dots").children, function (b, i) { b.setAttribute("aria-current", i === fi ? "true" : "false"); });
  }
  $("fPrev").addEventListener("click", function () { if (FEAT.length) { fi = (fi + FEAT.length - 1) % FEAT.length; feat(); } });
  $("fNext").addEventListener("click", function () { if (FEAT.length) { fi = (fi + 1) % FEAT.length; feat(); } });

  /* state and loading */
  var S, rows = [], offset = 0, more = false, total = null, seq = 0, offlineNow = false, shown = PER, catsOpen = false;
  function fresh(kind) { return { kind: kind || "skill", q: "", rank: "", cat: "", tier: "", lic: false, hide: {}, sort: "name" }; }
  S = fresh();

  function localMatch(r) {
    if (S.cat && r.category !== S.cat) return false;
    var q = S.q.trim().toLowerCase();
    return !q || (r.name + " " + r.title + " " + r.description + " " + r.author + " " + r.publisher).toLowerCase().indexOf(q) > -1;
  }
  function load(reset) {
    if (reset) { rows = []; offset = 0; more = false; total = null; shown = PER; }
    var mine = ++seq;
    if (S.rank === "verified") {
      rows = S.kind === "skill" ? (ST.verified_records || []).map(Hub.norm).filter(function (r) { return r.verified && localMatch(r); }) : [];
      more = false; total = rows.length; offlineNow = false; render(); return;
    }
    $("status").textContent = "Reading the catalogue…";
    Hub.page({ kind: S.kind, q: S.q, category: S.cat, limit: S.kind === "connector" ? 100 : 48, offset: offset }).then(function (res) {
      if (mine !== seq) return;
      rows = rows.concat(res.rows); offset += res.rows.length; more = res.more; total = res.total; offlineNow = res.offline;
      render();
    });
  }
  function passes(r) {
    if (S.rank === "quarantined" && r.verified) return false;
    if (S.tier && r.tier !== S.tier) return false;
    if (S.lic && !r.license) return false;
    for (var k in S.hide) if (r.flags.indexOf(k) > -1) return false;
    return true;
  }
  function sorted(list) {
    var a = list.slice();
    a.sort(function (x, y) {
      if (S.sort === "cat") return (x.categoryLabel || "~").localeCompare(y.categoryLabel || "~") || x.title.localeCompare(y.title);
      if (S.sort === "rank") return (y.verified - x.verified) || x.title.localeCompare(y.title);
      return x.title.localeCompare(y.title);
    });
    return a;
  }

  /* kinds, chips */
  function kindTabs() {
    var box = $("kinds"); box.textContent = "";
    KINDS.forEach(function (k) {
      var b = el("button", "kind"); b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(k.kind === S.kind));
      b.appendChild(document.createTextNode(k.label)); b.appendChild(el("small", null, n(k.count)));
      b.addEventListener("click", function () { var q = S.q; S = fresh(k.kind); S.q = q; catsOpen = false; kindTabs(); load(true); });
      box.appendChild(b);
    });
  }
  function chip(label, cnt, on, fn, rk) {
    var b = el("button", "chip"); b.type = "button"; b.setAttribute("aria-pressed", on ? "true" : "false");
    if (rk) b.appendChild(sq(rk));
    b.appendChild(document.createTextNode(Hub.clean(label)));
    if (cnt != null) b.appendChild(el("small", null, n(cnt)));
    b.addEventListener("click", fn); return b;
  }
  function drawChips() {
    var c = $("chips"), kind = S.kind, V = (ST.verified || {})[kind] || 0, T = count(kind);
    c.textContent = "";
    [["verified", V], ["quarantined", T - V]].forEach(function (p) {
      var ch = chip(RANK[p[0]].label, p[1], S.rank === p[0], function () { if (!p[1]) return; S.rank = S.rank === p[0] ? "" : p[0]; load(true); }, p[0]);
      if (!p[1]) { ch.setAttribute("aria-disabled", "true"); ch.title = "Nothing of this kind is in this state"; }
      c.appendChild(ch);
    });
    c.appendChild(chip("Licence declared", (ST.licence || {})[kind] || 0, S.lic, function () { S.lic = !S.lic; render(); }));
    if (kind === "plugin") ["Official", "Certified", "Community"].forEach(function (t) {
      if ((ST.tiers || {})[t]) c.appendChild(chip(t, ST.tiers[t], S.tier === t, function () { S.tier = S.tier === t ? "" : t; render(); }));
    });
    var fl = (ST.flags || {})[kind] || {};
    if (kind !== "skill") Object.keys(fl).sort(function (a, b) { return fl[b] - fl[a]; }).slice(0, 4).forEach(function (k) {
      c.appendChild(chip("Hide: " + Hub.flagLabel(k), fl[k], !!S.hide[k], function () { if (S.hide[k]) delete S.hide[k]; else S.hide[k] = 1; render(); }));
    });
    c.appendChild(el("span", "sep"));
    var cats = (CATS[kind] || []).filter(function (x) { return x.category !== "other" && x.category !== "general"; }).sort(function (a, b) { return b.count - a.count; });
    var lim = matchMedia("(max-width: 520px)").matches ? 0 : 8;
    (catsOpen ? cats : cats.slice(0, lim)).forEach(function (x) {
      c.appendChild(chip(x.label, x.count, S.cat === x.category, function () { S.cat = S.cat === x.category ? "" : x.category; load(true); }));
    });
    if (cats.length > lim) {
      var m = el("button", "more", catsOpen ? "Show fewer" : (lim ? "Show " + n(cats.length - lim) + " more" : "Show " + n(cats.length) + " categories")); m.type = "button";
      m.addEventListener("click", function () { catsOpen = !catsOpen; drawChips(); }); c.appendChild(m);
    }
    var un = (CATS[kind] || []).filter(function (x) { return x.category === "other" || x.category === "general"; }).reduce(function (a, x) { return a + x.count; }, 0);
    $("triage").textContent = un ? n(un) + " " + KLABEL[kind].toLowerCase() + " carry no usable category yet. They wait in the classification queue, and search still finds them." : "";
  }

  /* cards */
  function card(r) {
    var li = document.createElement("li"), a = el("a", "card"); a.href = "#/skill/" + encodeURIComponent(r.name);
    a.appendChild(art(r));
    var b = el("div", "body");
    b.appendChild(el("span", "by", (r.author || r.publisher ? (r.author || r.publisher) + " · " : "") + srcName(r.source) + (r.tier ? " · Tier: " + r.tier : "")));
    b.appendChild(el("span", "nm", r.title));
    b.appendChild(el("span", "vh", RANK[rank(r)].label));
    b.appendChild(el("p", "ds", r.description || "No description given."));
    a.appendChild(b);
    var f = el("div", "foot");
    f.appendChild(el("span", "ct", r.categoryLabel || "Unclassified"));
    var right = r.kind === "connector" ? (r.flags.length ? r.flags.map(Hub.flagLabel).join(", ") : "No flags recorded") : (r.license || "No licence") + " · " + (r.version || "");
    f.appendChild(el("span", "lv", right)); a.appendChild(f);
    li.appendChild(a); return li;
  }
  function render() {
    var grid = $("grid"); grid.textContent = "";
    var list = sorted(rows.filter(passes));
    if (!list.length) grid.appendChild(el("li", "empty", rows.length ? "Nothing loaded matches these filters. Clear one, or load more." :
      S.rank === "verified" && S.kind !== "skill" ? "Nothing in " + KLABEL[S.kind].toLowerCase() + " has been promoted. Every " + ONE[S.kind] + " here is quarantined." : "Nothing matches. Clear a filter, or search for another word."));
    list.slice(0, shown).forEach(function (r) { grid.appendChild(card(r)); });
    var left = list.length - shown;
    var mb = $("more"); mb.hidden = left <= 0 && !more;
    mb.textContent = left > 0 ? "Show more (" + n(left) + " left)" : "Load more from the catalogue";
    $("count").textContent = n(Math.min(shown, list.length)) + " of " + n(list.length) + " loaded" + (total != null ? " (" + n(total) + " in all)" : more ? " (more available)" : "");
    $("status").textContent = offlineNow ? "Live read failed. Showing the sample this page was rendered with." : "";
    drawChips();
  }
  $("more").addEventListener("click", function () {
    var list = rows.filter(passes);
    if (list.length > shown) { shown += PER; render(); } else if (more) { shown += PER; load(false); }
  });
  var tmr;
  $("q").addEventListener("input", function (e) { clearTimeout(tmr); tmr = setTimeout(function () { S.q = e.target.value; load(true); }, 200); });
  $("sort").addEventListener("change", function (e) { S.sort = e.target.value; render(); });
  document.addEventListener("keydown", function (e) {
    var tg = document.activeElement.tagName;
    if (e.key === "/" && tg !== "INPUT" && tg !== "SELECT") { e.preventDefault(); location.hash = ""; $("q").focus(); }
  });

  /* shelves */
  function shelves() {
    var host = $("shelves"); host.textContent = "";
    function shelf(title, text, items, go) {
      if (!items.length) return;
      var box = el("div", "shelf"), hd = el("div", "shelf-head"), tx = el("div");
      tx.appendChild(el("div", "lbl", "Shelf")); tx.appendChild(el("h2", null, title)); tx.appendChild(el("p", null, text)); hd.appendChild(tx);
      var b = el("button", "btn", "See all"); b.type = "button";
      b.addEventListener("click", function () { go(); kindTabs(); $("q").value = S.q; load(true); $("catalogue").scrollIntoView(); });
      hd.appendChild(b); box.appendChild(hd);
      var ul = el("ul", "grid"); items.slice(0, 4).forEach(function (r) { ul.appendChild(card(r)); });
      box.appendChild(ul); host.appendChild(box);
    }
    var own = (ST.verified_records || []).map(Hub.norm).filter(function (r) { return r.source === "axe:first-party"; });
    shelf("Operator's own", "First-party skills, promoted and ready for your Operators.", own, function () { S = fresh("skill"); S.rank = "verified"; });
    if (count("connector")) Hub.page({ kind: "connector", limit: 4 }).then(function (res) {
      shelf("Connectors", "Account-backed connectors from the Hermes index. Each one is quarantined, and its recorded risk flags show on the card.", res.rows,
        function () { S = fresh("connector"); });
    });
  }

  /* detail page (#/skill/<name>) */
  var listView = $("list-view"), dv = $("detail-view"), hero0 = $("hero");
  function fact(dl, k, v, mono) { dl.appendChild(el("dt", null, k)); var dd = el("dd", mono ? "mono" : null); if (v instanceof Node) dd.appendChild(v); else dd.textContent = Hub.clean(v); dl.appendChild(dd); }
  function drawDetail(r) {
    dv.textContent = "";
    var back = el("a", "back", "← All entries"); back.href = "#catalogue"; dv.appendChild(back);
    if (!r) { dv.appendChild(el("p", null, "That record was not found in the catalogue.")); return; }
    var rk = rank(r), head = el("div", "dhead"), left = el("div");
    left.appendChild(el("div", "lbl", RANK[rk].label + " · " + KLABEL[r.kind].replace(/s$/, "") + " · " + (r.categoryLabel || "Unclassified")));
    left.appendChild(el("h1", r.title.length > 14 ? "long" : null, r.title));
    left.appendChild(el("span", "by", "by " + (r.author || r.publisher || "unknown") + (federated(r.source) ? " · federated from " + srcName(r.source) : " · first party")));
    var tr = el("div", "track"); tr.setAttribute("aria-label", "Promotion: " + RANK[rk].label);
    ["quarantined", "verified"].forEach(function (k, i) {
      if (i) tr.appendChild(el("span", "off", "→"));
      var here = k === rk, s = el("span", here ? "on" : "off");
      s.appendChild(sq(here ? k : "quarantined")); s.appendChild(document.createTextNode(" " + RANK[k].label)); tr.appendChild(s);
    });
    left.appendChild(tr); left.appendChild(el("p", "desc", r.description || "No description given."));
    head.appendChild(left); head.appendChild(art(r)); dv.appendChild(head);

    var cmd = el("div", "cmd"), top = el("div", "top"); top.appendChild(el("div", "lbl", "Fetch the record"));
    if (rk === "verified") top.appendChild(copyBtn(r.name));
    cmd.appendChild(top); cmd.appendChild(el("pre", null, Hub.recordLine(r.name)));
    cmd.appendChild(el("p", null, rk === "verified" ? "Text only. Read the record before you run anything it names." : "Text only. This entry is held in quarantine, so Operators cannot install it until the owner promotes it. The line reads the record; it installs nothing."));
    dv.appendChild(cmd);

    var g = el("div", "dgrid"), fx = el("div"), dl = el("dl", "facts");
    fx.appendChild(el("div", "lbl", "Record"));
    fact(dl, "Category", r.categoryLabel ? r.categoryLabel + (r.categorySource === "inferred" ? " (inferred by the catalogue)" : r.categorySource ? " (from upstream)" : "") : "Awaiting classification");
    fact(dl, "Version", (r.version || "not recorded") + (r.upstreamVersion && r.upstreamVersion !== r.version ? " (upstream " + r.upstreamVersion + ")" : ""));
    fact(dl, "Licence", r.license || "None declared");
    fact(dl, "Source", srcName(r.source) + (federated(r.source) ? " (federated)" : " (first party)"));
    if (r.tier) fact(dl, "Publisher tier", r.tier + ", the upstream index's label. It is not our review.");
    fact(dl, "Promotion", RANK[rk].note);
    if (r.defect) fact(dl, "Data note", "The upstream record sets both verified and quarantined. Barracks treats it as quarantined until the owner reviews it.");
    if (r.withdrawn) fact(dl, "Upstream", "Withdrawn by its upstream index. Kept here, quarantined, for the record.");
    if (r.creds) fact(dl, "Credentials", Hub.credLabel(r.creds));
    if (r.disclosure) fact(dl, "Disclosure", r.disclosure);
    if (r.upstreamInstall && r.upstreamInstall.command) fact(dl, "Upstream install", "Text only, not run or endorsed here: " + r.upstreamInstall.command);
    fact(dl, "Env vars", r.env.length ? r.env.join(", ") : "None recorded", r.env.length);
    fact(dl, "Platforms", r.platforms.length ? r.platforms.join(", ") : "Not stated");
    fact(dl, "Homepage", Hub.link(r.homepage));
    fact(dl, "Checksum", r.checksum ? "sha256 " + r.checksum : "None", true);
    fact(dl, "Record id", r.name, true);
    fx.appendChild(dl); g.appendChild(fx);
    var rkb = el("div", "risk"); rkb.appendChild(el("div", "lbl", "Risk flags"));
    var tb = el("table"); tb.appendChild(el("caption", "vh", "Risk flags for this entry"));
    var body = el("tbody");
    if (r.kind === "skill") SKILL_FLAGS.forEach(function (f) { var row = el("tr"), th = el("th", null, f); th.scope = "row"; row.appendChild(th); row.appendChild(el("td", null, "Not assessed")); body.appendChild(row); });
    else {
      var known = Object.keys((ST.flags || {})[r.kind] || {});
      r.flags.forEach(function (f) { if (known.indexOf(f) < 0) known.push(f); });
      known.forEach(function (f) { var row = el("tr"), th = el("th", null, Hub.flagLabel(f)); th.scope = "row"; row.appendChild(th); row.appendChild(el("td", null, r.flags.indexOf(f) > -1 ? "Recorded" : "None recorded")); body.appendChild(row); });
    }
    tb.appendChild(body); rkb.appendChild(tb);
    rkb.appendChild(el("p", null, r.kind === "skill" ? "The owner's review fills in each flag. Until then, treat every flag as unknown." : "These are the flags the index recorded from the entry's own disclosure. None recorded does not mean none exist; the owner's review comes first."));
    g.appendChild(rkb); dv.appendChild(g);
  }
  var shownName = "";
  function route() {
    var m = location.hash.match(/^#\/skill\/(.+)$/);
    if (m) {
      var id; try { id = decodeURIComponent(m[1]); } catch (e) { id = ""; }
      listView.hidden = true; hero0.hidden = true; dv.hidden = false; shownName = id;
      var local = rows.concat((ST.verified_records || []).map(Hub.norm)).filter(function (x) { return x.name === id; })[0];
      drawDetail(local || null);
      Hub.detail(id).then(function (d) {
        if (shownName !== id) return;
        var fb = ((Hub.fallback.sample || {})[S.kind] || []).map(Hub.norm).filter(function (x) { return x.name === id; })[0];
        drawDetail(d || local || fb || null);
        window.scrollTo(0, 0);
        var h = dv.querySelector("h1"); if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
      });
    } else { shownName = ""; listView.hidden = false; hero0.hidden = false; dv.hidden = true; }
  }
  window.addEventListener("hashchange", route);

  Promise.all([Hub.kinds(), Hub.stats(), Hub.categories("skill"), Hub.categories("plugin"), Hub.categories("connector")]).then(function (r) {
    KINDS = r[0]; ST = r[1]; CATS = { skill: r[2], plugin: r[3], connector: r[4] };
    hero(); featSetup(); kindTabs(); shelves(); load(true); route();
  });
})();
