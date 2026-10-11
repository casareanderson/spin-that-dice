# Setting up spin-that-dice

About 10 minutes. You can roll the dice before you've made a Spotify app: a fresh clone ships a
305-track starter crate covering 10 of the 43 categories. The steps marked **CI checks this** are run on
a fresh Ubuntu machine every week by [`setup-check`](../.github/workflows/setup-check.yml).

## What you need

| | |
|---|---|
| OS | Linux or macOS for the server. Any modern browser for the dice (tablet, phone, laptop). |
| Python | 3.10 or newer (CI runs 3.10 and 3.12) |
| Python packages | `requests` (the only dependency) |
| To play songs | **Spotify Premium**, logged in on the device showing the page. Spotify removed free 30-second previews in November 2024, so there is no free fallback. |
| To fill all 43 categories | a free Spotify app (client id and secret). Optional. |
| Instead of Spotify | a Subsonic-compatible server (Navidrome and friends) or Jellyfin/Emby. Optional. |

## 1. Install and first run (CI checks this)

```bash
git clone https://github.com/casareanderson/spin-that-dice && cd spin-that-dice
python3 -m pip install requests
python3 -m unittest discover -s tests
python3 spin.py
```

The tests run offline (no network, no credentials) and end with `OK`. Then `spin.py` prints one line on
stderr and keeps running:

```
spin-that-dice on 127.0.0.1:8770 - spotify, 43 categories, 305 tracks indexed
```

Open <http://localhost:8770> and tap the die.

To check it from another terminal (this is what CI does):

```bash
curl -s localhost:8770/api/categories | head -c 200
curl -s "localhost:8770/api/roll?cat=Soul"
```

The second one returns a track from the starter crate as JSON.

Without a Spotify app, the background top-up logs `topup <category> failed: no SPOTIFY_CLIENT_ID /
SPOTIFY_CLIENT_SECRET (see README)` every 30 seconds. That's expected. The dice still roll from the
crate, and a roll never calls Spotify.

## 2. Fill the other 33 categories (optional, not checked by CI)

1. Create an app at <https://developer.spotify.com/dashboard> and tick **Web API**. Search uses the
   client-credentials flow, so you need no login, no redirect URI and no scopes.
2. Copy the example file and paste in the two values:

   ```bash
   cp spin.env.example spin.env
   ```

   ```
   SPOTIFY_CLIENT_ID=your-client-id
   SPOTIFY_CLIENT_SECRET=your-client-secret
   ```

3. Restart `spin.py`. You'll see lines like `topup R&B: +9 (now 46)` as it fills the thinnest categories
   first, at most `SPIN_CALLS_PER_HOUR` requests an hour (60 by default). Filling one category to 150
   tracks takes about 15 requests, so give it a few hours. The index is saved to `data/index.json`.

Credentials are read from the environment first, then `./spin.env`, then `~/.spin-that-dice.env`.

## 3. Configure

Environment variables, all read in `spin.py`, `providers.py` and `export.py`:

| name | default | what it does |
|---|---|---|
| `SPIN_HOST` | `127.0.0.1` | listen address. Set `0.0.0.0` to reach it from a tablet on your network. |
| `SPIN_PORT` | `8770` | listen port |
| `SPIN_PROVIDER` | `spotify` | `spotify`, `subsonic` or `jellyfin` |
| `SPIN_MARKET` | `GB` | Spotify market for search results |
| `SPIN_TARGET` | `150` | tracks to hold per category |
| `SPIN_MAX_OFFSET` | `120` | how deep to page into search results (deeper pages are mostly junk) |
| `SPIN_CALLS_PER_HOUR` | `60` | hard ceiling on Spotify requests per hour |
| `SPIN_DATA` | `./data` | categories, starter crate and the growing index |
| `SPIN_WEB` | `./web` | the page `spin.py` serves |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | none | Spotify app credentials (step 2) |
| `SPIN_SUBSONIC_URL` / `SPIN_SUBSONIC_USER` / `SPIN_SUBSONIC_PASSWORD` | none | Subsonic-compatible server |
| `SPIN_JELLYFIN_URL` / `SPIN_JELLYFIN_TOKEN` | none | Jellyfin or Emby server |
| `SPIN_JELLYFIN_USER_ID` | looked up | Jellyfin user id, if you want to pin one |
| `SPIN_DOMAIN` | none | `export.py` writes it to `docs/CNAME` when set |

Page settings live in `web/config.json`. Its only key, `spotify_client_id`, is empty by default (see
"Let guests use their own Spotify" below).

## 4. Use your own music server instead (not checked by CI)

```bash
SPIN_PROVIDER=subsonic SPIN_SUBSONIC_URL=http://nas.example.com:4533 \
SPIN_SUBSONIC_USER=you SPIN_SUBSONIC_PASSWORD=... python3 spin.py

SPIN_PROVIDER=jellyfin SPIN_JELLYFIN_URL=http://jellyfin.example.com:8096 \
SPIN_JELLYFIN_TOKEN=... python3 spin.py
```

The startup line then says `provider subsonic, no index needed`. Audio streams through `/api/stream`, so
your server's credentials never reach the browser. Be warned: these two backends are tested offline
against a stub, not against a live server. If one breaks on yours, please open an issue.

## 5. Run it as a service (not checked by CI)

The unit file runs `/usr/bin/python3`, so `requests` must be installed for the system Python
(`sudo apt install python3-requests` on Debian/Ubuntu).

```bash
sudo cp -r . /opt/spin-that-dice
sudo cp systemd/spin-that-dice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spin-that-dice
journalctl -u spin-that-dice -f       # you should see the startup line
```

Put it behind a reverse proxy for TLS. `spin.py` serves the page itself, so a plain
`reverse_proxy 127.0.0.1:8770` (Caddy) is enough. On a tablet: Safari → Share → **Add to Home Screen**,
or Chrome → menu → **Install app**.

## 6. Publish a static copy (CI checks this)

```bash
python3 export.py            # writes ./docs: index.html, index.json and the icons
```

The page notices there's no `/api` and rolls from `docs/index.json` in the browser, so you can host
`docs/` on GitHub Pages or Cloudflare Pages with no server and no key.

## Let guests use their own Spotify (optional)

Set `spotify_client_id` in `web/config.json` (it's public, not a secret), and add the page's exact URL as
a redirect URI on your Spotify app. A **Connect Spotify** link appears. Spotify only accepts HTTPS
redirect URIs (or literal `http://127.0.0.1:PORT`), so a LAN address like `http://192.0.2.10:8770` won't
work, and a Development Mode app allows 5 accounts in total.

## Common errors

| you see | what's wrong |
|---|---|
| `topup ... failed: no SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET` | no Spotify app set up yet. Fine for the crate. See step 2. |
| `topup ... failed: 429 quota, 23h01m` | Spotify's per-app quota is used up. `spin.py` stops calling until `Retry-After` passes. Don't restart it in a loop: Spotify's window re-arms while you're throttled. |
| roll returns `503` `nothing indexed for this category yet` | that category isn't in the crate and hasn't been filled yet. Pick another, or wait for the top-up. |
| roll returns `404` `unknown category` | the `cat` value doesn't match a name in `data/categories.json` (it's case-sensitive). |
| `set SPIN_SUBSONIC_URL / _USER / _PASSWORD` or `set SPIN_JELLYFIN_URL / SPIN_JELLYFIN_TOKEN` | you chose a provider without its settings. |
| `unknown SPIN_PROVIDER` | use `spotify`, `subsonic` or `jellyfin`. |
| the die rolls but nothing plays | the device isn't logged in to Spotify Premium. |
| `OSError: [Errno 98] Address already in use` | something else is on port 8770. Set `SPIN_PORT`. |

## Updating

```bash
cd spin-that-dice && git pull && python3 -m unittest discover -s tests
```

`spin.env` and `data/index.json` are yours and aren't in the repo, so a pull keeps them. If you run the
service from `/opt/spin-that-dice`, copy the new files over and `sudo systemctl restart spin-that-dice`.

## Uninstalling

```bash
sudo systemctl disable --now spin-that-dice
sudo rm -rf /opt/spin-that-dice /etc/systemd/system/spin-that-dice.service
rm -rf spin-that-dice ~/.spin-that-dice.env
```

## What CI can't prove

The weekly check installs from a fresh clone, runs the 27 offline tests, starts the server, rolls from the
starter crate over HTTP, checks unknown categories and paths are refused, and builds the static site. It
never talks to Spotify, Subsonic or Jellyfin, and it can't press play on a Premium account. Steps 2, 4 and
5 are yours to check.
