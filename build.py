#!/usr/bin/env python3
"""Tiny static build: stitches src/partials + src/pages/*.html into site/*.html.
Each page starts with a JSON comment line: <!--{"title": "...", "page": "home", "scripts": ["js/home.js"]}-->
Run: python3 build.py"""
import json, pathlib, re
ROOT = pathlib.Path(__file__).parent
SRC, OUT = ROOT / "src", ROOT / "site"
P = {n: (SRC / "partials" / f"{n}.html").read_text() for n in ("head", "header", "footer")}
NAV = ["home", "join", "announcements", "rules", "gallery", "donate"]
for f in sorted((SRC / "pages").glob("*.html")):
    raw = f.read_text()
    m = re.match(r"<!--(\{.*?\})-->\n", raw, re.S)
    meta, body = json.loads(m.group(1)), raw[m.end():]
    v = {"title": meta["title"], "description": meta.get("description", "ATMosphere, an AllTheMods 10 community Minecraft server."),
         "page": meta["page"],
         "scripts": "\n".join(f'<script src="{s}"></script>' for s in meta.get("scripts", []))}
    for n in NAV:
        v[f"active_{n}"] = " active" if n == meta["page"] else ""
    html = P["head"] + P["header"] + body + P["footer"]
    html = re.sub(r"\{\{(\w+)\}\}", lambda x: v[x.group(1)], html)
    (OUT / f.name).write_text(html)
    print("built", f.name)
