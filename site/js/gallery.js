(function () {
  const { el, fmtDate } = ATM, root = document.getElementById("gallery"), lb = document.getElementById("lightbox");
  let items = [], cur = 0, lastFocus = null;
  const credit = it => [it.credit ? "by " + it.credit : null, fmtDate(it.date)].filter(Boolean).join(" · ");
  const title = it => it.caption || it.title || "";
  function show(i) {
    cur = (i + items.length) % items.length; const it = items[cur], img = lb.querySelector("img");
    img.src = it.image; img.alt = title(it) || "Screenshot" + (it.credit ? " by " + it.credit : "");
    lb.querySelector("h3").textContent = title(it);
    lb.querySelector("p").textContent = credit(it);
    const link = lb.querySelector(".lb-link"); link.hidden = !it.url; if (it.url) link.href = it.url;
    lb.querySelector(".lb-count").textContent = `${cur + 1} / ${items.length}`;
  }
  function open(i) { lastFocus = document.activeElement; show(i); lb.hidden = false; document.body.style.overflow = "hidden"; lb.querySelector(".lb-close").focus(); }
  function close() { lb.hidden = true; document.body.style.overflow = ""; if (lastFocus) lastFocus.focus(); }
  lb.querySelector(".lb-close").onclick = close;
  lb.querySelector(".lb-prev").onclick = () => show(cur - 1);
  lb.querySelector(".lb-next").onclick = () => show(cur + 1);
  lb.addEventListener("click", e => { if (e.target === lb) close(); });
  document.addEventListener("keydown", e => {
    if (lb.hidden) return;
    if (e.key === "Escape") close(); else if (e.key === "ArrowLeft") show(cur - 1); else if (e.key === "ArrowRight") show(cur + 1);
  });
  ATM.loadJSON("data/gallery.json").then(data => {
    items = (data.items || []).slice().sort((a, b) => new Date(b.date) - new Date(a.date));
    if (data.example) ATM.flag("gallery pictures");
    root.replaceChildren(...items.map((it, i) => el("button", { type: "button", class: "panel shot", onclick: () => open(i) },
      el("img", { src: it.thumb || it.image, alt: title(it) || "Screenshot" + (it.credit ? " by " + it.credit : ""), loading: "lazy", width: 480, height: 270 }),
      el("div", { class: "cap" }, title(it) ? el("h3", { text: title(it) }) : null, el("p", { text: credit(it) })))));
    if (!items.length) root.append(el("div", { class: "panel state-msg", text: "No pictures yet. Post yours in our Discord #showcase channel!" }));
  }).catch(() => root.replaceChildren(el("div", { class: "panel state-msg", text: "Couldn't load the gallery right now." })));
})();
