"""Unit tests for tools/new_city.py. No network, no files written. Run with `python3 -m unittest -v`."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build_spots as b  # noqa: E402
import new_city as nc  # noqa: E402

PARIS = {"lat": "48.8588897", "lon": "2.3200410", "name": "Paris", "boundingbox": ["48.8155755", "48.9021560", "2.2241220", "2.4697602"],
         "address": {"city": "Paris", "country": "France", "country_code": "fr"}}
PLACES = [{"name": "Le Marais", "name_en": None, "wikidata": "Q1", "lat": 48.859, "lon": 2.362},
          {"name": "Belleville", "name_en": None, "wikidata": None, "lat": 48.872, "lon": 2.377},
          {"name": "Montmartre", "name_en": None, "wikidata": "Q2", "lat": 48.886, "lon": 2.341},
          {"name": "le marais", "name_en": None, "wikidata": None, "lat": 48.86, "lon": 2.36}]


class Slug(unittest.TestCase):
    def test_accents_and_spaces(self):
        self.assertEqual(nc.slug("São Paulo"), "sao-paulo")

    def test_non_latin_name_gives_nothing(self):
        self.assertEqual(nc.slug("東京"), "")


class CityBox(unittest.TestCase):
    def test_reorders_to_south_west_north_east(self):
        self.assertEqual(nc.city_box(PARIS), [48.816, 2.224, 48.902, 2.47])

    def test_huge_metro_is_cut_to_its_center(self):
        big = {**PARIS, "boundingbox": ["20", "40", "130", "150"], "lat": "35.68", "lon": "139.76"}
        s, w, n, e = nc.city_box(big)
        self.assertLess((n - s) * (e - w), 1.0)


class PickHoods(unittest.TestCase):
    def test_known_places_first_and_no_duplicates(self):
        hoods = nc.pick_hoods(PLACES, (48.86, 2.34))
        labels = [h["label"] for h in hoods]
        self.assertEqual(labels[:2], ["Le Marais", "Montmartre"])
        self.assertEqual(len(labels), 3)
        self.assertEqual(hoods[0]["match"], ["Le Marais"])


class BuildCity(unittest.TestCase):
    def test_paris(self):
        c = nc.build_city(PARIS, PLACES, "paris", None)
        self.assertEqual((c["tz"], c["currency"], c["units"], c["search"]), ("Europe/Paris", "€", "c", "Paris, France"))
        self.assertEqual(c["picks"], [])

    def test_passes_the_daily_builds_checks(self):
        c = nc.build_city(PARIS, PLACES, "paris", None)
        s, w, n, e = c["bbox"]
        self.assertTrue(b.CITY_ID.match(c["id"]) and s < n and w < e and (n - s) * (e - w) < 1.0)

    def test_multi_timezone_country_needs_tz(self):
        austin = {**PARIS, "address": {"city": "Austin", "country": "United States", "country_code": "us"}}
        with self.assertRaises(ValueError):
            nc.build_city(austin, [], "austin", None)
        c = nc.build_city(austin, [], "austin", "America/Chicago")
        self.assertEqual((c["units"], c["currency"]), ("f", "$"))

    def test_rejects_a_box_the_daily_build_would_refuse(self):
        dot = {**PARIS, "boundingbox": ["10", "10", "10", "10"], "lat": "10", "lon": "10"}
        with self.assertRaises(ValueError):
            nc.build_city(dot, [], "dot", None)

    def test_rejects_bad_id_and_tz(self):
        with self.assertRaises(ValueError):
            nc.build_city(PARIS, [], "Paris!", None)
        with self.assertRaises(ValueError):
            nc.build_city(PARIS, [], "paris", "not a zone")


if __name__ == "__main__":
    unittest.main()
