(function () {
  const { el } = ATM;
  const grid = document.getElementById("mods-grid"), count = document.getElementById("mods-count");
  const palette = ["#1d6fd8", "#c2410c", "#0e7490", "#7c3aed", "#15803d", "#b45309", "#be123c", "#334155"];
  const initials = name => name.replace(/\[.*?\]|\(.*?\)/g, "").replace(/^Create:?\s*/i, "").split(/[\s:&'-]+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
  Promise.all([ATM.config, ATM.loadJSON("data/mods.json")]).then(([cfg, mods]) => {
    if (cfg.modpack && cfg.modpack.version_is_placeholder) ATM.flag("modpack version");
    const hidden = new Map((cfg.mods_hidden || []).map(h => [h.name, h.reason]));
    const notes = cfg.mod_notes || {}, noMr = cfg.mod_modrinth_hidden || {};
    const shown = mods.filter(m => !hidden.has(m.name));
    count.textContent = `${shown.length} extra mods`;
    grid.replaceChildren(...shown.map((m, i) => {
      const btns = [];
      if (m.curseforge_file_url) btns.push(el("a", { class: "mc-btn mc-btn-cf xs", href: m.curseforge_file_url, target: "_blank", rel: "noopener", text: "CurseForge ▸" }));
      if (m.modrinth_url && !noMr[m.name]) btns.push(el("a", { class: "mc-btn mc-btn-mr xs", href: m.modrinth_url, target: "_blank", rel: "noopener", text: "Modrinth ▸" }));
      return el("div", { class: "panel mod" },
        el("span", { class: "mod-icon", style: `background:${palette[i % palette.length]}`, text: initials(m.name), "aria-hidden": "true" }),
        el("div", {},
          el("h3", { text: m.name }),
          el("div", { class: "ver" }, "Version ", el("b", { text: m.version })),
          el("div", { class: "file", text: m.filename, title: "Exact file name" }),
          notes[m.name] ? el("div", { class: "note", text: notes[m.name] }) : null,
          el("div", { class: "btns" }, btns)));
    }));
  }).catch(() => { count.textContent = "Couldn't load the mod list right now. Ask in Discord!"; });
})();
