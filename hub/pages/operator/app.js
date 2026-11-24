(function () {
  "use strict";
  var $ = Hub.$, el = Hub.el, n = Hub.n;
  var KLABEL = { skill: "Skills", plugin: "Plugins", connector: "Connectors" };

  /* the door: swap the model behind it */
  (function(){
    var models=[["Athena","serving since 23 Nov"],["Aurora","served main until 23 Nov"],["Kimi","standing by as candidate"]];
    var cards=document.querySelectorAll('.door .card');
    var out=document.getElementById('now');
    var i=0;
    document.getElementById('swap').addEventListener('click',function(){
      var prev=cards[i];
      i=(i+1)%models.length;
      var next=cards[i];
      cards.forEach(function(c){c.classList.remove('off')});
      prev.classList.remove('on');prev.classList.add('off');
      next.classList.add('on');
      setTimeout(function(){prev.classList.add('park');prev.classList.remove('off');void prev.offsetWidth;prev.classList.remove('park')},400);
      out.textContent=models[i][0]+', '+models[i][1];
    });
  })();

  /* the marketplace: live counts, a live list, nothing runnable */
  var KINDS = [], ST = { verified: {}, tiers: {} }, kind = "skill", seq = 0, q = "";
  function count(k) { var x = KINDS.filter(function (y) { return y.kind === k; })[0]; return x ? x.count : 0; }
  function tabs() {
    var box = $("mkt-tabs"); box.textContent = "";
    KINDS.forEach(function (k) {
      var b = el("button", "mtab"); b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(k.kind === kind));
      b.appendChild(el("span", null, k.label)); b.appendChild(el("span", "mc", n(k.count)));
      b.addEventListener("click", function () { kind = k.kind; tabs(); load(); });
      box.appendChild(b);
    });
  }
  function lede() {
    var tot = KINDS.reduce(function (a, k) { return a + k.count; }, 0);
    var v = Object.keys(ST.verified || {}).reduce(function (a, k) { return a + ST.verified[k]; }, 0);
    $("mkt-lede").textContent = "Read live from the catalogue Operator searches: " + n(tot) + " entries, " + n(v) + " verified, " + n(tot - v) + " quarantined. A quarantined entry is held for review and is not offered for install.";
  }
  function item(r) {
    var li = el("li", "mi"), top = el("div", "mtop");
    top.appendChild(el("span", "mn", r.title));
    top.appendChild(el("span", "state " + (r.verified ? "live" : "down"), r.verified ? "Verified" : "Quarantined"));
    li.appendChild(top);
    li.appendChild(el("p", "md", r.description || "No description in the record."));
    var meta = [r.kind, r.tier ? "Tier: " + r.tier : "", r.source.replace(/^axehub:/, ""), r.license || "licence unknown"].filter(Boolean).join(" \u00b7 ");
    li.appendChild(el("p", "mm label", meta));
    if (r.flags.length) li.appendChild(el("p", "mm label", "Risk flags recorded: " + r.flags.map(Hub.flagLabel).join(" \u00b7 ")));
    var a = el("a", "ml", "Open in Barracks"); a.href = "https://barracks.0perator.co/#/skill/" + encodeURIComponent(r.name);
    li.appendChild(a);
    return li;
  }
  function load() {
    var mine = ++seq, ul = $("mkt-list"), st = $("mkt-status");
    st.textContent = "Reading the catalogue\u2026";
    var first = kind === "skill" && !q ? (ST.verified_records || []).map(Hub.norm).filter(function (r) { return r.verified; }).slice(0, 3) : [];
    Hub.page({ kind: kind, q: q, limit: 8 }).then(function (res) {
      if (mine !== seq) return;
      var have = {}; first.forEach(function (r) { have[r.name] = 1; });
      var list = first.concat(res.rows.filter(function (r) { return !have[r.name]; })).slice(0, 8);
      ul.textContent = "";
      list.forEach(function (r) { ul.appendChild(item(r)); });
      st.textContent = list.length ? "Showing " + n(list.length) + " of " + n(count(kind)) + " " + KLABEL[kind].toLowerCase() + (q ? " matching \u201c" + Hub.clean(q) + "\u201d" : "") + "." + (res.offline ? " Live read failed: this is the sample the page was served with." : "")
        : "Nothing matches that search.";
    });
  }
  var tm;
  $("mkt-q").addEventListener("input", function (e) { clearTimeout(tm); tm = setTimeout(function () { q = e.target.value; load(); }, 200); });
  $("mkt-form").addEventListener("submit", function (e) { e.preventDefault(); });
  Promise.all([Hub.kinds(), Hub.stats()]).then(function (r) { KINDS = r[0]; ST = r[1]; tabs(); lede(); load(); });
})();
