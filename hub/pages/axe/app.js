(function () {
  "use strict";
  var $ = Hub.$, el = Hub.el, n = Hub.n;
  var KINDS = [], ST = { verified: {}, tiers: {}, flags: {}, sources: {}, licence: {}, credentials: {}, verified_records: [] };
  var CATS = {};
  var LABEL = { skill: "Skills", plugin: "Plugins", connector: "Connectors" };
  var ONE = { skill: "skill", plugin: "plugin", connector: "connector" };
  var COLLECTIONS = [
    ["Secure software development", "secure code"],
    ["Cybersecurity and audit", "security audit"],
    ["Document and records handling", "records management"],
    ["Data analysis", "data analysis"],
    ["Logistics", "logistics"],
    ["Field and offline operations", "offline"]
  ];
  var STEP = 24;

  function count(kind) { var k = KINDS.filter(function (x) { return x.kind === kind; })[0]; return k ? k.count : 0; }
  function sum(o) { var t = 0; for (var k in o) t += o[k]; return t; }
  function crossSvg() {
    var s = Hub.svg("svg", { "class": "cross", viewBox: "0 0 20 20", "aria-hidden": "true" });
    s.appendChild(Hub.svg("path", { d: "M10 1V19M1 10H19" }));
    return s;
  }

  var aboveLeft = 0, shownA = 8, F, rows = [], offset = 0, more = false, total = null, seq = 0, offlineNow = false;
  function fresh(kind) { return { kind: kind || "skill", q: "", cat: "", tr: "", tier: "", hide: {}, lic: "", sort: "state" }; }
  F = fresh();

  /* hero */
  function hero() {
    var all = sum(KINDS.reduce(function (o, k) { o[k.kind] = k.count; return o; }, {}));
    var v = sum(ST.verified || {});
    $("k-total").textContent = n(all);
    $("k-verified").textContent = n(v);
    $("k-quar").textContent = n(all - v);
    $("k-defect").textContent = n(ST.defect || 0);
    var ol = $("cols");
    COLLECTIONS.forEach(function (c) {
      var li = el("li"), b = el("button", "colbtn");
      b.type = "button";
      b.appendChild(el("span", "t", c[0]));
      b.appendChild(el("span", "k caps dim", "Live search: " + c[1]));
      b.addEventListener("click", function () {
        F = fresh("skill"); F.q = c[1]; $("q").value = c[1];
        tabs(); facets(); load(true);
        $("catalogue").scrollIntoView({ block: "start" });
      });
      li.appendChild(b); ol.appendChild(li);
    });
  }

  /* kind tabs */
  function tabs() {
    var box = $("kinds"); box.textContent = "";
    KINDS.forEach(function (k) {
      var b = el("button", "kind caps");
      b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(k.kind === F.kind));
      b.appendChild(el("span", null, k.label));
      b.appendChild(el("span", "num dim", n(k.count)));
      b.addEventListener("click", function () {
        if (F.kind === k.kind) return;
        var q = F.q; F = fresh(k.kind); F.q = q;
        tabs(); facets(); load(true); governance();
      });
      box.appendChild(b);
    });
  }

  /* facets */
  function opt(parent, type, name, value, label, cnt, checked, onchange) {
    var lab = el("label", "opt"), i = el("input");
    i.type = type; i.name = name; i.value = value; i.checked = !!checked;
    i.addEventListener("change", function () { onchange(i); });
    lab.appendChild(i); lab.appendChild(el("span", null, label)); lab.appendChild(el("span", "dim num", cnt));
    parent.appendChild(lab);
  }
  function radios(fs, key, items) {
    var keep = fs.firstChild; fs.textContent = ""; fs.appendChild(keep);
    var name = "r-" + key + "-" + F.kind;
    opt(fs, "radio", name, "", "Any", "", !F[key], function (i) { F[key] = i.value; render(); });
    items.forEach(function (r) { opt(fs, "radio", name, r[0], r[1], r[2], F[key] === r[0], function (i) { F[key] = i.value; render(); }); });
  }
  function facets() {
    var kind = F.kind, v = (ST.verified || {})[kind] || 0, tot = count(kind);
    $("q").value = F.q;
    var sel = $("f-cat"), cats = (CATS[kind] || []).slice();
    var open = cats.filter(function (c) { return c.category !== "other" && c.category !== "general"; });
    var rest = cats.filter(function (c) { return c.category === "other" || c.category === "general"; });
    open.sort(function (a, b) { return b.count - a.count; });
    sel.textContent = "";
    var o0 = el("option", null, "All categories (" + n(cats.length) + ")"); o0.value = ""; sel.appendChild(o0);
    open.concat(rest).forEach(function (c) {
      var rest1 = c.category === "other" || c.category === "general";
      var o = el("option", null, c.label + (rest1 ? " (unclassified)" : "") + " — " + n(c.count)); o.value = c.category; sel.appendChild(o);
    });
    sel.value = F.cat;
    radios($("f-tr"), "tr", [["verified", "Verified", n(v)], ["quarantined", "Quarantined", n(tot - v)]]);
    var tiers = (ST.tiers || {}), tierBox = $("f-tier");
    tierBox.hidden = !(kind === "plugin" && Object.keys(tiers).length);
    if (!tierBox.hidden) radios(tierBox, "tier", ["Official", "Certified", "Community"].filter(function (t) { return tiers[t]; })
      .map(function (t) { return [t, t, n(tiers[t])]; }));
    var fl = (ST.flags || {})[kind] || {}, flBox = $("f-flag"), keys = Object.keys(fl).sort(function (a, b) { return fl[b] - fl[a]; });
    flBox.hidden = !keys.length || kind === "skill";
    var lg = flBox.firstChild; flBox.textContent = ""; flBox.appendChild(lg);
    keys.forEach(function (k) {
      opt(flBox, "checkbox", "hide", k, Hub.flagLabel(k), n(fl[k]), !!F.hide[k], function (i) { if (i.checked) F.hide[k] = 1; else delete F.hide[k]; render(); });
    });
    radios($("f-lic"), "lic", [["stated", "Stated", ""], ["none", "Not stated", ""]]);
    $("f-sort").value = F.sort;
    $("pending").textContent = "Not yet recorded: community review, freshness, unpinned dependencies, the never-promote scan" +
      (kind === "skill" ? ", risk flags for skills." : ".") + " Licence and risk filters apply to the records loaded so far.";
  }

  var tq;
  $("q").addEventListener("input", function (e) { clearTimeout(tq); tq = setTimeout(function () { F.q = e.target.value.trim(); load(true); }, 200); });
  $("f-cat").addEventListener("change", function (e) { F.cat = e.target.value; load(true); });
  $("f-sort").addEventListener("change", function (e) { F.sort = e.target.value; render(); });
  $("reset").addEventListener("click", function () { F = fresh(F.kind); facets(); load(true); });

  /* loading */
  function load(reset) {
    if (reset) { shownA = 8; rows = []; offset = 0; more = false; total = null; }
    var mine = ++seq;
    $("status").textContent = "Reading the index…";
    Hub.page({ kind: F.kind, q: F.q, category: F.cat, limit: F.kind === "connector" ? 100 : STEP, offset: offset }).then(function (res) {
      if (mine !== seq) return;
      rows = rows.concat(res.rows); offset += res.rows.length; more = res.more; total = res.total; offlineNow = res.offline;
      render();
    });
  }
  $("more").addEventListener("click", function () {
    if (aboveLeft > 0) { shownA += 24; render(); } else load(false);
  });

  /* what shows */
  function localMatch(r) {
    if (F.cat && r.category !== F.cat) return false;
    if (!F.q) return true;
    return (r.name + " " + r.title + " " + r.description + " " + r.author + " " + r.publisher).toLowerCase().indexOf(F.q.toLowerCase()) > -1;
  }
  function passes(r) {
    if (F.tr === "verified" && !r.verified) return false;
    if (F.tr === "quarantined" && r.verified) return false;
    if (F.tier && r.tier !== F.tier) return false;
    if (F.lic === "stated" && !r.license) return false;
    if (F.lic === "none" && r.license) return false;
    for (var k in F.hide) if (r.flags.indexOf(k) > -1) return false;
    return true;
  }
  function byName(a, b) { return a.title.localeCompare(b.title); }
  function row(r) {
    var li = el("li"), b = el("button", "row"), top = el("span", "top");
    b.type = "button";
    top.appendChild(el("span", "nm", r.title));
    var st = el("span", "st caps" + (r.verified ? "" : " dim"));
    if (r.verified) st.appendChild(crossSvg());
    st.appendChild(document.createTextNode(r.verified ? "Verified" : "Quarantined"));
    top.appendChild(st);
    if (r.tier) top.appendChild(el("span", "tier caps dim", "Tier: " + r.tier));
    b.appendChild(top);
    b.appendChild(el("span", "ds", r.description || "No description in the record."));
    var meta = [r.source.replace(/^axehub:/, ""), r.categoryLabel ? r.categoryLabel + (r.categorySource === "inferred" ? " · inferred" : "") : "", r.license || "licence unknown"];
    b.appendChild(el("span", "meta caps dim", meta.filter(Boolean).join(" · ")));
    if (r.flags.length) b.appendChild(el("span", "fl caps", "Risk flags recorded: " + r.flags.map(Hub.flagLabel).join(" · ")));
    b.addEventListener("click", function () { openRecord(r); });
    li.appendChild(b);
    return li;
  }
  function render() {
    var kind = F.kind;
    var vis = rows.filter(passes);
    var above = vis.filter(function (r) { return r.verified; });
    if (kind === "skill") {
      var have = {}; above.forEach(function (r) { have[r.name] = 1; });
      (ST.verified_records || []).map(Hub.norm).filter(function (r) { return r.verified && !have[r.name] && localMatch(r) && passes(r); })
        .forEach(function (r) { above.push(r); });
    }
    var below = vis.filter(function (r) { return !r.verified; });
    if (F.sort === "name") { above.sort(byName); below.sort(byName); }
    var A = $("above"), B = $("below");
    A.textContent = ""; B.textContent = "";
    aboveLeft = Math.max(0, above.length - shownA);
    above.slice(0, shownA).forEach(function (r) { A.appendChild(row(r)); });
    below.forEach(function (r) { B.appendChild(row(r)); });
    if (!above.length) A.appendChild(el("li", "empty caps", kind === "skill" ? "Nothing above the line for these filters." :
      "Nothing in " + LABEL[kind].toLowerCase() + " has crossed the line. Every " + ONE[kind] + " here is quarantined."));
    if (!below.length) B.appendChild(el("li", "empty caps", "Nothing below the line for these filters."));
    var st = $("status"); st.textContent = "";
    var msg = n(above.length) + " above the line · " + n(below.length) + " below · " + n(rows.length) + " loaded" +
      (total != null ? " of " + n(total) : more ? ", more available" : "");
    st.appendChild(el("span", "num", msg));
    if (offlineNow) st.appendChild(el("span", "off", "Live read failed. Showing the sample this page was rendered with."));
    $("more").hidden = !more && !aboveLeft;
    $("more").textContent = aboveLeft ? "Show " + n(Math.min(aboveLeft, 24)) + " more verified (" + n(aboveLeft) + " left)" : "Show more";
  }

  /* detail */
  var dlg = $("dlg"), lastFocus = null, current = "";
  function fact(dl, k, v) {
    dl.appendChild(el("dt", "caps", k));
    var dd = el("dd");
    if (v instanceof Node) dd.appendChild(v); else dd.textContent = Hub.clean(v);
    dl.appendChild(dd);
  }
  function paint(r) {
    var s = $("d-state"); s.textContent = "";
    s.appendChild(el("span", "rule"));
    if (r.verified) s.appendChild(crossSvg());
    s.appendChild(el("span", r.verified ? "" : "dim", r.verified ? "Verified · above the line" : "Below the line · quarantined on intake"));
    $("d-kind").textContent = r.kind.charAt(0).toUpperCase() + r.kind.slice(1) + " record";
    $("d-name").textContent = r.title;
    $("d-desc").textContent = r.description || "No description in the record.";
    $("d-install").textContent = Hub.recordLine(r.name);
    $("d-copy").hidden = !r.verified;
    $("d-line-t").textContent = r.verified ? "Install line" : "Record (read-only)";
    $("d-line-n").textContent = r.verified ? "" : "Reads the record as JSON. It does not install the entry or clear it from quarantine.";
    var dl = $("d-facts"); dl.textContent = "";
    fact(dl, "Trust", r.verified ? "Verified" : "Quarantined");
    if (r.defect) fact(dl, "Data note", "This record has both verified and quarantined set. That is a known import defect, not a review, so it is treated as quarantined.");
    if (r.withdrawn) fact(dl, "Upstream", "Withdrawn by its upstream index. Kept here, quarantined, for the record.");
    fact(dl, "Kind", r.kind.charAt(0).toUpperCase() + r.kind.slice(1));
    if (r.tier) fact(dl, "Publisher tier", r.tier + " (the upstream index's label, not our review)");
    fact(dl, "Source", r.source || "not recorded");
    if (r.author || r.publisher) fact(dl, r.kind === "skill" ? "Author" : "Publisher", r.author || r.publisher);
    fact(dl, "Category", (r.categoryLabel || "not recorded") + (r.categorySource ? " · " + r.categorySource : ""));
    fact(dl, "Version", (r.version || "not recorded") + (r.upstreamVersion && r.upstreamVersion !== r.version ? " · upstream " + r.upstreamVersion : ""));
    fact(dl, "Licence", r.license || "Unknown: none declared in the record");
    fact(dl, "Checksum", r.checksum ? "sha256 " + r.checksum : "not recorded");
    if (r.platforms.length) fact(dl, "Platforms", r.platforms.join(", "));
    if (r.env.length) fact(dl, "Env vars", r.env.join(", "));
    if (r.creds) fact(dl, "Credentials", Hub.credLabel(r.creds));
    if (r.kind !== "skill") fact(dl, "Risk flags", r.flags.length ? r.flags.map(Hub.flagLabel).join(" · ") : "none recorded");
    if (r.disclosure) fact(dl, "Disclosure", r.disclosure);
    if (r.upstreamInstall && r.upstreamInstall.command) fact(dl, "Upstream install", "Text only, from the upstream index, not run or endorsed here: " + r.upstreamInstall.command);
    fact(dl, "Freshness", "Not recorded");
    fact(dl, "Homepage", Hub.link(r.homepage));
    var t = $("d-trail"); t.textContent = "";
    t.appendChild(el("li", null, "Indexed from " + (r.source || "an unrecorded source") + "."));
    t.appendChild(el("li", null, r.checksum ? "Checksum recorded at intake: sha256 " + r.checksum.slice(0, 12) + "…" : "No checksum recorded."));
    if (r.verified) t.appendChild(el("li", null, "Promoted: marked verified and released from quarantine."));
    else {
      t.appendChild(el("li", null, "Quarantined on intake, the default for every record."));
      if (r.defect) t.appendChild(el("li", null, "Record carries a conflicting verified flag: a known import defect, not a review. Kept quarantined."));
    }
    t.appendChild(el("li", "dim", "Named reviewer sign-offs are not yet recorded in the index."));
  }
  function openRecord(r) {
    lastFocus = document.activeElement; current = r.name;
    paint(r);
    $("d-copy").textContent = "Copy";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    $("d-close").focus();
    Hub.detail(r.name).then(function (d) { if (d && current === r.name) paint(d); });
  }
  function close() { if (dlg.close) dlg.close(); else dlg.removeAttribute("open"); }
  $("d-close").addEventListener("click", close);
  dlg.addEventListener("click", function (e) { if (e.target === dlg) close(); });
  dlg.addEventListener("close", function () { current = ""; if (lastFocus) lastFocus.focus(); });
  $("d-copy").addEventListener("click", function () { Hub.copy($("d-install").textContent, $("d-copy"), "Copy"); });

  /* governance */
  function bars(ul, list) {
    ul.textContent = "";
    var max = Math.max.apply(null, list.map(function (r) { return r[1]; })) || 1;
    list.forEach(function (r) {
      var li = el("li");
      li.appendChild(el("span", "lbl", r[0]));
      var bar = el("span", "bar"), i = el("i");
      i.style.width = (r[1] / max * 100).toFixed(2) + "%";
      bar.appendChild(i); li.appendChild(bar);
      li.appendChild(el("span", "num dim", n(r[1])));
      ul.appendChild(li);
    });
  }
  var govDone = false;
  function governance() {
    if (!govDone) {
      govDone = true;
      var g = $("gov"), un = (CATS.skill || []).filter(function (c) { return c.category === "other" || c.category === "general"; })
        .reduce(function (a, c) { return a + c.count; }, 0);
      var tiers = ST.tiers || {}, tl = ["Official", "Certified", "Community"].filter(function (t) { return tiers[t]; })
        .map(function (t) { return t + " " + n(tiers[t]); }).join(" · ");
      var cf = (ST.flags || {}).connector || {};
      var lic = ST.licence || {};
      [
        [KINDS.map(function (k) { return k.label + " " + n(k.count); }).join(" · "), "Entries by kind"],
        [n(ST.defect || 0), "Rows with both verified and quarantined set: a data defect, kept quarantined"],
        [n(un), "Skills with no usable category; never shown as a category, search still finds them"],
        [n(ST.derived || 0), "Skill categories inferred by the catalogue, labelled as inferred"],
        [n(ST.withdrawn || 0), "Entries withdrawn by their upstream index, kept and quarantined"],
        [n(lic.skill || 0) + " / " + n(count("skill") - (lic.skill || 0)), "Skill licence stated / not stated"]
      ].concat(tl ? [[tl, "Plugin publisher tiers, as the upstream index states them"]] : [])
        .concat(Object.keys(cf).length ? [[Object.keys(cf).sort(function (a, b) { return cf[b] - cf[a]; })
          .map(function (k) { return Hub.flagLabel(k) + " " + n(cf[k]); }).join(" · "), "Connector risk flags recorded"]] : [])
        .forEach(function (x) {
          var d = el("div"); d.appendChild(el("dt", "caps dim", x[1])); d.appendChild(el("dd", "num", x[0])); g.appendChild(d);
        });
    }
    var rowsSrc = ((ST.sources || {})[F.kind] || []).map(function (s) { return [s[0].replace(/^axehub:/, ""), s[1]]; });
    var top = rowsSrc.slice(0, 7), rest = rowsSrc.slice(7).reduce(function (a, r) { return a + r[1]; }, 0);
    if (rest) top.push([(rowsSrc.length - 7) + " others", rest]);
    $("mix-t").textContent = "Source registry · " + LABEL[F.kind].toLowerCase();
    bars($("mix-src"), top);
  }

  Hub.theme("axe-theme", [$("theme")]);
  if (matchMedia("(max-width: 52rem)").matches) $("facets").removeAttribute("open");
  Promise.all([Hub.kinds(), Hub.stats(), Hub.categories("skill"), Hub.categories("plugin"), Hub.categories("connector")]).then(function (r) {
    KINDS = r[0]; ST = r[1]; CATS = { skill: r[2], plugin: r[3], connector: r[4] };
    hero(); tabs(); facets(); governance(); load(true);
  });
})();
