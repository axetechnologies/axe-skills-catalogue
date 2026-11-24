/* Shared data layer for the three host pages. Same-origin, read-only, and every string it returns is untrusted:
   callers write it with textContent (Hub.el) and never as markup. */
(function (w) {
  "use strict";
  var Hub = w.Hub = {};
  var doc = w.document;

  Hub.fmt = new Intl.NumberFormat("en-CA");
  Hub.n = function (x) { return Hub.fmt.format(x || 0); };
  Hub.$ = function (id) { return doc.getElementById(id); };
  var PICT = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu;
  Hub.clean = function (s) { return String(s == null ? "" : s).replace(PICT, ""); };
  Hub.el = function (tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = Hub.clean(text);
    return e;
  };
  Hub.svg = function (tag, attrs) {
    var e = doc.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  Hub.link = function (url, text) {
    var s = String(url || "");
    if (!/^https:\/\/[^\s]+$/.test(s)) return doc.createTextNode(Hub.clean(s || "none"));
    var a = Hub.el("a", null, text || s);
    a.href = s; a.rel = "noopener noreferrer nofollow"; a.target = "_blank";
    return a;
  };

  /* what the server embedded when it rendered the page: true figures, used only when a live call fails */
  var FB = {};
  try { FB = JSON.parse(doc.getElementById("hub-fallback").textContent) || {}; } catch (e) { FB = {}; }
  Hub.fallback = FB;
  Hub.offline = false;

  Hub.get = function (path) {
    var ctl = w.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 9000) : 0;
    return fetch(path, { credentials: "omit", headers: { Accept: "application/json" }, signal: ctl ? ctl.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (j) { clearTimeout(timer); return j; }, function (e) { clearTimeout(timer); throw e; });
  };
  function enc(o) {
    var out = [];
    for (var k in o) if (o[k] !== "" && o[k] != null) out.push(encodeURIComponent(k) + "=" + encodeURIComponent(o[k]));
    return out.join("&");
  }
  function down(e) { Hub.offline = true; return e; }

  Hub.kinds = function () {
    return Hub.get("/v1/kinds").then(function (j) { return j.kinds; }, function () {
      down(); return FB.kinds || [];
    });
  };
  Hub.stats = function () {
    return Hub.get("/assets/stats.json").then(function (j) { return j; }, function () {
      down();
      var s = FB.stats || {};
      s.verified_records = FB.verified || [];
      return s;
    });
  };
  Hub.categories = function (kind) {
    return Hub.get("/v1/categories?" + enc({ kind: kind })).then(function (j) { return j.categories; }, function () {
      down(); return (FB.categories || {})[kind] || [];
    });
  };

  /* a model any page can read, from an API record or an embedded one */
  var FLAGS = {
    intercepts_agent_calls: "Intercepts agent calls", desktop_renderer_full_authority: "Desktop renderer, full authority",
    third_party_egress: "Sends data to a third party", shell_exec: "Runs shell commands", money_movement: "Moves money",
    broad_system_access: "Broad system access", telemetry_default_on: "Telemetry on by default",
    guardrail_bypass: "Bypasses guardrails", shell_piped_install: "Piped shell install",
    prompt_injection_text: "Prompt-injection text", write_access: "Can write", scope_undisclosed: "Scope not disclosed"
  };
  Hub.flagLabel = function (f) { return FLAGS[f] || String(f).replace(/_/g, " "); };
  var CREDS = { "none-stated": "None stated", mentioned: "Mentioned in the text", declared: "Declared as environment variables" };
  Hub.credLabel = function (c) {
    if (!c) return "";
    if (CREDS[c]) return CREDS[c];
    return /oauth/i.test(c) ? "Account sign-in (OAuth)" : String(c);
  };

  Hub.norm = function (rec) {
    var c = rec.card || {}, m = rec.metadata || {}, t = m.taxonomy || {};
    var flagged = c.verified === true || m.verified === true;
    var defect = flagged && m.quarantined === true;
    var title = c.title || String(rec.name || "").split("__").pop();
    var cs = c.category_source || "";
    return {
      name: rec.name, title: title, kind: c.kind || m.kind || "skill",
      description: c.description || t.description || "",
      source: c.source || m.source || "", author: c.author || m.author || "", publisher: c.publisher || m.publisher || "",
      license: c.license || m.license || t.license || "", version: rec.version || "",
      upstreamVersion: c.upstream_version || m.upstream_version || "",
      category: c.category || t.category || "", categoryLabel: c.category_label || t.category_label || "",
      categorySource: cs === "derived" ? "inferred" : cs,
      verified: flagged && !defect, defect: defect,
      tier: c.trust_tier || m.trust_tier || "",
      flags: c.risk_flags || m.risk_flags || [], creds: c.credentials_needed || m.credentials_needed || "",
      disclosure: c.disclosure || m.disclosure || "", homepage: c.homepage || m.homepage || "",
      upstreamInstall: c.upstream_install || null, checksum: rec.checksum || "",
      withdrawn: m.upstream_status === "withdrawn", platforms: c.platforms || m.platforms || [],
      env: c.env_vars || [], created: rec.created_at || ""
    };
  };
  Hub.trust = function (r) { return r.verified ? "verified" : "quarantined"; };
  Hub.recordUrl = function (name) { return w.location.origin + "/v1/skills/" + encodeURIComponent(name); };
  Hub.recordLine = function (name) { return "curl -s " + Hub.recordUrl(name); };

  function match(r, q, category) {
    if (category && r.category !== category) return false;
    if (!q) return true;
    return (r.name + " " + r.title + " " + r.description + " " + r.author + " " + r.publisher + " " + r.source).toLowerCase().indexOf(q.toLowerCase()) > -1;
  }
  /* one page of one kind. Resolves { rows, total (null when the server cannot say), more, offline } */
  Hub.page = function (o) {
    var limit = o.limit || 24, offset = o.offset || 0, q = (o.q || "").trim();
    var req = q
      ? Hub.get("/v1/skills/search?" + enc({ q: q, kind: o.kind, limit: limit, offset: offset })).then(function (j) {
          return { rows: j.map(Hub.norm), total: null, more: j.length === limit };
        })
      : Hub.get("/v1/skills?" + enc({ kind: o.kind, limit: limit, offset: offset, category: o.category, envelope: 1 })).then(function (j) {
          return { rows: j.data.map(Hub.norm), total: j.total, more: !!j.has_more };
        });
    return req.then(function (r) { r.offline = false; return r; }, function () {
      down();
      var all = ((FB.sample || {})[o.kind] || []).concat(o.kind === "skill" ? FB.verified || [] : []).map(Hub.norm)
        .filter(function (r) { return match(r, q, o.category); });
      return { rows: all.slice(offset, offset + limit), total: all.length, more: offset + limit < all.length, offline: true };
    });
  };
  Hub.detail = function (name) {
    return Hub.get("/v1/skills/" + encodeURIComponent(name)).then(Hub.norm, function () { return null; });
  };

  Hub.copy = function (text, btn, idle) {
    var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = idle; }, 1600); };
    try { w.navigator.clipboard.writeText(text).then(done, function () { btn.textContent = "Select and copy"; }); }
    catch (e) { btn.textContent = "Select and copy"; }
  };

  Hub.theme = function (key, buttons, onChange) {
    var root = doc.documentElement;
    try { var saved = w.localStorage.getItem(key); if (saved) root.setAttribute("data-theme", saved); } catch (e) { /* storage may be blocked */ }
    function dark() {
      var t = root.getAttribute("data-theme");
      return t ? t === "dark" : !!(w.matchMedia && w.matchMedia("(prefers-color-scheme: dark)").matches);
    }
    function label() { buttons.forEach(function (b) { b.textContent = dark() ? "Light" : "Dark"; }); if (onChange) onChange(); }
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        var next = dark() ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { w.localStorage.setItem(key, next); } catch (e) { /* storage may be blocked */ }
        label();
      });
    });
    label();
  };

  /* apply a stored theme before first paint */
  try { var s0 = w.localStorage.getItem(doc.documentElement.getAttribute("data-theme-key") || ""); if (s0) doc.documentElement.setAttribute("data-theme", s0); } catch (e) { /* ignore */ }
})(window);
