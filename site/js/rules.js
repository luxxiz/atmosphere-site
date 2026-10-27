ATM.config.then(cfg => {
  const root = document.getElementById("rules"), { el } = ATM;
  const rules = cfg.rules || [];
  if (cfg.rules_are_placeholder) ATM.flag("rules");
  root.replaceChildren(...rules.map((r, i) => el("li", { class: "panel rule" },
    el("span", { class: "mc-slot", text: String(i + 1) }),
    el("div", {}, el("h2", { text: r.title }), r.text ? el("p", { text: r.text }) : null))));
  if (!rules.length) root.append(el("li", { class: "panel state-msg", text: "Rules coming soon." }));
});
