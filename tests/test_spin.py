"""Offline tests - no network, no credentials, no Spotify app needed."""
import json, os, sys, tempfile, unittest
from pathlib import Path

os.environ.setdefault("SPIN_DATA", str(Path(__file__).resolve().parent.parent / "data"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spin


class Filler(unittest.TestCase):
    def test_content_farms_rejected(self):
        for a, n in [("WM Beats", "Boom Bap Oldschool"), ("90s HipHop Legends", "The Golden Era Vault"),
                     ("Various Artists", "Anything"), ("Some Guy", "Juicy - Karaoke Version"),
                     ("Hip Hop Beat Nation", "Golden Age Train")]:
            self.assertIsNotNone(spin.looks_like_filler({"a": a, "n": n}, "90s Hip Hop"), f"{a} - {n}")

    def test_real_tracks_kept(self):
        for a, n in [("A Tribe Called Quest", "Can I Kick It?"), ("The Notorious B.I.G.", "Juicy"),
                     ("KC & The Sunshine Band", "Get Down Tonight - 2004 Remaster"),
                     ("Beastie Boys", "Intergalactic"), ("Bob Marley & The Wailers", "Could You Be Loved")]:
            self.assertIsNone(spin.looks_like_filler({"a": a, "n": n}, "90s Hip Hop"), f"{a} - {n}")


class Budget(unittest.TestCase):
    def test_never_bursts_past_the_cap(self):
        b = spin.Budget(5)
        self.assertEqual(sum(1 for _ in range(50) if b.take()), 5)

    def test_refills_over_time(self):
        b = spin.Budget(3600)          # one per second
        for _ in range(3600):
            b.take()
        self.assertFalse(b.take())
        b.ts -= 10                      # pretend 10s passed
        self.assertTrue(b.take())


class Index(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        spin.INDEX_PATH = Path(self.tmp.name) / "index.json"
        self.ix = spin.Index()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_crate_is_loaded(self):
        self.assertGreater(sum(self.ix.count(c) for c in spin.CATS), 0)

    def test_no_immediate_repeats(self):
        cat = next(c for c in spin.CATS if self.ix.count(c) >= 20)
        seen = [self.ix.pick(cat)["id"] for _ in range(10)]
        self.assertEqual(len(set(seen)), 10, "picked the same track twice in ten rolls")

    def test_repeat_window_grows_with_the_category(self):
        cat = next(c for c in spin.CATS if self.ix.count(c) >= 20)
        self.ix.d[cat]["tracks"] = self.ix.d[cat]["tracks"][:4]
        self.ix.pick(cat)
        small = self.ix.recent[cat].maxlen
        self.ix.d[cat]["tracks"] = self.ix.d[cat]["tracks"] * 40
        self.ix.pick(cat)
        self.assertGreater(self.ix.recent[cat].maxlen, small)

    def test_add_dedupes(self):
        t = [{"id": "x1", "n": "a", "a": "b", "y": "1999"}]
        cat = list(spin.CATS)[0]
        self.assertEqual(self.ix.add(cat, t, 0), 1)
        self.assertEqual(self.ix.add(cat, t, 10), 0)

    def test_survives_a_round_trip(self):
        self.ix.add(list(spin.CATS)[0], [{"id": "z9", "n": "n", "a": "a", "y": "2000"}], 0)
        self.ix.save()
        self.assertIn("z9", spin.INDEX_PATH.read_text())


class Offsets(unittest.TestCase):
    def test_depth_is_capped(self):
        # deep pagination is what polluted the first crate
        self.assertLessEqual(spin.MAX_OFFSET, 200)


class Categories(unittest.TestCase):
    def test_every_category_has_queries(self):
        for c, spec in spin.CATS.items():
            self.assertTrue(spec.get("q"), c)

    def test_seed_categories_all_exist(self):
        for c in spin.SEED:
            self.assertIn(c, spin.CATS, f"crate has {c!r} with no category")


if __name__ == "__main__":
    unittest.main(verbosity=2)
