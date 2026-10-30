"""Starts a city pack from its name: `python3 tools/new_city.py "Paris"`.

Looks the city up on OpenStreetMap (Nominatim for the outline, Overpass for neighborhood names), writes
cities/<id>/city.json and an empty spots.json, and adds the city to cities/index.json. Then add 10 to 30 hand
picks, run `python3 tools/format_city.py`, and open a pull request. The daily build fills spots.json.

Options: --id paris (folder name), --tz Europe/Paris (needed for countries with several time zones),
--dry-run (print the city file, write nothing). Standard library only.
"""
import argparse
import json
import math
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from format_city import dump  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "plan-committee-new-city/1.0 (+https://github.com/marinasofia/plan-committee)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"

EURO = set("at be cy de ee es fi fr gr hr ie it lt lu lv mt nl pt si sk".split())
CURRENCY = {"us": "$", "ca": "$", "au": "$", "nz": "$", "mx": "$", "sg": "$", "hk": "$", "gb": "£", "jp": "¥",
            "cn": "¥", "in": "₹", "kr": "₩", "th": "฿", "ph": "₱", "tr": "₺", "il": "₪", "ng": "₦", "vn": "₫",
            "ua": "₴", "br": "R$", "za": "R"}
# countries with one time zone; anywhere else, pass --tz
TZ = {"gb": "Europe/London", "ie": "Europe/Dublin", "fr": "Europe/Paris", "de": "Europe/Berlin", "es": "Europe/Madrid",
      "it": "Europe/Rome", "nl": "Europe/Amsterdam", "be": "Europe/Brussels", "pt": "Europe/Lisbon", "ch": "Europe/Zurich",
      "at": "Europe/Vienna", "se": "Europe/Stockholm", "no": "Europe/Oslo", "dk": "Europe/Copenhagen",
      "fi": "Europe/Helsinki", "pl": "Europe/Warsaw", "cz": "Europe/Prague", "hu": "Europe/Budapest", "gr": "Europe/Athens",
      "tr": "Europe/Istanbul", "jp": "Asia/Tokyo", "kr": "Asia/Seoul", "cn": "Asia/Shanghai", "in": "Asia/Kolkata",
      "sg": "Asia/Singapore", "hk": "Asia/Hong_Kong", "th": "Asia/Bangkok", "vn": "Asia/Ho_Chi_Minh", "ph": "Asia/Manila",
      "il": "Asia/Jerusalem", "ae": "Asia/Dubai", "za": "Africa/Johannesburg", "ng": "Africa/Lagos", "eg": "Africa/Cairo",
      "ke": "Africa/Nairobi", "ma": "Africa/Casablanca", "ar": "America/Argentina/Buenos_Aires", "co": "America/Bogota",
      "pe": "America/Lima", "cl": "America/Santiago", "nz": "Pacific/Auckland"}
TZ_RE = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+){1,2}$")  # what the app accepts
ID_RE = re.compile(r"^[a-z][a-z-]{1,23}$")


def slug(name: str) -> str:
    """'São Paulo' -> 'sao-paulo' (ASCII letters and dashes, what folder names and the app accept)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z]+", "-", s).strip("-")[:24].strip("-")
    return s if ID_RE.match(s) else ""


def city_box(hit: dict) -> list[float]:
    """Nominatim's boundingbox is [south, north, west, east] as strings. The daily build only accepts a box
    under 1 square degree, so a huge metro (or one with far islands) is cut to its center."""
    s, n, w, e = (float(x) for x in hit["boundingbox"])
    lat, lon = float(hit["lat"]), float(hit["lon"])
    if (n - s) * (e - w) >= 0.9:
        dy, dx = 0.25, 0.35
        s, n, w, e = lat - dy, lat + dy, lon - dx, lon + dx
    return [round(s, 3), round(w, 3), round(n, 3), round(e, 3)]


def pick_hoods(places: list[dict], center: tuple[float, float], n: int = 9) -> list[dict]:
    """Up to n neighborhood chips: places with a Wikidata entry first (the ones people know), nearest first."""
    def dist(p):
        return math.hypot(p["lat"] - center[0], (p["lon"] - center[1]) * math.cos(math.radians(center[0])))
    seen, out = set(), []
    for p in sorted(places, key=lambda p: (not p.get("wikidata"), dist(p))):
        label = (p.get("name_en") or p["name"]).strip()[:30]
        if label and label.lower() not in seen:
            seen.add(label.lower())
            local = p["name"].strip()[:30]  # spots carry the local name ("7e Arrondissement"), the chip the English one
            out.append({"label": label, "match": [label] + ([local] if local.lower() != label.lower() else [])})
        if len(out) == n:
            break
    return out


def build_city(hit: dict, places: list[dict], city_id: str, tz: str | None) -> dict:
    """The city.json for one Nominatim result plus OSM neighborhoods. Raises ValueError with a fix when unsure."""
    addr = hit.get("address") or {}
    cc = str(addr.get("country_code") or "").lower()
    name = str(addr.get("city") or addr.get("town") or hit.get("name") or "").strip()[:40]
    if not name:
        raise ValueError("Nominatim gave no city name; try a more specific name, like 'Paris, France'")
    tz = tz or TZ.get(cc)
    if not tz:
        raise ValueError(f"{name} is in a country with several time zones: pass --tz, like --tz America/Chicago")
    if not TZ_RE.match(tz):
        raise ValueError(f"--tz {tz!r} doesn't look like a time zone name (like Europe/Paris)")
    if not ID_RE.match(city_id):
        raise ValueError("--id must be 2 to 24 lowercase letters or dashes, like 'sao-paulo'")
    lat, lon = round(float(hit["lat"]), 3), round(float(hit["lon"]), 3)
    country = str(addr.get("country") or "").strip()
    return {
        "id": city_id, "name": name, "short": name[:20], "search": f"{name}, {country}" if country else name,
        "bbox": city_box(hit), "center": [lat, lon], "tz": tz, "units": "f" if cc in ("us", "lr", "mm") else "c",
        "currency": CURRENCY.get(cc) or ("€" if cc in EURO else "$"), "sources": {}, "areas": [], "stayIn": [],
        "hoods": pick_hoods(places, (lat, lon)), "picks": [],
    }


def get_json(url: str, data: bytes | None = None) -> object:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA), timeout=180) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # Overpass answers 429/504 when busy
            if attempt == 3:
                raise SystemExit(f"{url.split('/')[2]} didn't answer ({type(e).__name__}); try again in a few minutes")
            time.sleep(10 * (attempt + 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help='the city, like "Paris" or "Portland, Oregon"')
    ap.add_argument("--id", help="folder name (default: from the name)")
    ap.add_argument("--tz", help="time zone, like America/Chicago (needed in countries with several)")
    ap.add_argument("--dry-run", action="store_true", help="print the city file, write nothing")
    a = ap.parse_args()

    q = urllib.parse.urlencode({"q": a.name, "format": "jsonv2", "limit": 1, "addressdetails": 1, "accept-language": "en"})
    hits = get_json(f"{NOMINATIM}?{q}")
    if not hits:
        raise SystemExit(f"OpenStreetMap doesn't know {a.name!r}. Try the English name plus the country.")
    hit = hits[0]
    s, n, w, e = (float(x) for x in hit["boundingbox"])
    query = (f'[out:json][timeout:120];node["place"~"^(suburb|neighbourhood|quarter)$"]["name"]({s},{w},{n},{e});'
             "out tags center 400;")
    els = get_json(OVERPASS, urllib.parse.urlencode({"data": query}).encode()).get("elements", [])
    places = [{"name": t["name"], "name_en": t.get("name:en"), "wikidata": t.get("wikidata"), "lat": el["lat"], "lon": el["lon"]}
              for el in els if (t := el.get("tags") or {}).get("name") and "lat" in el]
    city_id = a.id or slug(str((hit.get("address") or {}).get("city") or hit.get("name") or a.name))
    try:
        city = build_city(hit, places, city_id, a.tz)
    except ValueError as err:
        raise SystemExit(str(err))
    if a.dry_run:
        print(dump(city))
        return

    folder = ROOT / "cities" / city_id
    if folder.exists():
        raise SystemExit(f"cities/{city_id} already exists; pick another --id")
    folder.mkdir(parents=True)
    (folder / "city.json").write_text(dump(city), encoding="utf-8")
    (folder / "spots.json").write_text('{"spots": []}\n', encoding="utf-8")
    index_path = ROOT / "cities" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["cities"].append({"id": city_id, "name": city["name"]})
    rows = ",\n".join("    " + json.dumps(c, ensure_ascii=False) for c in index["cities"])  # one city per line, like the file
    index_path.write_text('{\n  "cities": [\n' + rows + "\n  ]\n}\n", encoding="utf-8")
    print(f"Wrote cities/{city_id}/ with {len(city['hoods'])} neighborhoods. Next: add 10 to 30 hand picks to "
          f"cities/{city_id}/city.json, run python3 tools/format_city.py, and open a pull request.")


if __name__ == "__main__":
    main()
