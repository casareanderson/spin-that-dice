# spin-that-dice

A party dice for Spotify. Tap the die, get a random track from a category, and it
plays. Built for an iPad propped up at a party — black, one big target, no menus.

Rolling **never calls the Spotify API**. A background thread builds a local index
within a strict request budget; the die picks from that. A four-hour party costs
zero API calls, and the index keeps growing between parties.

## Why the index exists

The obvious design — one search request per roll — dies in practice:

- Spotify rate-limits **per app**, not per user, on a rolling window. A busy
  screen exhausts it and takes every other roll down with it.
- Worse, **the quota window re-arms while you are throttled.** Keep calling after
  a 429 and the deadline keeps moving; an open browser tab can hold an app in a
  permanent 429. Measured directly: a `Retry-After` of 82,510s had *grown back*
  toward 24h after further calls.

So this trades freshness for reliability:

| | requests |
|---|---|
| Rolls during a party | **0** |
| Filling one category to 150 tracks | ~15, spread over time |
| Budget ceiling | `SPIN_CALLS_PER_HOUR`, default 60 |

A 429 trips a circuit breaker that honours `Retry-After` and stops calling
entirely until it expires. Rolls keep working the whole time.

## Setup

```bash
git clone https://github.com/casareanderson/spin-that-dice
cd spin-that-dice
pip install requests                      # the only dependency
cp spin.env.example spin.env              # add your Client ID + Secret
python3 spin.py                           # http://localhost:8770
```

Credentials come from **your own** Spotify app
([dashboard](https://developer.spotify.com/dashboard)) — so you get your own
quota, not a shared one. Search uses the client-credentials flow: no login, no
redirect URI, no scopes.

It ships with a curated 305-track crate across 10 categories, so a fresh clone
works offline from the first roll while the other 33 categories fill in.

### Running it properly

```bash
sudo cp -r . /opt/spin-that-dice
sudo cp systemd/spin-that-dice.service /etc/systemd/system/
sudo systemctl enable --now spin-that-dice
```

Put it behind a reverse proxy for TLS. `spin.py` serves the page itself, so a
plain `reverse_proxy 127.0.0.1:8770` is enough.

### On an iPad

Open the page in Safari → Share → **Add to Home Screen**. It launches
full-screen with no browser chrome, and holds a screen wake lock so it won't
sleep mid-party.

## Configuration

| env | default | meaning |
|---|---|---|
| `SPIN_PORT` / `SPIN_HOST` | `8770` / `127.0.0.1` | listen address |
| `SPIN_MARKET` | `GB` | Spotify market for results |
| `SPIN_TARGET` | `150` | tracks to hold per category |
| `SPIN_MAX_OFFSET` | `120` | how deep to paginate (see below) |
| `SPIN_CALLS_PER_HOUR` | `60` | hard ceiling on API requests |
| `SPIN_DATA` / `SPIN_WEB` | `./data` / `./web` | asset locations |

## Result quality

Search results get worse the deeper you page. Of 104 tracks hand-dropped from the
first crate, **42 were 2020+ SEO uploads** that only surface deep in a result set,
so `SPIN_MAX_OFFSET` caps depth at 120 by default.

A pattern filter (`looks_like_filler`) rejects outright content farms - "type
beat" accounts, karaoke, `Various Artists`, artists named after the category.
Measured against that hand-classified set it catches **8% of the junk with zero
false positives** against 92 hand-kept tracks. It is deliberately conservative:
most of what was wrong with the first crate was *genre mismatch*, not spam, and
nothing here can detect that - Spotify removed artist `genres` for
Development Mode apps in Feb 2026.

```bash
python3 -m unittest discover -s tests    # offline, no creds, no network
```

## Categories

43, defined as search queries in `data/categories.json` — 90s and 2000s Hip Hop,
R&B, Soul, Neo Soul, Funk & Disco, Afrobeats, Afro House, Amapiano, Dancehall,
Reggae, Hiplife, Highlife, UK Rap, Grime, UK Garage, Drill, Trap, House, Techno,
Drum & Bass, Jungle, Rock, Indie, Punk, Metal, Pop, 80s, 90s Pop, 2000s Pop,
Jazz, Blues, Gospel, Country, Latin, Reggaeton, Soca, K-Pop, Bollywood, Lo-fi,
Classical and more. Add your own by adding queries.

## Playback

Uses the [Spotify iFrame
API](https://developer.spotify.com/documentation/embeds/tutorials/using-the-iframe-api)
so a roll can call `play()` — a fresh `<iframe>` per roll has nothing to call.
**Full-length playback needs Spotify Premium, logged in on that device**;
Spotify removed 30-second previews from the API in November 2024, so there is no
longer a free fallback.

## Notes on the Spotify API

Some of this is not in the docs and cost real time to find:

- **Nov 2024** removed `/recommendations`, `/audio-features`, `/audio-analysis`,
  `/related-artists` and 30s previews.
- **Feb 2026** renamed and trimmed: search `limit` capped at **10** (was 50),
  `popularity` stripped, artist `genres` **absent entirely** for Development Mode
  apps, and dev-mode user allowlists cut from 25 to 5.
- Removed endpoints answer **403, not 404** — check the path before blaming scopes.

Sequencing a playlist so it flows is a separate tool:
[setlisted](https://github.com/casareanderson/setlisted).

## Licence

MIT.
