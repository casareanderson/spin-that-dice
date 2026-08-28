"""Offline provider tests - a stubbed transport, no server, no network."""
import os, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import providers


class FakeResponse:
    def __init__(self, payload=None, headers=None, chunks=None):
        self._payload, self.headers = payload, headers or {}
        self._chunks = chunks or []
    def json(self): return self._payload
    def raise_for_status(self): pass
    def iter_content(self, n): return iter(self._chunks)


def sub_ok(body):
    return FakeResponse({"subsonic-response": dict(body, status="ok")})


class SubsonicTests(unittest.TestCase):
    def setUp(self):
        self.p = providers.Subsonic("http://nas:4533/", "chris", "hunter2")

    def test_password_is_never_sent_in_clear(self):
        q = self.p._params()
        self.assertNotIn("hunter2", str(q))
        self.assertEqual(len(q["t"]), 32)          # md5(password + salt)
        self.assertNotEqual(self.p._params()["s"], self.p._params()["s"])  # fresh salt

    def test_categories_sorted_by_song_count(self):
        body = {"genres": {"genre": [{"value": "Reggae", "songCount": 10},
                                     {"value": "Soul", "songCount": 99},
                                     {"value": "", "songCount": 5}]}}
        with mock.patch("requests.get", return_value=sub_ok(body)):
            self.assertEqual(self.p.categories(), ["Soul", "Reggae"])

    def test_roll_shape(self):
        body = {"randomSongs": {"song": [{"id": 42, "title": "Juicy",
                                          "artist": "The Notorious B.I.G.", "year": 1994}]}}
        with mock.patch("requests.get", return_value=sub_ok(body)):
            t = self.p.roll("90s Hip Hop")
        self.assertEqual(t, {"id": "42", "n": "Juicy",
                             "a": "The Notorious B.I.G.", "y": "1994"})

    def test_empty_genre_raises_rather_than_returning_none(self):
        with mock.patch("requests.get", return_value=sub_ok({"randomSongs": {}})):
            with self.assertRaises(providers.ProviderError):
                self.p.roll("Polka")

    def test_server_error_is_surfaced(self):
        bad = FakeResponse({"subsonic-response": {"status": "failed",
                                                  "error": {"code": 40, "message": "wrong password"}}})
        with mock.patch("requests.get", return_value=bad):
            with self.assertRaisesRegex(providers.ProviderError, "wrong password"):
                self.p.categories()

    def test_missing_config_fails_loudly(self):
        with mock.patch.dict(os.environ, {"SPIN_SUBSONIC_URL": "", "SPIN_SUBSONIC_USER": "",
                                          "SPIN_SUBSONIC_PASSWORD": ""}, clear=False):
            with self.assertRaises(providers.ProviderError):
                providers.Subsonic()


class JellyfinTests(unittest.TestCase):
    def setUp(self):
        self.p = providers.Jellyfin("http://jf:8096/", "tok123", user_id="u1")

    def test_auth_header_shape(self):
        self.assertEqual(self.p.headers["Authorization"], 'MediaBrowser Token="tok123"')

    def test_categories(self):
        with mock.patch("requests.get", return_value=FakeResponse(
                {"Items": [{"Name": "Soul"}, {"Name": "Afrobeats"}, {"Nope": 1}]})):
            self.assertEqual(self.p.categories(), ["Soul", "Afrobeats"])

    def test_roll_joins_multiple_artists(self):
        with mock.patch("requests.get", return_value=FakeResponse(
                {"Items": [{"Id": "abc", "Name": "Regulate",
                            "Artists": ["Warren G", "Nate Dogg"], "ProductionYear": 1994}]})):
            t = self.p.roll("90s Hip Hop")
        self.assertEqual(t["a"], "Warren G, Nate Dogg")
        self.assertEqual(t["id"], "abc")

    def test_roll_falls_back_to_album_artist(self):
        with mock.patch("requests.get", return_value=FakeResponse(
                {"Items": [{"Id": "z", "Name": "n", "AlbumArtist": "Sade"}]})):
            self.assertEqual(self.p.roll("Soul")["a"], "Sade")

    def test_empty_genre_raises(self):
        with mock.patch("requests.get", return_value=FakeResponse({"Items": []})):
            with self.assertRaises(providers.ProviderError):
                self.p.roll("Polka")

    def test_user_id_resolved_when_not_given(self):
        p = providers.Jellyfin("http://jf:8096", "tok")
        with mock.patch("requests.get", return_value=FakeResponse({"Id": "resolved"})):
            self.assertEqual(p.user_id, "resolved")


class FactoryTests(unittest.TestCase):
    def test_spotify_is_native(self):
        self.assertIsNone(providers.build("spotify"))

    def test_unknown_provider_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.build("winamp")

    def test_env_selects_provider(self):
        with mock.patch.dict(os.environ, {"SPIN_PROVIDER": "subsonic",
                                          "SPIN_SUBSONIC_URL": "http://x",
                                          "SPIN_SUBSONIC_USER": "u",
                                          "SPIN_SUBSONIC_PASSWORD": "p"}):
            self.assertIsInstance(providers.build(), providers.Subsonic)


if __name__ == "__main__":
    unittest.main(verbosity=2)
