#!/usr/bin/env python3
"""spin-that-dice - a party dice that picks a random track from a category.

Quota model
-----------
A roll never calls Spotify. Rolls are served from a local index that a
background thread tops up, spending at most `SPIN_CALLS_PER_HOUR` requests an
hour. A warm index means a whole party costs zero API calls, and the index
keeps growing toward "the whole catalogue" between parties.

Spotify's quota window re-arms if you keep calling while throttled, so a 429
trips a circuit breaker that honours Retry-After and stops calling entirely.
"""
import json, os, random, re, sys, threading, time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SPIN_DATA", HERE / "data"))
WEB = Path(os.environ.get("SPIN_WEB", HERE / "web"))
PORT = int(os.environ.get("SPIN_PORT", "8770"))
HOST = os.environ.get("SPIN_HOST", "127.0.0.1")
MARKET = os.environ.get("SPIN_MARKET", "GB")
TARGET = int(os.environ.get("SPIN_TARGET", "150"))          # tracks to hold per category
CALLS_PER_HOUR = int(os.environ.get("SPIN_CALLS_PER_HOUR", "60"))

CATS = json.loads((DATA / "categories.json").read_text())
SEED = json.loads((DATA / "crate.json").read_text()) if (DATA / "crate.json").exists() else {}
INDEX_PATH = DATA / "index.json"
MAX_OFFSET = int(os.environ.get("SPIN_MAX_OFFSET", "120"))

# Measured, not guessed: of 104 tracks hand-dropped from the first crate, 42 were
# 2020+ SEO uploads that only appear deep in a result set -- so depth is capped
# above. These patterns catch the outright content farms (8% of that junk, with
# zero false positives against 92 hand-kept tracks). The rest was genre mismatch,
# which nothing here can detect: Spotify removed artist `genres` for dev-mode apps.
BAD_TITLE = re.compile(r"(karaoke|tribute|made famous by|originally performed|type beat|"
                       r"study (music|beats)|sleep music|workout mix|8d audio|nightcore|"
                       r"ultra slowed)", re.I)
BAD_ARTIST = re.compile(r"(\bbeats\b|\bbeatz\b|\binstrumentals\b|karaoke|tribute band|"
                        r"\blegends\b|\bvault\b|\ball stars\b|hip hop beat|"
                        r"\bcollective\b|\bbeat nation\b)", re.I)


def looks_like_filler(track, cat):
    """Return a reason string if this is content-farm filler, else None."""
    a, n = track.get("a", ""), track.get("n", "")
    if re.match(r"^(various artists|unknown artist)$", a.strip(), re.I):
        return "various artists"
    if BAD_TITLE.search(n):
        return "title"
    if BAD_ARTIST.search(a):
        return "artist"
    words = [w for w in re.split(r"[^a-z0-9]+", cat.lower()) if len(w) > 2]
    if words and all(w in a.lower() for w in words):
        return "named after the category"
    return None


# ---------------------------------------------------------------- credentials
def _creds():
    """env -> ./spin.env -> ~/.spin-that-dice.env. Nothing else, no vault."""
    cid, sec = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    for p in (HERE / "spin.env", Path.home() / ".spin-that-dice.env"):
        if p.exists():
            kv = {}
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip().strip("'\"")
            cid = cid or kv.get("SPOTIFY_CLIENT_ID")
            sec = sec or kv.get("SPOTIFY_CLIENT_SECRET")
            if cid and sec:
                return cid, sec
    raise RuntimeError("no SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET (see README)")


# ---------------------------------------------------------------- rate control
class Budget:
    """Token bucket. Refills to CALLS_PER_HOUR over an hour, never bursts past it."""

    def __init__(self, per_hour):
        self.cap = max(1, per_hour)
        self.tokens = float(self.cap)
        self.rate = self.cap / 3600.0
        self.ts = time.time()
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            now = time.time()
            self.tokens = min(self.cap, self.tokens + (now - self.ts) * self.rate)
            self.ts = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False

    def left(self):
        with self.lock:
            return int(self.tokens)


budget = Budget(CALLS_PER_HOUR)
_blocked_until = 0.0
_tok = {"v": None, "exp": 0.0}
_tlock = threading.Lock()


def blocked_for():
    return max(0.0, _blocked_until - time.time())


def token():
    with _tlock:
        if _tok["v"] and time.time() < _tok["exp"]:
            return _tok["v"]
        cid, sec = _creds()
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(cid, sec),
            timeout=15,
        )
        r.raise_for_status()
        j = r.json()
        _tok["v"] = j["access_token"]
        _tok["exp"] = time.time() + int(j.get("expires_in", 3600)) - 120
        return _tok["v"]


# ---------------------------------------------------------------- the index
class Index:
    def __init__(self):
        self.lock = threading.Lock()
        self.d = {}
        if INDEX_PATH.exists():
            try:
                self.d = json.loads(INDEX_PATH.read_text())
            except Exception:
                self.d = {}
        for cat, tracks in SEED.items():          # seed crate ships with the repo
            slot = self.d.setdefault(cat, {"tracks": [], "offsets": []})
            have = {t["id"] for t in slot["tracks"]}
            slot["tracks"].extend(t for t in tracks if t.get("id") and t["id"] not in have)
        self.recent = {}

    def count(self, cat):
        with self.lock:
            return len(self.d.get(cat, {}).get("tracks", []))

    def pick(self, cat):
        with self.lock:
            tracks = self.d.get(cat, {}).get("tracks", [])
            if not tracks:
                return None
            want = min(40, max(1, len(tracks) // 2))
            seen = self.recent.get(cat)
            if seen is None or seen.maxlen != want:
                # the category grows, so the no-repeat window has to grow with it
                seen = deque(seen or (), maxlen=want)
                self.recent[cat] = seen
            fresh = [t for t in tracks if t["id"] not in seen] or tracks
            t = random.choice(fresh)
            seen.append(t["id"])
            return t

    def add(self, cat, tracks, offset):
        with self.lock:
            slot = self.d.setdefault(cat, {"tracks": [], "offsets": []})
            have = {t["id"] for t in slot["tracks"]}
            new = [t for t in tracks if t["id"] not in have]
            slot["tracks"].extend(new)
            if offset not in slot["offsets"]:
                slot["offsets"].append(offset)
            return len(new)

    def offsets(self, cat):
        with self.lock:
            return set(self.d.get(cat, {}).get("offsets", []))

    def save(self):
        with self.lock:
            tmp = INDEX_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d))
            tmp.replace(INDEX_PATH)


index = Index()


def fetch(cat):
    """One search request. Returns tracks added, or raises."""
    global _blocked_until
    spec = CATS[cat]
    used = index.offsets(cat)
    pool = [o for o in range(0, MAX_OFFSET, 10) if o not in used] or list(range(0, MAX_OFFSET, 10))
    offset = random.choice(pool)
    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token()}"},
        params={"q": random.choice(spec["q"]), "type": "track",
                "limit": 10, "offset": offset, "market": MARKET},
        timeout=15,
    )
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After", "3600") or 3600)
        _blocked_until = time.time() + wait
        raise RuntimeError(f"429 quota, {wait // 3600}h{wait % 3600 // 60:02d}m")
    r.raise_for_status()
    items = [t for t in (r.json().get("tracks") or {}).get("items") or [] if t and t.get("id")]
    cand = [{
        "id": t["id"], "n": t["name"],
        "a": ", ".join(a["name"] for a in t.get("artists") or []),
        "y": (t.get("album") or {}).get("release_date", "")[:4],
    } for t in items]
    clean = [t for t in cand if not looks_like_filler(t, cat)]
    return index.add(cat, clean, offset)


def topper():
    """Background top-up. Fills the thinnest categories first, within budget."""
    while True:
        try:
            dirty = False
            if not blocked_for():
                thin = sorted(CATS, key=index.count)
                for cat in thin:
                    if index.count(cat) >= TARGET:
                        continue
                    if not budget.take():
                        break
                    try:
                        n = fetch(cat)
                        sys.stderr.write(f"topup {cat}: +{n} (now {index.count(cat)})\n")
                        dirty = True
                    except Exception as e:
                        sys.stderr.write(f"topup {cat} failed: {e}\n")
                        break
                    time.sleep(2)
                if dirty:
                    index.save()   # one write per pass, not one per request
        except Exception as e:
            sys.stderr.write(f"topper: {e}\n")
        time.sleep(30)


# ---------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "spin-that-dice"

    def _send(self, code, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if ctype == "application/json" else "max-age=60")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/categories":
            return self._send(200, {
                "blocked_min": int(blocked_for() // 60),
                "budget_left": budget.left(),
                "cats": [{"name": c, "have": index.count(c)} for c in CATS],
            })
        if u.path == "/api/roll":
            cat = (parse_qs(u.query).get("cat") or [""])[0]
            if cat in ("", "any"):
                playable = [c for c in CATS if index.count(c)]
                cat = random.choice(playable or list(CATS))
            if cat not in CATS:
                return self._send(404, {"error": f"unknown category {cat!r}"})
            t = index.pick(cat)
            if not t:
                return self._send(503, {"cat": cat, "error": "nothing indexed for this category yet",
                                        "blocked_min": int(blocked_for() // 60)})
            return self._send(200, {"cat": cat, "track": t, "have": index.count(cat)})
        path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        f = (WEB / path).resolve()
        if f.is_file() and str(f).startswith(str(WEB.resolve())):
            ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "application/octet-stream"
            return self._send(200, f.read_bytes(), ctype)
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=topper, daemon=True).start()
    sys.stderr.write(f"spin-that-dice on {HOST}:{PORT} - {len(CATS)} categories, "
                     f"{sum(index.count(c) for c in CATS)} tracks indexed\n")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
