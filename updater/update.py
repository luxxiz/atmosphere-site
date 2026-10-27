#!/usr/bin/env python3
"""ATMosphere site updater (read-only).

Pulls #announcements and #showcase from Discord (REST API v10, GET requests only),
pings the Minecraft server with the Server List Ping protocol, and writes:

  site/data/announcements.json
  site/data/gallery.json      (+ images downloaded into site/media/gallery/)
  site/data/status.json

It never posts, edits or deletes anything on Discord. Files are only written when
their content changed. Any single step may fail; the others still run and the old
file is kept. Exit code is 0 unless the script itself is broken.

Environment:
  ATMOSPHERE_DISCORD_BOT_TOKEN           required for the Discord parts (secret, never logged)
  ATMOSPHERE_ANNOUNCEMENTS_CHANNEL_ID    optional, overrides updater/config.json
  ATMOSPHERE_SHOWCASE_CHANNEL_ID         optional, overrides updater/config.json
  ATMOSPHERE_MC_HOST / ATMOSPHERE_MC_PORT optional, overrides updater/config.json
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import io
import json
import logging
import os
import pathlib
import re
import socket
import struct
import sys
import time

import requests

try:
    from PIL import Image, ImageOps
except ImportError:  # gallery still works without thumbnails being regenerated? No: we need Pillow.
    Image = None

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SITE = ROOT / "site"
DATA = SITE / "data"
MEDIA = SITE / "media"
API = "https://discord.com/api/v10"
UA = "DiscordBot (https://github.com/, 1.0) ATMosphere-site-updater"

# ---------------------------------------------------------------- logging ---
TOKEN = os.environ.get("ATMOSPHERE_DISCORD_BOT_TOKEN", "").strip()


class Redact(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if TOKEN and TOKEN in msg:
            record.msg, record.args = msg.replace(TOKEN, "***"), ()
        return True


log = logging.getLogger("updater")
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
_h.addFilter(Redact())
log.addHandler(_h)
log.setLevel(logging.INFO)
problems: list[str] = []


def problem(msg: str):
    problems.append(msg)
    log.warning(msg)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{msg}".replace(TOKEN, "***") if TOKEN else f"::warning::{msg}")


# ----------------------------------------------------------------- config ---
def load_config() -> dict:
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    env = {
        "announcements_channel_id": "ATMOSPHERE_ANNOUNCEMENTS_CHANNEL_ID",
        "showcase_channel_id": "ATMOSPHERE_SHOWCASE_CHANNEL_ID",
        "minecraft_host": "ATMOSPHERE_MC_HOST",
        "minecraft_port": "ATMOSPHERE_MC_PORT",
    }
    for key, var in env.items():
        if os.environ.get(var, "").strip():
            cfg[key] = os.environ[var].strip()
    cfg["minecraft_port"] = int(cfg["minecraft_port"])
    return cfg


# ------------------------------------------------------------ file output ---
def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_if_changed(path: pathlib.Path, obj) -> bool:
    new = dump(obj)
    if path.exists() and path.read_text(encoding="utf-8") == new:
        log.info("%s unchanged", path.relative_to(ROOT))
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(path)
    log.info("wrote %s", path.relative_to(ROOT))
    return True


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- Discord ---
class Discord:
    """Minimal read-only Discord REST client. Only ever sends GET requests."""

    def __init__(self, token: str):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bot {token}", "User-Agent": UA})
        self.members: dict[str, str] = {}
        self.roles: dict[str, str] = {}
        self.channels: dict[str, str] = {}
        self.guild_id: str | None = None

    def get(self, path: str, **params):
        for attempt in range(4):
            r = self.s.get(API + path, params=params, timeout=15)
            if r.status_code == 429:
                wait = float(r.json().get("retry_after", 1)) + 0.2
                log.info("rate limited, waiting %.1fs", wait)
                time.sleep(wait)
                continue
            if r.status_code >= 500 and attempt < 3:
                time.sleep(1 + attempt)
                continue
            if not r.ok:
                raise RuntimeError(f"GET {path} -> HTTP {r.status_code}")
            return r.json()
        raise RuntimeError(f"GET {path} -> still rate limited")

    def messages(self, channel_id: str, max_messages: int, stop=None):
        out, before = [], None
        while len(out) < max_messages:
            params = {"limit": min(100, max_messages - len(out))}
            if before:
                params["before"] = before
            batch = self.get(f"/channels/{channel_id}/messages", **params)
            if not batch:
                break
            out.extend(batch)
            before = batch[-1]["id"]
            if stop and stop(out):
                break
            if len(batch) < params["limit"]:
                break
        return out

    def load_guild(self, channel_id: str):
        if self.guild_id:
            return
        ch = self.get(f"/channels/{channel_id}")
        self.guild_id = ch.get("guild_id")
        if not self.guild_id:
            return
        try:
            self.roles = {r["id"]: r["name"] for r in self.get(f"/guilds/{self.guild_id}/roles")}
        except Exception as e:  # noqa: BLE001
            problem(f"could not load roles: {e}")
        try:
            self.channels = {c["id"]: clean_channel_name(c.get("name", "")) for c in self.get(f"/guilds/{self.guild_id}/channels")}
        except Exception as e:  # noqa: BLE001
            problem(f"could not load channels: {e}")

    def display_name(self, user: dict) -> str:
        uid = user.get("id", "")
        if uid not in self.members:
            name = user.get("global_name") or user.get("username") or "Unknown"
            if self.guild_id and uid:
                try:
                    m = self.get(f"/guilds/{self.guild_id}/members/{uid}")
                    name = m.get("nick") or (m.get("user") or {}).get("global_name") or name
                except Exception:  # left the server etc.
                    pass
            self.members[uid] = name
        return self.members[uid]


def clean_channel_name(name: str) -> str:
    return re.sub(r"[⌈⌋⌊⌉「」『』|]", "", name).strip()


def msg_link(guild_id, channel_id, message_id) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


# ---------------------------------------------------- Discord markdown -> HTML ---
URL_RE = re.compile(r"https?://[^\s<>\"'\]\)]+[^\s<>\"'\]\).,;:!?]")


def resolve_tokens(text: str, msg: dict, dc: Discord) -> str:
    """Replace Discord mention/emoji/timestamp tokens with plain text (before escaping)."""
    users = {u["id"]: u for u in msg.get("mentions", [])}

    def user(m):
        u = users.get(m.group(1))
        return "@" + (dc.display_name(u) if u else "someone")

    text = re.sub(r"<@!?(\d+)>", user, text)
    text = re.sub(r"<@&(\d+)>", lambda m: "@" + dc.roles.get(m.group(1), "role"), text)
    text = re.sub(r"<#(\d+)>", lambda m: "#" + dc.channels.get(m.group(1), "channel"), text)
    text = re.sub(r"</([\w -]+):\d+>", r"/\1", text)  # slash command mentions
    text = re.sub(r"<a?:\w+:\d+>", "", text)  # custom emoji: drop
    text = re.sub(r"<t:(-?\d+)(?::\w)?>", lambda m: dt.datetime.fromtimestamp(int(m.group(1)), dt.timezone.utc).strftime("%d %b %Y %H:%M UTC"), text)
    text = re.sub(r"@(everyone|here)\b[ \t]*", "", text)  # pings are noise on a website
    return text


def strip_md(text: str) -> str:
    """Plain text version: drop markdown markers, keep the words."""
    t = re.sub(r"```[\w+-]*\n?(.*?)```", r"\1", text, flags=re.S)
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"\1", t)
    t = re.sub(r"<(https?://[^>\s]+)>", r"\1", t)
    t = re.sub(r"(?m)^\s*(?:#{1,3}|-#|>{1,3})\s+", "", t)
    t = re.sub(r"\*\*|__|~~|\|\||`", "", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])", r"\1", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def inline(raw: str) -> str:
    """Escape one block of text and convert inline Discord markdown. Output is safe HTML."""
    slots: list[str] = []

    def keep(fragment: str) -> str:
        slots.append(fragment)
        return f"\x00{len(slots) - 1}\x00"

    def link(url: str, label: str | None = None) -> str:
        url = url.strip()
        if not re.match(r"^https?://", url, re.I):
            return html.escape(label or url)
        return keep(f'<a href="{html.escape(url, quote=True)}">{html.escape(label or url)}</a>')

    s = raw.replace("\x00", "")
    s = re.sub(r"`([^`\n]+)`", lambda m: keep("<code>" + html.escape(m.group(1)) + "</code>"), s)
    s = re.sub(r"\[([^\]\n]+)\]\(<?(https?://[^)\s>]+)>?\)", lambda m: link(m.group(2), m.group(1)), s)
    s = re.sub(r"<(https?://[^>\s]+)>", lambda m: link(m.group(1)), s)
    s = URL_RE.sub(lambda m: link(m.group(0)), s)
    s = html.escape(s, quote=False)
    for pat, tag in ((r"\*\*(.+?)\*\*", "strong"), (r"__(.+?)__", "u"), (r"~~(.+?)~~", "s")):
        s = re.sub(pat, lambda m, t=tag: f"<{t}>{m.group(1)}</{t}>", s, flags=re.S)
    s = re.sub(r"\|\|(.+?)\|\|", r'<span class="spoiler">\1</span>', s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w])_(?!\s)([^_\n]+?)_(?![\w])", r"<em>\1</em>", s)
    s = s.replace("**", "").replace("||", "")  # unmatched leftovers
    s = re.sub(r"(?<!\w)__|__(?!\w)", "", s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], s)
    return s.strip()


def md_to_html(text: str) -> str:
    """Line-based renderer for the Discord markdown subset. Every piece of user text goes
    through html.escape, so the result is safe to insert as HTML."""
    out: list[str] = []
    para: list[str] = []
    lst: tuple[str, list[str], int] | None = None  # (tag, items, start)
    quote: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + "<br>".join(inline(l) for l in para) + "</p>")
            para = []

    def flush_list():
        nonlocal lst
        if lst:
            tag, items, start = lst
            attr = f' start="{start}"' if tag == "ol" and start != 1 else ""
            out.append(f"<{tag}{attr}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
            lst = None

    def flush_quote():
        nonlocal quote
        if quote:
            out.append("<blockquote>" + "<br>".join(inline(l) for l in quote) + "</blockquote>")
            quote = []

    def flush_all():
        flush_para(); flush_list(); flush_quote()

    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        st = line.strip()
        if st.startswith("```"):
            flush_all()
            body, rest = [], st[3:]
            if rest.endswith("```") and len(rest) >= 3:
                body.append(rest[:-3])
            else:
                i += 1
                while i < len(lines) and not lines[i].strip().endswith("```"):
                    body.append(lines[i]); i += 1
                if i < len(lines):
                    body.append(lines[i].rstrip()[:-3])
            out.append("<pre><code>" + html.escape("\n".join(body).strip("\n")) + "</code></pre>")
            i += 1
            continue
        if not st:
            # a blank line ends paragraphs/quotes; lists continue if the next real line is the same kind
            flush_para(); flush_quote()
            if lst:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                nxt = lines[j].strip() if j < len(lines) else ""
                same = (lst[0] == "ul" and re.match(r"^[-*•]\s+", nxt)) or (lst[0] == "ol" and re.match(r"^\d+[.)]\s+", nxt))
                if not same:
                    flush_list()
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", st)
        if m:
            flush_all()
            lvl = len(m.group(1)) + 2
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif re.match(r"^-#\s+", st):
            flush_all()
            out.append("<p><small>" + inline(re.sub(r"^-#\s+", "", st)) + "</small></p>")
        elif re.match(r"^>{1,3}\s?", st):
            flush_para(); flush_list()
            quote.append(re.sub(r"^>{1,3}\s?", "", st))
        elif re.match(r"^[-*•]\s+", st):
            flush_para(); flush_quote()
            if not lst or lst[0] != "ul":
                flush_list(); lst = ("ul", [], 1)
            lst[1].append(re.sub(r"^[-*•]\s+", "", st))
        elif re.match(r"^\d+[.)]\s+", st):
            flush_para(); flush_quote()
            n = int(re.match(r"^(\d+)", st).group(1))
            if not lst or lst[0] != "ol":
                flush_list(); lst = ("ol", [], n)
            lst[1].append(re.sub(r"^\d+[.)]\s+", "", st))
        else:
            flush_list(); flush_quote()
            para.append(st)
        i += 1
    flush_all()
    return "".join(o for o in out if o not in ("<p></p>",))


def split_title(text: str) -> tuple[str, str]:
    """First meaningful line becomes the title (markdown stripped); the rest is the body."""
    lines = text.strip("\n").split("\n")
    for idx, line in enumerate(lines):
        plain = strip_md(re.sub(r"^\s*#{1,3}\s+", "", line))
        if len(re.findall(r"[^\W_]", plain)) >= 2:
            title = re.sub(r"\s{2,}", " ", plain).strip()
            if len(title) > 120:
                title = title[:117].rstrip() + "…"
                return title, "\n".join(lines[idx:]).strip()
            return title, "\n".join(lines[idx + 1:]).strip()
    return "", text.strip()


# ---------------------------------------------------------------- images ---
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")


def message_images(msg: dict, skip_jpeg: bool = False) -> list[dict]:
    """Image attachments + image embeds. Videos/gifv and spoilered files are skipped.
    skip_jpeg: Minecraft screenshots are PNG; JPEGs in #showcase are phone/camera photos
    (holidays, food, desk setups), which we keep off the public gallery."""
    found = []
    for a in msg.get("attachments", []):
        ctype = (a.get("content_type") or "").split(";")[0]
        name = a.get("filename", "")
        if ctype not in IMAGE_TYPES and not re.search(r"\.(png|jpe?g|webp|gif)$", name, re.I):
            continue
        if name.upper().startswith("SPOILER_"):
            continue
        if skip_jpeg and (ctype == "image/jpeg" or re.search(r"\.jpe?g$", name, re.I)):
            continue
        found.append({"key": "a" + a["id"], "url": a.get("url") or a.get("proxy_url"), "size": a.get("size", 0),
                      "w": a.get("width"), "h": a.get("height")})
    for e in msg.get("embeds", []):
        if e.get("type") != "image" or (skip_jpeg and re.search(r"\.jpe?g(\?|$)", e.get("url", ""), re.I)):
            continue
        src = (e.get("image") or e.get("thumbnail") or {})
        url = src.get("proxy_url") or src.get("url") or e.get("url")
        if url:
            found.append({"key": "e" + hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16], "url": url, "size": 0,
                          "w": src.get("width"), "h": src.get("height")})
    return found


def fetch_image(session: requests.Session, img: dict, folder: pathlib.Path, prefix: str, cfg: dict, thumb=True):
    """Download once (keyed by attachment id), store as re-encoded WebP (strips EXIF/GPS)."""
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{prefix}-{img['key']}"
    full, small = folder / f"{base}.webp", folder / f"{base}-thumb.webp"
    if full.exists() and (small.exists() or not thumb):
        with Image.open(full) as im:
            size = im.size
        return full, (small if thumb else None), size
    if img["size"] and img["size"] > cfg["max_image_bytes"]:
        raise RuntimeError(f"image too big ({img['size']} bytes)")
    r = session.get(img["url"], timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    if len(r.content) > cfg["max_image_bytes"]:
        raise RuntimeError("image too big")
    with Image.open(io.BytesIO(r.content)) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        w = cfg["full_image_max_width"]
        if im.width > w:
            im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        im.save(full, "WEBP", quality=82, method=5)
        size = im.size
        if thumb:
            ImageOps.fit(im.convert("RGB"), tuple(cfg["thumb_size"]), Image.LANCZOS).save(small, "WEBP", quality=78, method=5)
    return full, (small if thumb else None), size


def rel(p: pathlib.Path | None) -> str | None:
    return p.relative_to(SITE).as_posix() if p else None


def usable(msg: dict) -> bool:
    if msg.get("type") not in (0, 19):  # default + reply; skip pins, joins, boosts, thread notices...
        return False
    if (msg.get("author") or {}).get("bot"):
        return False
    return True


# ---------------------------------------------------------- announcements ---
def update_announcements(dc: Discord, cfg: dict) -> None:
    cid = cfg["announcements_channel_id"]
    dc.load_guild(cid)
    msgs = dc.messages(cid, cfg["announcements_limit"] + 20)
    items, media_used = [], set()
    folder = MEDIA / "announcements"
    for m in msgs:
        if not usable(m):
            continue
        text = resolve_tokens(m.get("content", ""), m, dc).strip()
        imgs = message_images(m)
        if not text and not imgs:
            continue
        title, rest = split_title(text)
        images = []
        for img in imgs:
            try:
                full, _, size = fetch_image(dc.s, img, folder, "ann", cfg, thumb=False)
                media_used.add(full.name)
                images.append({"src": rel(full), "width": size[0], "height": size[1]})
            except Exception as e:  # noqa: BLE001
                problem(f"announcement {m['id']}: image skipped ({e})")
        if not title and not rest and not images:
            continue
        excerpt = strip_md(rest)
        items.append({
            "id": "a" + m["id"],
            "title": title or "Announcement",
            "body": md_to_html(rest),
            "text": excerpt[:400],
            "date": m["timestamp"],
            "edited": m.get("edited_timestamp"),
            "author": dc.display_name(m["author"]),
            "url": msg_link(dc.guild_id, cid, m["id"]),
            "images": images,
        })
        if len(items) >= cfg["announcements_limit"]:
            break
    out = {"_readme": "Written automatically by updater/update.py from the Discord #announcements channel. Do not edit by hand.",
           "source": "discord", "items": items}
    write_if_changed(DATA / "announcements.json", out)
    prune(folder, media_used)
    log.info("announcements: %d items, %d images", len(items), len(media_used))


# ---------------------------------------------------------------- gallery ---
def update_gallery(dc: Discord, cfg: dict) -> None:
    cid = cfg["showcase_channel_id"]
    dc.load_guild(cid)
    limit = cfg["gallery_image_limit"]
    skip_jpeg = bool(cfg.get("gallery_skip_jpeg", True))
    excluded = set(map(str, cfg.get("gallery_exclude_message_ids", [])))
    count = lambda ms: sum(len(message_images(x, skip_jpeg)) for x in ms if usable(x))  # noqa: E731
    msgs = dc.messages(cid, cfg["gallery_max_messages"], stop=lambda ms: count(ms) >= limit)
    folder = MEDIA / "gallery"
    items, used, videos, photos = [], set(), 0, 0
    for m in msgs:
        if not usable(m) or m["id"] in excluded:
            continue
        videos += sum(1 for a in m.get("attachments", []) if (a.get("content_type") or "").startswith("video/"))
        photos += len(message_images(m)) - len(message_images(m, skip_jpeg))
        imgs = message_images(m, skip_jpeg)
        if not imgs:
            continue
        caption = strip_md(resolve_tokens(m.get("content", ""), m, dc))
        caption = URL_RE.sub("", caption).strip()
        credit = dc.display_name(m["author"])
        for n, img in enumerate(imgs):
            if len(items) >= limit:
                break
            try:
                full, small, size = fetch_image(dc.s, img, folder, "g", cfg)
            except Exception as e:  # noqa: BLE001
                problem(f"showcase {m['id']}: image skipped ({e})")
                continue
            used.update({full.name, small.name})
            items.append({
                "id": f"g{m['id']}-{n}",
                "image": rel(full), "thumb": rel(small), "width": size[0], "height": size[1],
                "credit": credit, "caption": caption[:300], "date": m["timestamp"],
                "url": msg_link(dc.guild_id, cid, m["id"]),
            })
        if len(items) >= limit:
            break
    out = {"_readme": "Written automatically by updater/update.py from the Discord #showcase channel. Images are copies in site/media/gallery/. Do not edit by hand.",
           "source": "discord", "items": items}
    write_if_changed(DATA / "gallery.json", out)
    prune(folder, used)
    log.info("gallery: %d images (%d videos and %d camera photos skipped)", len(items), videos, photos)


def prune(folder: pathlib.Path, keep: set[str]) -> None:
    if not folder.exists():
        return
    for f in folder.iterdir():
        if f.is_file() and f.name not in keep:
            f.unlink()
            log.info("deleted unreferenced %s", f.relative_to(ROOT))


# ----------------------------------------------------- Server List Ping ---
def _varint(n: int) -> bytes:
    n &= 0xFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed early")
        buf += chunk
    return bytes(buf)


def _read_varint(sock: socket.socket) -> int:
    n = 0
    for i in range(5):
        b = _read_exact(sock, 1)[0]
        n |= (b & 0x7F) << (7 * i)
        if not b & 0x80:
            return n
    raise ValueError("VarInt too long")


def _buf_varint(buf: bytes, i: int) -> tuple[int, int]:
    n = 0
    for k in range(5):
        b = buf[i]; i += 1
        n |= (b & 0x7F) << (7 * k)
        if not b & 0x80:
            return n, i
    raise ValueError("VarInt too long")


def server_list_ping(host: str, port: int, timeout: float = 3.0) -> dict:
    """Modern (1.7+) Server List Ping: handshake (next state 1) + status request -> JSON."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        h = host.encode("utf-8")
        hs = _varint(0x00) + _varint(767) + _varint(len(h)) + h + struct.pack(">H", port) + _varint(1)
        s.sendall(_varint(len(hs)) + hs + _varint(1) + _varint(0x00))
        length = _read_varint(s)
        if not 0 < length < 2_000_000:
            raise ValueError("bad packet length")
        buf = _read_exact(s, length)
    pid, i = _buf_varint(buf, 0)
    if pid != 0x00:
        raise ValueError(f"unexpected packet id {pid}")
    slen, i = _buf_varint(buf, i)
    return json.loads(buf[i:i + slen].decode("utf-8"))


def motd_text(desc) -> str:
    if isinstance(desc, str):
        t = desc
    elif isinstance(desc, dict):
        t = desc.get("text", "") + "".join(motd_text(x) for x in desc.get("extra", []))
    elif isinstance(desc, list):
        t = "".join(motd_text(x) for x in desc)
    else:
        t = ""
    return re.sub(r"§.", "", t)


def update_status(cfg: dict) -> None:
    host, port = cfg["minecraft_host"], cfg["minecraft_port"]
    out = {"online": False, "players": 0, "max": 0, "version": None, "modpack": None, "motd": None,
           "updated_at": now_iso()}
    try:
        j = server_list_ping(host, port)
        players = j.get("players") or {}
        better = j.get("betterStatus") or {}  # sent by the ATM "Better Compatibility Checker" mod
        out.update({
            "online": True,
            "players": int(players.get("online") or 0),
            "max": int(players.get("max") or 0),
            "version": (j.get("version") or {}).get("name"),
            "modpack": {"name": better.get("name"), "version": better.get("version")} if better else None,
            "motd": motd_text(j.get("description")).strip()[:200] or None,
        })
        # Player names from "players.sample" are deliberately NOT published.
        log.info("server online: %d/%d players, %s", out["players"], out["max"], out["version"])
    except Exception as e:  # noqa: BLE001
        log.warning("server ping failed (%s: %s) -> offline", type(e).__name__, e)
    write_if_changed(DATA / "status.json", out)


# ------------------------------------------------------------------ main ---
def main() -> int:
    cfg = load_config()
    steps = []
    if TOKEN:
        dc = Discord(TOKEN)
        steps += [("announcements", lambda: update_announcements(dc, cfg)), ("gallery", lambda: update_gallery(dc, cfg))]
    else:
        problem("ATMOSPHERE_DISCORD_BOT_TOKEN is not set: skipping announcements and gallery (existing files kept)")
    steps.append(("status", lambda: update_status(cfg)))
    if Image is None:
        problem("Pillow is not installed: gallery skipped")
        steps = [s for s in steps if s[0] != "gallery"]
    for name, fn in steps:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            problem(f"{name} failed, keeping the previous file: {type(e).__name__}: {e}")
    log.info("done, %d problem(s)", len(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
