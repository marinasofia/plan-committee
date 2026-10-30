"""Unit tests for the pure functions in pipeline/build_places.py. No DuckDB, no network, no files written.
Run with `python3 -m unittest -v` from the repo root."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build_places as bp  # noqa: E402


def row(**kw):
    base = {"name": "Bar Alto", "confidence": 0.9, "web": "https://baralto.pt", "brand": None, "status": None,
            "primary": "cocktail_bar", "hierarchy": ["food_and_drink", "bar", "cocktail_bar"], "lat": 38.7123456, "lon": -9.1412345}
    return {**base, **kw}


class KindOf(unittest.TestCase):
    def test_types(self):
        self.assertEqual(bp.kind_of("cocktail_bar", ["food_and_drink", "bar"]), "drinks")
        self.assertEqual(bp.kind_of("italian_restaurant", ["food_and_drink", "restaurant"]), "dinner")
        self.assertEqual(bp.kind_of("comedy_club", ["arts_and_entertainment", "performing_arts_venue"]), "late")
        self.assertEqual(bp.kind_of("park", ["sports_and_recreation", "park"]), "free")

    def test_takeout_and_shops_are_not_a_night_out(self):
        for p in ("fast_food_restaurant", "coffee_shop", "bakery", "doner_kebab_restaurant", "breakfast_and_brunch_restaurant"):
            self.assertIsNone(bp.kind_of(p, ["food_and_drink", "restaurant", p]), p)
        self.assertIsNone(bp.kind_of("dentist", ["health_care"]))


class ToSpot(unittest.TestCase):
    def test_bar(self):
        s = bp.to_spot(row())
        self.assertEqual((s["n"], s["t"], s["f"], s["lat"], s["web"]), ("Bar Alto", "drinks", ["fancy"], 38.71235, "https://baralto.pt"))

    def test_cuisine(self):
        s = bp.to_spot(row(primary="sushi_restaurant", hierarchy=["food_and_drink", "restaurant"]))
        self.assertEqual((s["t"], s["c"]), ("dinner", "asian"))

    def test_rejects_closed_unsure_chain_and_events(self):
        self.assertIsNone(bp.to_spot(row(status="permanently_closed")))
        self.assertIsNone(bp.to_spot(row(confidence=0.3)))
        self.assertIsNone(bp.to_spot(row(brand="Q123")))
        self.assertIsNone(bp.to_spot(row(name="Starbucks Reserve")))
        self.assertIsNone(bp.to_spot(row(name="Jazz Festival HQ")))

    def test_untrusted_text_and_links(self):
        s = bp.to_spot(row(name="Bar‮\x00 Alto" + "x" * 200, web="javascript:alert(1)"))
        self.assertTrue(s["n"].startswith("Bar Alto") and len(s["n"]) <= 80)
        self.assertEqual(s["web"], "")


class CleanUrl(unittest.TestCase):
    def test_drops_query_and_fragment(self):
        self.assertEqual(bp.clean_url("https://rezto.app/reservation/piano?rwg_token=AFd1x&x=1#top"), "https://rezto.app/reservation/piano")
        self.assertEqual(bp.clean_url("javascript:alert(1)"), "")
        self.assertEqual(bp.clean_url("https://"), "")


class Pick(unittest.TestCase):
    def test_three_in_town_is_a_chain_and_names_are_unique(self):
        rows = [row(name="Taco Spot", lat=38.7 + i / 1000) for i in range(3)] + [row(), row(name="bar alto")]
        names = [s["n"] for s in bp.pick(rows)]
        self.assertEqual(names, ["Bar Alto"])

    def test_galleries_are_capped(self):
        rows = [row(name=f"Gallery {i}", primary="art_gallery", hierarchy=["arts_and_entertainment", "art_gallery"]) for i in range(40)]
        self.assertEqual(len(bp.pick(rows)), bp.GALLERIES)


class Edits(unittest.TestCase):
    def test_remove_and_add(self):
        spots = [bp.to_spot(row()), bp.to_spot(row(name="Old Bar"))]
        edits = {"remove": ["Old Bar"], "add": [{"n": "New Place", "t": "dinner", "lat": 38.71, "lon": -9.14, "f": ["cozy", "evil"]}]}
        out = bp.apply_edits(spots, edits)
        self.assertEqual([s["n"] for s in out], ["New Place", "Bar Alto"])
        self.assertEqual(out[0]["f"], ["cozy"])

    def test_bad_additions_are_dropped(self):
        bad = [{"n": "", "t": "dinner", "lat": 1, "lon": 1}, {"n": "X", "t": "brunch", "lat": 1, "lon": 1},
               {"n": "X", "t": "dinner", "lat": True, "lon": 1}, {"n": "X", "t": "dinner", "lat": 99, "lon": 1}, "nope"]
        self.assertEqual(bp.apply_edits([], {"add": bad}), [])


class ChooseCities(unittest.TestCase):
    def test_caps_suburbs_and_packs(self):
        rows = [("Lisboa", "Lisbon", "PT", 545000, 38.72, -9.14, "city"),
                ("Amadora", "Amadora", "PT", 175000 + 300000, 38.76, -9.23, "city"),   # 9 km away: a suburb
                ("Brooklyn", "Brooklyn", "US", 2600000, 40.65, -73.95, "city"),        # inside the NYC pack
                ("Porto", "Porto", "PT", 400000, 41.15, -8.61, "city"),
                ("Sintra District", "Sintra District", "PT", 380000, 38.8, -9.38, "city")]
        ids = [c["id"] for c in bp.choose_cities(rows)]
        self.assertEqual(ids, ["lisbon-pt", "porto-pt"])

    def test_inputs_from_pull_requests_are_checked(self):
        import json
        bp.check_inputs(json.loads(bp.CITIES.read_text(encoding="utf-8")), json.loads(bp.EDITS.read_text(encoding="utf-8")))
        for cities, edits in (([{"id": "../x", "name": "X", "lat": 1, "lon": 1, "km": 2}], {}),
                              ([{"id": "ok-xx", "name": "X", "lat": float("nan"), "lon": 1, "km": 2}], {}),
                              ([], {"ok-xx": ["not", "an", "object"]})):
            with self.assertRaises(SystemExit):
                bp.check_inputs(cities, edits)

    def test_every_city_file_entry_is_valid(self):
        import json
        cities = json.loads(bp.CITIES.read_text(encoding="utf-8"))
        ids = [c["id"] for c in cities]
        self.assertEqual(len(ids), len(set(ids)))
        for c in cities:
            self.assertRegex(c["id"], r"^[a-z][a-z-]{1,23}$")
            self.assertTrue(-85 <= c["lat"] <= 85 and -180 <= c["lon"] <= 180 and 1.5 <= c["km"] <= 4)


if __name__ == "__main__":
    unittest.main()
