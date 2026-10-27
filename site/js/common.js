/* ATMosphere shared site script: config, preview banner, copy buttons, helpers. */
(function () {
  const cache = {};
  function loadJSON(path) {
    if (!cache[path]) cache[path] = fetch(path, { cache: "no-store" }).then(r => {
      if (!r.ok) throw new Error(path + " " + r.status);
      return r.json();
    });
    return cache[path];
  }
  const get = (obj, key) => key.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);

  // Tiny DOM builder. Text always goes in via textContent (Discord content is untrusted).
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
    return n;
  }
  const fmtDate = iso => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
  function timeAgo(iso) {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (isNaN(s)) return "";
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return fmtDate(iso);
  }
  // Split plain text into paragraphs.
  const paras = text => String(text || "").split(/\n{2,}/).map(p => el("p", { text: p.trim() })).filter(p => p.textContent);

  // Preview banner: only shown when the current page uses example/placeholder data.
  const reasons = new Set();
  function flag(reason) {
    reasons.add(reason);
    const b = document.getElementById("placeholder-banner");
    if (!b) return;
    b.textContent = "Preview · placeholder: " + [...reasons].join(", ");
    b.hidden = false;
  }

  function toast(btn, msg) { const old = btn.textContent; btn.textContent = msg; setTimeout(() => (btn.textContent = old), 1600); }
  function copyText(text, btn) {
    const done = () => btn && toast(btn, "Copied!");
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallback());
    else fallback();
    function fallback() {
      const t = el("textarea", { style: "position:fixed;opacity:0" }); t.value = text; document.body.append(t);
      t.select(); try { document.execCommand("copy"); done(); } catch (e) {} t.remove();
    }
  }

  const config = loadJSON("data/config.json").then(cfg => {
    document.querySelectorAll("[data-cfg-text]").forEach(n => { const v = get(cfg, n.dataset.cfgText); if (v != null) n.textContent = v; });
    document.querySelectorAll("[data-cfg-href]").forEach(n => { const v = get(cfg, n.dataset.cfgHref); if (v) n.href = v; });
    document.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", () => copyText(get(cfg, b.dataset.copy), b)));
    return cfg;
  }).catch(err => { console.error("config.json missing", err); return {}; });

  // Server status panel (Home). Reads data/status.json (written by the updater every ~15 min).
  function renderStatus(root) {
    const set = (sel, v) => { const n = root.querySelector(sel); if (n) n.textContent = v; };
    const lamp = root.querySelector(".lamp");
    const xp = root.querySelector(".xpbar > div");
    function unavailable() {
      lamp.className = "lamp off"; set("[data-st=state]", "Unknown");
      set("[data-st=players]", "–"); set("[data-st=max]", ""); xp.style.width = "0";
      set("[data-st=updated]", "Status unavailable. The live server status can't be loaded right now.");
    }
    loadJSON("data/status.json").then(s => {
      if (typeof s.online !== "boolean") return unavailable();
      if (s.example) { flag("server status"); root.querySelector("[data-st=tag]").hidden = false; }
      const ageMin = (Date.now() - new Date(s.updated_at).getTime()) / 60000;
      const stale = !(ageMin < 60); // the updater runs every 15 min; older than an hour = we don't really know
      lamp.className = "lamp" + (stale ? " off" : s.online ? "" : " down");
      set("[data-st=state]", stale ? "Unknown" : s.online ? "Online" : "Offline");
      const p = Number.isFinite(s.players) ? s.players : 0, m = Number.isFinite(s.max) ? s.max : 0;
      set("[data-st=players]", s.online && !stale ? String(p) : "–"); set("[data-st=max]", s.online && !stale && m ? "/ " + m : "");
      xp.style.width = s.online && !stale && m ? Math.min(100, (p / m) * 100) + "%" : "0";
      root.querySelector(".xpbar").title = s.online ? `${p} of ${m} players` : "";
      if (s.online && s.modpack && s.modpack.version) set("[data-st=version]", "ATM10 " + s.modpack.version);
      if (s.online && s.version) set("[data-st=mc]", s.version);
      const tick = () => set("[data-st=updated]", s.updated_at
        ? "Checked " + timeAgo(s.updated_at) + (stale ? " · the status check hasn't run for a while, so this may be out of date." : " · refreshed about every 15 minutes")
        : "");
      tick(); setInterval(tick, 60000);
    }).catch(unavailable);
  }

  // Announcement bodies are pre-rendered by the updater (escaped + basic Discord markdown).
  // Belt and braces: only a small allow-list of tags/attributes survives here.
  const ALLOWED = new Set(["P", "BR", "STRONG", "EM", "U", "S", "CODE", "PRE", "BLOCKQUOTE", "UL", "OL", "LI", "H3", "H4", "H5", "A", "SPAN", "SMALL"]);
  function safeHTML(htmlText) {
    const doc = new DOMParser().parseFromString("<div>" + (htmlText || "") + "</div>", "text/html");
    const frag = document.createDocumentFragment();
    (function walk(src, dst) {
      for (const n of [...src.childNodes]) {
        if (n.nodeType === 3) { dst.append(n.textContent); continue; }
        if (n.nodeType !== 1) continue;
        if (!ALLOWED.has(n.tagName)) { walk(n, dst); continue; }
        const c = document.createElement(n.tagName.toLowerCase());
        if (n.tagName === "A") {
          const href = n.getAttribute("href") || "";
          if (!/^https?:\/\//i.test(href)) { walk(n, dst); continue; }
          c.href = href; c.target = "_blank"; c.rel = "noopener noreferrer nofollow"; c.className = "link";
        }
        if (n.tagName === "OL" && /^\d+$/.test(n.getAttribute("start") || "")) c.setAttribute("start", n.getAttribute("start"));
        if (n.tagName === "SPAN" && n.classList.contains("spoiler")) { c.className = "spoiler"; c.title = "Spoiler: click to reveal"; c.addEventListener("click", () => c.classList.add("shown")); }
        walk(n, c); dst.append(c);
      }
    })(doc.body.firstChild, frag);
    return frag;
  }

  // Feed card used on Home (short) and Announcements (full).
  function postCard(item, opts) {
    const full = opts && opts.full;
    const meta = el("div", { class: full ? "post-meta" : "card-meta" },
      el("span", { class: "tag tag-cyan", text: item.source === "discord" || item.url ? "from Discord" : (item.source || "post") }),
      el("time", { datetime: item.date, text: fmtDate(item.date) }),
      full && item.author ? el("span", { text: "by " + item.author }) : null);
    const plain = String(item.text || "").replace(/\s+/g, " ").trim();
    if (!full) {
      return el("article", { class: "panel card" }, meta, el("h3", { text: item.title }),
        plain ? el("p", { text: plain.length > 150 ? plain.slice(0, 147).trimEnd() + "…" : plain }) : el("p", {}),
        el("a", { class: "link", href: "announcements.html#" + encodeURIComponent(item.id), text: "Read more ▸" }));
    }
    const body = el("div", { class: "body" });
    if (item.body != null) body.append(safeHTML(item.body)); else body.append(...paras(item.text));
    const imgs = (item.images || []).map(im => el("a", { href: im.src, target: "_blank", rel: "noopener", class: "post-img" },
      el("img", { src: im.src, alt: "Image attached to the announcement", loading: "lazy", width: im.width, height: im.height })));
    return el("article", { class: "panel post", id: item.id }, meta, el("h2", { text: item.title }), body,
      imgs.length ? el("div", { class: "post-imgs" }, imgs) : null,
      item.url ? el("div", { class: "post-foot" }, el("a", { class: "link", href: item.url, target: "_blank", rel: "noopener", text: "View on Discord ▸" })) : null);
  }
  function renderFeed(root, path, label, opts) {
    return loadJSON(path).then(data => {
      const items = (data.items || []).slice().sort((a, b) => new Date(b.date) - new Date(a.date));
      if (data.example) flag(label);
      root.replaceChildren();
      if (!items.length) { root.append(el("div", { class: "panel state-msg", text: "Nothing here yet. Check back soon!" })); return; }
      (opts && opts.limit ? items.slice(0, opts.limit) : items).forEach(i => root.append(postCard(i, opts)));
      if (location.hash) { const t = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (t) t.scrollIntoView(); }
    }).catch(() => root.replaceChildren(el("div", { class: "panel state-msg", text: "Couldn't load posts right now." })));
  }

  document.querySelectorAll("[data-year]").forEach(n => (n.textContent = new Date().getFullYear()));
  window.ATM = { loadJSON, config, el, fmtDate, timeAgo, flag, copyText, renderStatus, renderFeed, paras };
})();
