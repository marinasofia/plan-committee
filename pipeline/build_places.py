"""Builds the open place lists for "Somewhere else" cities from Overture Maps Places (not OpenStreetMap).

Overture (overturemaps.org) publishes a free global places dataset every month: restaurants, bars and venues
from Meta, Microsoft, Foursquare and AllThePlaces, under open licenses (CDLA-Permissive-2.0, Apache-2.0, CC0).
For every city in places/cities.json this reads a box around the center straight from Overture's public files
on Amazon S3 (no account), keeps the places that make a night out, applies places/edits.json (corrections
anyone can send by pull request), and writes one small JSON file per city plus index.json and the license notices.
The GitHub Action publishes them on the `places-data` branch, served by jsDelivr, and the app reads them.

  python3 pipeline/build_places.py --out out                 # build every city (needs: pip install duckdb)
  python3 pipeline/build_places.py --out out --only lisbon-pt
  python3 pipeline/build_places.py --refresh-cities          # rebuild places/cities.json from Overture's city list

The daily pipeline (build_spots.py) stays standard library only; this monthly one needs DuckDB to read the
Parquet files. The transform functions below are pure Python and unit tested without DuckDB.
"""
import argparse
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_spots import CHAIN_WORDS, norm  # noqa: E402  (shared chain list and name normalizer)

ROOT = Path(__file__).resolve().parent.parent
CITIES = ROOT / "places" / "cities.json"
EDITS = ROOT / "places" / "edits.json"
S3 = "s3://overturemaps-us-west-2/release"
TYPES = ("dinner", "drinks", "late", "free")
TAGS = {"romantic", "cozy", "fancy", "chaotic", "artsy", "lowkey", "dancing", "nerdy", "rooftop", "music", "views",
        "photo", "dessert", "wait", "loud", "quiet", "cash", "veg", "late"}
CAPS = {"dinner": 320, "drinks": 230, "late": 100, "free": 60}  # per city, best first: about 120 KB, 35 KB gzipped
GALLERIES = 20  # Overture lists every commercial gallery; parks and viewpoints come first

# Overture taxonomy -> the app's types. Checked in order against the place's category and its parents.
DRINKS = {"bar", "cocktail_bar", "wine_bar", "pub", "irish_pub", "beer_bar", "beer_garden", "brewery", "lounge", "sports_bar",
          "dive_bar", "gay_bar", "hotel_bar", "speakeasy", "gastropub", "sake_bar", "whiskey_bar", "rooftop_bar", "piano_bar",
          "tiki_bar", "cidery", "winery", "brewpub"}
LATE = {"dance_club", "night_club", "nightlife_venue", "music_venue", "jazz_and_blues_venue", "comedy_club", "karaoke_venue",
        "movie_theater", "theatre_venue", "performing_arts_venue", "opera_and_ballet", "arcade", "bowling_alley", "escape_room",
        "ice_cream_shop", "dessert_shop", "gelato_shop", "museum", "art_museum", "history_museum", "science_museum",
        "salsa_club", "billiard_hall", "planetarium", "observatory", "aquarium"}
FREE = {"park", "garden", "botanical_garden", "beach", "scenic_viewpoint", "lookout", "public_plaza", "art_gallery", "street_art",
        "pier", "promenade"}
SKIP = re.compile(r"fast_food|burger|kebab|chicken|sandwich|bagel|donut|juice|smoothie|bubble_tea|coffee|cafe|bakery|deli|"
                  r"food_truck|salad|candy|chocolatier|tea_room|cafeteria|strip_club|adult|hookah|breakfast|brunch|festival", re.I)
CUISINE = [("pizza", "pizza"), ("italian", "italian"), ("steak", "steak"), ("french", "french"),
           (r"japanese|sushi|ramen|chinese|thai|korean|vietnamese|indian|asian|dim_sum|noodle|nepal|malaysian|indonesian|filipino|"
            r"taiwanese|cantonese|szechuan", "asian"),
           (r"mexican|taco|peruvian|brazilian|latin|argentin|colombian|cuban|caribbean", "latin"),
           (r"american|barbecue|diner|southern|cajun|bar_and_grill", "american"),
           (r"greek|lebanese|turkish|spanish|tapas|mediterranean|middle_eastern|moroccan|israeli|portuguese|persian", "mediterranean"),
           (r"seafood|fish|oyster", "seafood"), (r"vegan|vegetarian", "veg"),
           (r"british|german|polish|european|austrian|irish|russian|georgian|czech|hungarian|gastropub|brasserie", "comfort")]
VIBES = {"cocktail_bar": ["fancy"], "speakeasy": ["fancy", "cozy"], "wine_bar": ["cozy", "romantic"], "pub": ["lowkey", "cozy"],
         "irish_pub": ["lowkey", "loud"], "dive_bar": ["lowkey", "chaotic"], "sports_bar": ["loud"], "beer_garden": ["lowkey"],
         "hotel_bar": ["fancy"], "rooftop_bar": ["rooftop", "views"], "lounge": ["cozy"], "dance_club": ["dancing", "loud", "late"],
         "night_club": ["dancing", "loud", "late"], "salsa_club": ["dancing"], "music_venue": ["music"],
         "jazz_and_blues_venue": ["music", "cozy"], "piano_bar": ["music"], "karaoke_venue": ["chaotic", "loud"],
         "comedy_club": ["chaotic"], "arcade": ["nerdy", "chaotic"], "escape_room": ["nerdy"], "movie_theater": ["nerdy"],
         "theatre_venue": ["artsy"], "performing_arts_venue": ["artsy"], "opera_and_ballet": ["artsy", "fancy"],
         "museum": ["artsy", "quiet"], "art_museum": ["artsy", "quiet"], "art_gallery": ["artsy"], "street_art": ["artsy", "photo"],
         "ice_cream_shop": ["dessert"], "gelato_shop": ["dessert"], "dessert_shop": ["dessert"], "scenic_viewpoint": ["views", "photo"],
         "lookout": ["views", "photo"], "garden": ["romantic", "quiet"], "botanical_garden": ["romantic", "quiet"],
         "park": ["lowkey"], "beach": ["views"], "steakhouse": ["fancy"], "french_restaurant": ["romantic"],
         "vegan_restaurant": ["veg"], "vegetarian_restaurant": ["veg"], "observatory": ["nerdy", "views"], "planetarium": ["nerdy"]}
CTRL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")  # control and bidi characters


def clean_text(s: object, n: int) -> str:
    return CTRL.sub("", str(s or "")).strip()[:n]


def kind_of(primary: str | None, hierarchy: list[str] | None) -> str | None:
    """dinner / drinks / late / free, or None for anything that isn't a night out."""
    p = primary or ""
    chain = [p, *(hierarchy or [])]
    if SKIP.search(p):
        return None
    if any(c in DRINKS for c in chain):
        return "drinks"
    if any(c in LATE for c in chain):
        return "late"
    if any(c in FREE for c in chain) or "viewpoint" in p:
        return "free"
    if "restaurant" in chain or p.endswith("_restaurant") or p in ("steakhouse", "tapas_bar", "bistro", "brasserie", "diner"):
        return "dinner"
    return None


def to_spot(row: dict) -> dict | None:
    """One Overture place -> the app's spot format, or None. Never trusts the input: every field is typed and capped."""
    name = clean_text(row.get("name"), 80)
    lat, lon = row.get("lat"), row.get("lon")
    if not name or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if row.get("status") not in (None, "open") or (row.get("confidence") or 0) < 0.6:
        return None
    if row.get("brand") or any(w in name.lower() for w in CHAIN_WORDS) or re.search(r"festival|headquarters|\bhq\b", name, re.I):
        return None  # chains, and events or offices filed as venues
    primary = str(row.get("primary") or "")
    t = kind_of(primary, row.get("hierarchy"))
    if not t:
        return None
    cats = [primary, *(row.get("hierarchy") or [])]
    tags = sorted({v for c in cats for v in VIBES.get(c, [])} | ({"rooftop", "views"} if "rooftop" in name.lower() else set()))
    cuisine = next((c for pat, c in CUISINE if re.search(pat, primary)), "") if t == "dinner" else ""
    web = str(row.get("web") or "")
    return {"n": name, "t": t, "h": "", "p": 0 if t == "free" else 3 if primary in ("steakhouse", "opera_and_ballet") else 2,
            "c": cuisine, "f": [x for x in tags if x in TAGS], "v": clean_text(primary.replace("_", " "), 40),
            "web": web[:200] if re.match(r"^https?://[^\s<>\"']+$", web) else "",
            "lat": round(float(lat), 5), "lon": round(float(lon), 5),
            "_score": float(row.get("confidence") or 0) + (0.3 if web else 0) + (0.4 if t == "free" and "gallery" not in primary else 0),
            "_gallery": "gallery" in primary or primary == "street_art"}


def pick(rows: list[dict]) -> list[dict]:
    """The city's list: no chains (a name with 3+ places in town is one), one spot per name, best per type first."""
    spots = [s for s in map(to_spot, rows) if s]
    counts: dict[str, int] = {}
    for s in spots:
        counts[norm(s["n"])] = counts.get(norm(s["n"]), 0) + 1
    out, seen, per, galleries = [], set(), dict.fromkeys(TYPES, 0), 0
    for s in sorted(spots, key=lambda s: -s["_score"]):
        k = norm(s["n"])
        if counts[k] >= 3 or k in seen or per[s["t"]] >= CAPS[s["t"]] or (s["_gallery"] and galleries >= GALLERIES):
            continue
        galleries += s["_gallery"]
        seen.add(k)
        per[s["t"]] += 1
        out.append({k2: v for k2, v in s.items() if not k2.startswith("_")})
    return out


def clean_edit(s: object) -> dict | None:
    """A place someone added by pull request: same shape and limits as everything else."""
    if not isinstance(s, dict) or s.get("t") not in TYPES:
        return None
    name, lat, lon = clean_text(s.get("n"), 80), s.get("lat"), s.get("lon")
    if not name or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return None
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        return None
    p = s.get("p")
    web = str(s.get("web") or "")
    return {"n": name, "t": s["t"], "h": clean_text(s.get("h"), 40), "p": p if isinstance(p, int) and 0 <= p <= 4 else 2,
            "c": clean_text(s.get("c"), 20), "f": [x for x in s.get("f") or [] if x in TAGS][:5], "v": clean_text(s.get("v"), 90),
            "web": web[:200] if re.match(r"^https?://[^\s<>\"']+$", web) else "", "lat": round(lat, 5), "lon": round(lon, 5)}


def apply_edits(spots: list[dict], edits: dict) -> list[dict]:
    """places/edits.json for one city: {"remove": ["Closed Bar"], "add": [{spot}]}. Additions win over Overture."""
    drop = {norm(n) for n in edits.get("remove") or [] if isinstance(n, str)}
    added = [s for s in map(clean_edit, edits.get("add") or []) if s]
    keep = {norm(s["n"]) for s in added}
    return added + [s for s in spots if norm(s["n"]) not in drop | keep]


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", "-", s).strip("-")[:20].strip("-")


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = math.pi / 180
    x = math.sin((b[0] - a[0]) * r / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


SKIP_DIVISION = re.compile(r"borough|metropolitan|municipality|hromada|district|town$|\bcounty\b", re.I)
PACKS = [(40.73, -73.99), (51.51, -0.12)]  # NYC and London have their own curated packs
CAP = {"US": 45, "CN": 12, "IN": 12}


def choose_cities(rows: list[tuple]) -> list[dict]:
    """Overture's localities (name, English name, country, population, lat, lon, class) -> the cities we build:
    biggest first, a cap per country so the list covers the world, no suburb of a city already on it."""
    out: list[dict] = []
    per: dict[str, int] = {}
    for name, en, cc, pop, lat, lon, cls in sorted(rows, key=lambda r: -(r[3] or 0)):
        label = clean_text(en or name, 40)
        if cls != "city" or not label or SKIP_DIVISION.search(label) or not cc or lat is None:
            continue
        if per.get(cc, 0) >= CAP.get(cc, 10) or any(km_between((lat, lon), p) < 30 for p in PACKS):
            continue
        if any(km_between((lat, lon), (c["lat"], c["lon"])) < 15 for c in out):
            continue
        sid = slug(label)
        if len(sid) < 2:
            continue
        per[cc] = per.get(cc, 0) + 1
        out.append({"id": f"{sid}-{cc.lower()}", "name": label, "cc": cc.lower(), "lat": round(lat, 3), "lon": round(lon, 3),
                    "km": 3.0 if pop >= 5_000_000 else 2.5 if pop >= 1_000_000 else 2.0})
    return sorted(out, key=lambda c: c["id"])


NOTICE = """# Open place lists for The Plan Committee

One file per city, built every month from Overture Maps Places (https://overturemaps.org) plus corrections
people send to places/edits.json in https://github.com/marinasofia/plan-committee. Anyone can use them.

Licenses: the places come from Overture's sources under CDLA-Permissive-2.0, Apache-2.0 (Foursquare
Open Source Places, Copyright 2024 Foursquare Labs, Inc.; changes: filtered to nights out and reformatted)
and CC0-1.0 (AllThePlaces). Keep this notice and credit "Overture Maps Foundation" when you reuse them.
The city list comes from Overture's divisions, which are derived from OpenStreetMap (ODbL, © OpenStreetMap contributors).
"""


def latest_release(con) -> str:
    rows = con.execute(f"SELECT DISTINCT regexp_extract(file, 'release/([^/]+)/', 1) r FROM glob('{S3}/*/theme=places/type=place/*') "
                       "ORDER BY r DESC LIMIT 1").fetchall()
    return rows[0][0]


def connect():
    import duckdb  # only this monthly build needs it
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    return con


def city_rows(con, src: str, city: dict) -> list[dict]:
    dy = city["km"] / 111
    dx = dy / math.cos(math.radians(city["lat"]))
    q = f"""SELECT names.primary AS name, confidence, websites[1] AS web, coalesce(brand.wikidata, brand.names.primary) AS brand,
              operating_status AS status, taxonomy.primary AS "primary", taxonomy.hierarchy AS hierarchy, bbox.ymin AS lat, bbox.xmin AS lon
            FROM read_parquet('{src}') WHERE bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?"""
    cur = con.execute(q, [city["lon"] - dx, city["lon"] + dx, city["lat"] - dy, city["lat"] + dy])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def build(out: Path, only: str | None) -> None:
    cities = json.loads(CITIES.read_text(encoding="utf-8"))
    edits = json.loads(EDITS.read_text(encoding="utf-8")) if EDITS.exists() else {}
    con = connect()
    release = latest_release(con)
    src = f"{S3}/{release}/theme=places/type=place/*"
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for c in cities:
        if only and c["id"] != only:
            continue
        t = time.time()
        spots = apply_edits(pick(city_rows(con, src, c)), edits.get(c["id"]) or {})
        (out / f"{c['id']}.json").write_text(json.dumps({"v": 1, "release": release, "spots": spots}, ensure_ascii=False,
                                                        separators=(",", ":")), encoding="utf-8")
        index.append({k: c[k] for k in ("id", "name", "cc", "lat", "lon")} | {"n": len(spots)})
        print(f"{c['id']}: {len(spots)} places in {time.time() - t:.1f}s", flush=True)
    (out / "index.json").write_text(json.dumps({"v": 1, "release": release, "cities": index}, ensure_ascii=False,
                                               separators=(",", ":")), encoding="utf-8")
    (out / "README.md").write_text(NOTICE, encoding="utf-8")


def refresh_cities() -> None:
    con = connect()
    release = latest_release(con)
    rows = con.execute(f"""SELECT names.primary, coalesce(names.common['en'], names.primary), country, population,
                             bbox.ymin, bbox.xmin, class FROM read_parquet('{S3}/{release}/theme=divisions/type=division/*')
                           WHERE subtype = 'locality' AND population >= 300000""").fetchall()
    cities = choose_cities(rows)
    rows_json = ",\n".join("  " + json.dumps(c, ensure_ascii=False) for c in cities)
    CITIES.write_text("[\n" + rows_json + "\n]\n", encoding="utf-8")
    print(f"places/cities.json: {len(cities)} cities from Overture {release}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--only", help="build one city id")
    ap.add_argument("--refresh-cities", action="store_true")
    a = ap.parse_args()
    refresh_cities() if a.refresh_cities else build(a.out, a.only)


if __name__ == "__main__":
    main()
