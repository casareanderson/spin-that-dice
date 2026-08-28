"""Music backends other than Spotify.

Both of these are strictly better sources for a dice than Spotify is: they expose
real genres from your own tags, they can return a random track in one call, and
they stream audio you own -- so no quota, no index, no Premium, no 5-user cap.

⚠️ UNVERIFIED: written against the published API specs and covered by offline
tests with a stubbed transport, but never run against a live server. Expect to
fix something the first time you point it at one.

Streams are proxied through spin.py rather than handed to the browser, so server
credentials never reach the page and there is no CORS to negotiate.
"""
import hashlib
import os
import random
import secrets
from urllib.parse import urlencode

import requests

TIMEOUT = 15


class ProviderError(RuntimeError):
    pass


class Provider:
    """A source of categories and random tracks."""

    needs_index = False          # only Spotify has to build one

    def categories(self):
        """-> [str] category names."""
        raise NotImplementedError

    def roll(self, cat):
        """-> {"id","n","a","y"} for one random track in `cat`."""
        raise NotImplementedError

    def stream(self, track_id):
        """-> (requests.Response streaming, content_type)."""
        raise NotImplementedError


class Subsonic(Provider):
    """Navidrome, Airsonic, Gonic, Ampache, LMS - anything speaking Subsonic.

    Env: SPIN_SUBSONIC_URL, SPIN_SUBSONIC_USER, SPIN_SUBSONIC_PASSWORD
    """

    name = "subsonic"

    def __init__(self, url=None, user=None, password=None):
        self.url = (url or os.environ.get("SPIN_SUBSONIC_URL", "")).rstrip("/")
        self.user = user or os.environ.get("SPIN_SUBSONIC_USER", "")
        self.password = password or os.environ.get("SPIN_SUBSONIC_PASSWORD", "")
        if not (self.url and self.user and self.password):
            raise ProviderError("set SPIN_SUBSONIC_URL / _USER / _PASSWORD")

    def _params(self, **extra):
        # salted token auth - the plaintext password never goes over the wire
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.password + salt).encode()).hexdigest()
        p = {"u": self.user, "t": token, "s": salt,
             "v": "1.16.1", "c": "spin-that-dice", "f": "json"}
        p.update(extra)
        return p

    def _get(self, endpoint, **extra):
        r = requests.get(f"{self.url}/rest/{endpoint}",
                         params=self._params(**extra), timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json().get("subsonic-response") or {}
        if body.get("status") != "ok":
            err = body.get("error") or {}
            raise ProviderError(f"subsonic {err.get('code','?')}: {err.get('message','unknown')}")
        return body

    def categories(self):
        genres = (self._get("getGenres").get("genres") or {}).get("genre") or []
        named = [(g.get("value") or "", g.get("songCount") or 0) for g in genres]
        return [v for v, n in sorted(named, key=lambda x: -x[1]) if v]

    def roll(self, cat):
        # the dice is a single API call on this backend
        songs = (self._get("getRandomSongs", size=1, genre=cat)
                 .get("randomSongs") or {}).get("song") or []
        if not songs:
            raise ProviderError(f"no songs in genre {cat!r}")
        s = songs[0]
        return {"id": str(s.get("id")), "n": s.get("title") or "",
                "a": s.get("artist") or "", "y": str(s.get("year") or "")}

    def stream(self, track_id):
        r = requests.get(f"{self.url}/rest/stream",
                         params=self._params(id=track_id), stream=True, timeout=TIMEOUT)
        r.raise_for_status()
        return r, r.headers.get("Content-Type", "audio/mpeg")

    def jukebox(self, track_id):
        """Play on the SERVER's speakers (Navidrome jukebox mode), not the browser."""
        self._get("jukeboxControl", action="set", id=track_id)
        self._get("jukeboxControl", action="start")


class Jellyfin(Provider):
    """Jellyfin (and Emby, which shares this API shape).

    Env: SPIN_JELLYFIN_URL, SPIN_JELLYFIN_TOKEN  (optional SPIN_JELLYFIN_USER_ID)
    """

    name = "jellyfin"

    def __init__(self, url=None, token=None, user_id=None):
        self.url = (url or os.environ.get("SPIN_JELLYFIN_URL", "")).rstrip("/")
        self.token = token or os.environ.get("SPIN_JELLYFIN_TOKEN", "")
        self._user_id = user_id or os.environ.get("SPIN_JELLYFIN_USER_ID") or None
        if not (self.url and self.token):
            raise ProviderError("set SPIN_JELLYFIN_URL / SPIN_JELLYFIN_TOKEN")

    @property
    def headers(self):
        return {"Authorization": f'MediaBrowser Token="{self.token}"',
                "Accept": "application/json"}

    def _get(self, path, **params):
        r = requests.get(f"{self.url}{path}", headers=self.headers,
                         params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    @property
    def user_id(self):
        if not self._user_id:
            me = self._get("/Users/Me")
            self._user_id = me.get("Id")
            if not self._user_id:
                raise ProviderError("could not resolve a Jellyfin user id")
        return self._user_id

    def categories(self):
        items = self._get("/Genres", includeItemTypes="Audio",
                          recursive="true", userId=self.user_id).get("Items") or []
        return [g["Name"] for g in items if g.get("Name")]

    def roll(self, cat):
        items = self._get("/Items", includeItemTypes="Audio", recursive="true",
                          sortBy="Random", limit=1, genres=cat,
                          userId=self.user_id).get("Items") or []
        if not items:
            raise ProviderError(f"no songs in genre {cat!r}")
        i = items[0]
        artists = i.get("Artists") or []
        return {"id": str(i.get("Id")), "n": i.get("Name") or "",
                "a": ", ".join(artists) or (i.get("AlbumArtist") or ""),
                "y": str(i.get("ProductionYear") or "")}

    def stream(self, track_id):
        q = urlencode({"userId": self.user_id, "api_key": self.token,
                       "container": "mp3", "audioCodec": "mp3"})
        r = requests.get(f"{self.url}/Audio/{track_id}/universal?{q}",
                         stream=True, timeout=TIMEOUT)
        r.raise_for_status()
        return r, r.headers.get("Content-Type", "audio/mpeg")


def build(name=None):
    """Factory. Returns None for spotify, which spin.py handles natively."""
    name = (name or os.environ.get("SPIN_PROVIDER", "spotify")).lower()
    if name == "spotify":
        return None
    if name == "subsonic":
        return Subsonic()
    if name == "jellyfin":
        return Jellyfin()
    raise ProviderError(f"unknown SPIN_PROVIDER {name!r} (spotify|subsonic|jellyfin)")
