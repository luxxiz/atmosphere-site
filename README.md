# ATMosphere website

Homepage for **ATMosphere**, a community Minecraft server running All the Mods 10.
Plain HTML/CSS/JS, hosted on GitHub Pages, refreshed automatically from Discord every ~15 minutes.

## What's where

| Path | What it is |
|---|---|
| `site/` | The website that gets published (built HTML, CSS, JS, images, data). |
| `src/pages/`, `src/partials/` | Page sources + shared header/footer. Edit these, not `site/*.html`. |
| `build.py` | Stitches `src/` into `site/*.html`. Run `python3 build.py` after editing `src/`. |
| `site/data/config.json` | Server address, Discord invite, Ko-fi link, ATM10 version, rules, donate text, mod notes. Edit by hand. |
| `site/data/mods.json` | Extra mods players must install (shown on *How to join*). Edit by hand. |
| `site/data/announcements.json` | **Auto-generated** from Discord #announcements. Don't edit. |
| `site/data/gallery.json` + `site/media/gallery/` | **Auto-generated** from Discord #showcase (images are downloaded copies). Don't edit. |
| `site/data/status.json` | **Auto-generated** server status. Not committed; created fresh on every run. |
| `updater/update.py` | The updater (Python 3.11+, `requests` + `Pillow`). |
| `updater/config.json` | Non-secret updater settings: channel IDs, Minecraft host/port, limits, gallery filters. |
| `.github/workflows/update.yml` | Runs the updater every 15 min, on manual start and on every push, then deploys. |

## The updater

* Reads Discord with the REST API v10, **GET requests only**. The bot only needs *View Channel* +
  *Read Message History* in the two channels, and the *Message Content* intent. It never posts anything.
* **#announcements**: the last 30 posts. The first line becomes the title. Discord markdown is converted
  to safe HTML (everything is escaped first, and the page also re-checks the HTML against an allow-list).
  Mentions become plain names, custom emoji and @everyone pings are dropped.
* **#showcase**: the last 60 images. They are downloaded and re-encoded to WebP with thumbnails, because
  Discord image links expire. Files that are no longer used get deleted. Videos are skipped.
  **JPEG photos are skipped on purpose**: Minecraft screenshots are PNG, while JPEGs in #showcase are phone
  photos (holidays, food, desk setups). Change `gallery_skip_jpeg` in `updater/config.json` to include them.
  To hide a specific post, add its message ID to `gallery_exclude_message_ids`.
* **Server status**: a real Minecraft *Server List Ping* to `82.24.111.62:25565` (3 s timeout): online/offline,
  players, Minecraft version, modpack version. Player names are **not** published.
* Files are only rewritten when their content changed. If one part fails (Discord down, server off),
  the others still run, the old file is kept, and the script still exits 0 (warnings show in the Actions log).

Settings can be overridden with environment variables: `ATMOSPHERE_ANNOUNCEMENTS_CHANNEL_ID`,
`ATMOSPHERE_SHOWCASE_CHANNEL_ID`, `ATMOSPHERE_MC_HOST`, `ATMOSPHERE_MC_PORT`.
The token comes **only** from the GitHub secret `ATMOSPHEREBOT` (the workflow passes it in as `ATMOSPHERE_DISCORD_BOT_TOKEN`). Never commit it.

## One-time setup on GitHub

1. Create a repository (public, so GitHub Pages and Actions minutes are free) and push this folder to `main`.
2. *Settings → Secrets and variables → Actions → New repository secret*: name `ATMOSPHEREBOT`,
   value = the bot token.
3. *Settings → Pages → Build and deployment → Source*: **GitHub Actions**.
4. *Actions* tab: enable workflows if asked, then run **Update from Discord and deploy** once by hand
   (*Run workflow*). The site appears at `https://<user>.github.io/<repo>/`.

## Good to know

* **Status freshness**: status is checked about every 15 min, so it can be up to ~15 min old (more if GitHub
  starts the run late). The page shows "Checked X min ago". If the last check is older than an hour, it shows
  *Unknown* instead of guessing.
* **GitHub may delay scheduled runs**, especially at busy times, and it **pauses scheduled workflows in public
  repos after 60 days without repository activity**. The bot's data commits count as activity, but only when
  something changed in Discord. If the channels are quiet for two months, GitHub emails the owner and the
  schedule stops. Re-enable it in the *Actions* tab or just push any commit.
* The site loads its data with `fetch()`, so opening the HTML files straight from disk won't show the data.
  To preview locally: `python3 -m http.server 8000 -d site`, then open http://localhost:8000.
* To run the updater locally: `pip install -r updater/requirements.txt`, set `ATMOSPHERE_DISCORD_BOT_TOKEN`
  in your shell (not in a file in this folder), then `python3 updater/update.py`.
