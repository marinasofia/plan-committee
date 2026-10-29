"""
Grows spots.json automatically. Runs on GitHub Actions (see .github/workflows/update-spots.yml).

1. Pulls every NYC restaurant inspected in the last 12 months (NYC Open Data, free, no key).
   A place that stops getting inspected has almost certainly closed, so it drops out.
2. Pulls bars, music venues, museums, cinemas, parks and viewpoints from OpenStreetMap (free, no key).
3. Keeps restaurants that OpenStreetMap also knows with a website or opening hours (a signal the place
   is real and notable), removes chains, fast food and the hand picked spots already in index.html.
4. Asks a free AI (Groq or Gemini key from repo secrets) to tag new places in batches:
   type, price, cuisine, vibe tags, a short why. The AI must say known:false for places it does not
   recognize; those are skipped so it never invents vibes for places it has never heard of.
   Results are cached in data/tagged.json, so each place is only tagged once.
5. Optionally reads anonymous usage counts (picks, saves, vetoes) from the Cloudflare Worker and
   stores a popularity score so loved places rank higher.
6. Writes spots.json, which the app loads on every visit.

Standard library only. Env vars: GROQ_API_KEY, GEMINI_API_KEY (either or both), STATS_URL (optional),
MAX_BATCHES (default 40 per run, to stay inside free daily limits), BATCH_SIZE (default 25).
"""
import datetime as dt
import gzip
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "tagged.json"
BLOCKLIST = ROOT / "data" / "blocklist.txt"
CITIES = ROOT / "cities"

MAX_BATCHES = int(os.environ.get("MAX_BATCHES", "40"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "25"))
UA = {"User-Agent": "plan-committee-spot-updater/1.0 (github actions)"}

CUISINES = ["italian", "pizza", "steak", "french", "asian", "latin", "comfort", "american", "mediterranean", "seafood", "veg"]
TAGS = ["romantic", "cozy", "fancy", "chaotic", "artsy", "lowkey", "dancing", "nerdy",
        "rooftop", "music", "views", "photo", "dessert", "wait", "loud", "quiet", "cash", "veg", "late"]

CHAIN_WORDS = ["mcdonald", "burger king", "wendy's", "subway", "dunkin", "starbucks", "chipotle", "taco bell",
               "kfc", "popeyes", "domino's", "papa john", "pizza hut", "little caesar", "panera", "sweetgreen",
               "just salad", "chick-fil-a", "five guys", "white castle", "applebee", "olive garden", "red lobster",
               "ihop", "denny's", "cava", "pret a manger", "le pain quotidien", "7-eleven", "halal guys", "wingstop",
               "jersey mike", "jimmy john", "potbelly", "qdoba", "panda express", "tim hortons", "insomnia cookies",
               "crumbl", "joe & the juice", "blue bottle", "bluestone lane", "gregorys coffee", "pinkberry",
               "16 handles", "dos toros", "baskin", "carvel", "krispy kreme", "auntie anne", "cinnabon", "sbarro",
               "raising cane", "dig ", "fresh&co", "chopt", "maman", "paris baguette", "tous les jours", "wetzel",
               "nathan's famous", "the habit", "smashburger", "jamba", "playa bowls", "cold stone", "golden krust",
               "crown fried", "kennedy fried", "great wall", "china wok", "dallas bbq", "bareburger", "sophie's cuban"]
SKIP_CUISINES = ["donuts", "hotdogs", "juice", "smoothies", "bagels", "pretzels", "sandwiches", "chicken",
                 "fruits/vegetables", "nuts/confectionary", "soups", "salads", "not listed", "bottled beverages",
                 "hamburgers", "pancakes/waffles", "coffee/tea", "bakery products/desserts", "frozen desserts"]
BORO = {"Manhattan": "M", "Brooklyn": "BK", "Queens": "Q"}


def log(*a):
    print(*a, flush=True)


def get_json(url, data=None, headers=None, timeout=180, tries=4):
    req = urllib.request.Request(url, data=data, headers={**UA, "Accept-Encoding": "gzip", **(headers or {})})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == tries - 1:
                raise
        except (OSError, EOFError, http.client.HTTPException, json.JSONDecodeError):  # dropped connection, cut off response
            if attempt == tries - 1:
                raise
        log(f"  retrying {url.split('?')[0]} ({attempt + 1})")
        time.sleep(30 * 2 ** attempt)  # Overpass asks for exponential backoff when busy


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("&", "and"))


def nice_name(s):
    """Inspection data is ALL CAPS. Turn 'JOE'S PIZZA' into "Joe's Pizza"."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if s.upper() != s:
        return s
    small = {"and", "of", "the", "de", "la", "le", "di", "da", "on", "at", "in", "a"}
    words = []
    for i, w in enumerate(s.lower().split(" ")):
        words.append(w if (i and w in small) else w[:1].upper() + w[1:])
    out = " ".join(words)
    return re.sub(r"'S\b", "'s", out)


def is_chain(name, place=None):
    """Known chain words, or an OSM brand tag (works in every city, no list to maintain)."""
    n = name.lower()
    return bool(place and place.get("chain")) or any(c in n for c in CHAIN_WORDS)


def km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(d))


# ---------------------------------------------------------------- sources
def fetch_inspections():
    since = (dt.date.today() - dt.timedelta(days=365)).isoformat() + "T00:00:00"
    params = {
        "$select": "camis,dba,boro,building,street,zipcode,cuisine_description,latitude,longitude,max(inspection_date) as last",
        "$where": f"inspection_date > '{since}' AND boro in('Manhattan','Brooklyn','Queens')",
        "$group": "camis,dba,boro,building,street,zipcode,cuisine_description,latitude,longitude",
        "$order": "camis",
        "$limit": "1000",
    }
    # page through it in small gzipped pages: big responses tend to get cut off mid download
    rows = []
    while True:
        url = "https://data.cityofnewyork.us/resource/43nn-pn8j.json?" + urllib.parse.urlencode({**params, "$offset": len(rows)})
        page = get_json(url)
        rows += page
        if len(page) < 1000:
            break
    out = {}
    for r in rows:
        try:
            lat, lon = float(r.get("latitude") or 0), float(r.get("longitude") or 0)
        except ValueError:
            continue
        if not lat or not r.get("dba"):
            continue
        out[r["camis"]] = {
            "id": "nyc:" + r["camis"], "name": nice_name(r["dba"]), "boro": BORO.get(r.get("boro"), ""),
            "cuisine": (r.get("cuisine_description") or "").lower(), "lat": lat, "lon": lon,
            "addr": f"{r.get('building', '')} {r.get('street', '')}".strip().title(),
        }
    log(f"inspections: {len(out)} restaurants inspected since {since[:10]}")
    return list(out.values())


OVERPASS = "https://overpass-api.de/api/interpreter"
OSM_QUERY = """
[out:json][timeout:240];
(
  nwr["amenity"~"^(restaurant|bar|pub|biergarten|nightclub|cafe|ice_cream|cinema|theatre|arts_centre|music_venue)$"]["name"](BBOX);
  nwr["tourism"~"^(museum|gallery|viewpoint)$"]["name"](BBOX);
  nwr["leisure"~"^(park|garden)$"]["name"]["wikidata"](BBOX);
);
out center tags;
"""


OSM_KINDS = set(re.findall(r"[a-z_]+", "|".join(re.findall(r'~"\^\(([^)]*)\)\$"', OSM_QUERY))))


BOOKING = re.compile(r"^https://(www\.)?(resy\.com|opentable\.com|exploretock\.com|sevenrooms\.com)/[^\s<>\"']{1,200}$", re.I)


def booking(t):
    """Direct booking page from OSM tags, 'walkin' if OSM says no reservations, else ''."""
    for k in ("reservation:website", "website:booking", "website:reservation", "reservation", "website", "contact:website"):
        v = (t.get(k) or "").strip().replace("http://", "https://", 1)
        if BOOKING.match(v):
            return v
    return "walkin" if t.get("reservation") == "no" else ""


DAYS = ["mo", "tu", "we", "th", "fr", "sa", "su"]


def parse_hours(oh):
    """OSM opening_hours -> 7 lists (Mon..Sun) of [open, close] minutes; close can pass 1440 (after midnight).
    Handles the common forms ("Mo-Fr 11:00-23:00; Sa,Su 10:00-02:00; Mo off", "24/7"). Anything fancier
    (holidays, months, sunset) returns None, which the app treats as "hours unknown", never as closed."""
    oh = (oh or "").strip().lower()
    if not oh or len(oh) > 300:
        return None
    if oh == "24/7":
        return [[[0, 1440]] for _ in DAYS]
    week = [None] * 7
    for rule in re.split(r"\s*(?:;|\|\|)\s*", oh):
        if not rule:
            continue
        if rule.startswith("ph"):
            continue  # public holidays: ignore
        m = re.fullmatch(r"((?:[a-z]{2}(?:-[a-z]{2})?)(?:\s*,\s*[a-z]{2}(?:-[a-z]{2})?)*)?\s*(.*)", rule)
        days_part, times = m.group(1), m.group(2).strip()
        days = set(range(7))
        if days_part:
            days = set()
            for part in re.split(r"\s*,\s*", days_part):
                a, _, b = part.partition("-")
                if a not in DAYS or (b and b not in DAYS):
                    return None
                i, j = DAYS.index(a), DAYS.index(b or a)
                days |= {(i + k) % 7 for k in range((j - i) % 7 + 1)}
        if times in ("off", "closed"):
            spans = []
        else:
            spans = []
            for t in re.split(r"\s*,\s*", times):
                tm = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})|(\d{1,2}):(\d{2})\+", t)
                if not tm:
                    return None
                if tm.group(5):
                    start = int(tm.group(5)) * 60 + int(tm.group(6))
                    end = start + 300  # "open end": assume five hours
                else:
                    start, end = int(tm.group(1)) * 60 + int(tm.group(2)), int(tm.group(3)) * 60 + int(tm.group(4))
                    if end <= start:
                        end += 1440
                if start >= 1440 or end > 2880:
                    return None
                spans.append([start, end])
        for d in days:
            week[d] = spans
    week = [w if w is not None else [] for w in week]
    return week if any(week) else None  # "closed every day" is more likely a bad edit than a real place: treat as unknown


def needs(t):
    """Accessibility and diet info from OSM tags, only when the tag says yes."""
    out = []
    if t.get("wheelchair") == "yes":
        out.append("wheel")
    for tag, key in (("diet:vegan", "vegan"), ("diet:vegetarian", "veg"), ("diet:gluten_free", "gf")):
        if t.get(tag) in ("yes", "only"):
            out.append(key)
    if t.get("wheelchair") == "no":
        out.append("nowheel")
    return out


def fetch_osm(city):
    bbox = ",".join(str(x) for x in city["bbox"])
    data = urllib.parse.urlencode({"data": OSM_QUERY.replace("BBOX", bbox)}).encode()
    j = get_json(OVERPASS, data=data, timeout=300)
    out = []
    for e in j.get("elements", []):
        t = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if not lat or not t.get("name"):
            continue
        if t.get("disused") or t.get("abandoned") or "disused:amenity" in t:
            continue
        kind = next((t[k] for k in ("amenity", "tourism", "leisure") if t.get(k) in OSM_KINDS), "")
        out.append({
            "id": f"osm:{e['type'][0]}{e['id']}", "name": t["name"], "kind": kind, "lat": lat, "lon": lon,
            "cuisine": t.get("cuisine", ""), "website": t.get("website") or t.get("contact:website") or "",
            "hours": t.get("opening_hours", ""), "rooftop": t.get("rooftop") == "yes" or "rooftop" in t["name"].lower(),
            "music": t.get("live_music") == "yes" or kind == "music_venue", "rsv": booking(t),
            "hrs": parse_hours(t.get("opening_hours")), "x": needs(t), "chain": bool(t.get("brand") or t.get("brand:wikidata")),
        })
    log(f"openstreetmap: {len(out)} named places in {city['name']}")
    return out


NTA_URL = "https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson?$limit=1000"


def fetch_neighborhoods():
    """NYC's official neighborhood shapes (2020 Neighborhood Tabulation Areas). Returns locate(lat, lon) -> (boro, hood)."""
    areas = []
    for f in get_json(NTA_URL).get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        polys = g.get("coordinates", []) if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
        rings = [ring for poly in polys for ring in poly]
        if not rings:
            continue
        xs, ys = [x for r in rings for x, y in r], [y for r in rings for x, y in r]
        # "SoHo-Little Italy-Hudson Square" -> "SoHo", "Upper West Side (Central)" -> "Upper West Side"
        areas.append((BORO.get(p.get("boroname"), ""), re.sub(r"\s*\(.*", "", (p.get("ntaname") or "").split("-")[0]).strip(),
                      (min(xs), min(ys), max(xs), max(ys)), rings))
    log(f"neighborhoods: {len(areas)} areas")

    def inside(x, y, rings):  # even-odd rule over all rings, so holes work too
        hit = False
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    hit = not hit
        return hit

    def locate(lat, lon):
        for boro, hood, (x0, y0, x1, y1), rings in areas:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and inside(lon, lat, rings):
                return boro, hood
        return "", ""
    locate.count = len(areas)
    return locate


OSM_SKIP_CUISINE = re.compile(r"coffee|sandwich|bubble_tea|donut|juice|bagel|kebab|fried_chicken|burger|chicken", re.I)


def build_candidates(city, insp, osm, curated, locate):
    """Notable places for one city. With restaurant inspection data (NYC), a restaurant must be both inspected
    recently (so it is open) and on OpenStreetMap with a website or hours. Without it, OSM alone decides."""
    blocked = BLOCKLIST.read_text(encoding="utf-8").splitlines() if BLOCKLIST.exists() else []
    cur = {norm(n) for n in curated + [b for b in blocked if b.strip() and not b.startswith("#")]}
    grid = {}
    for o in osm:
        grid.setdefault((round(o["lat"], 3), round(o["lon"], 3)), []).append(o)

    def nearby(lat, lon):
        for dy in (-0.001, 0, 0.001):
            for dx in (-0.001, 0, 0.001):
                yield from grid.get((round(lat + dy, 3), round(lon + dx, 3)), [])

    cands, used_osm = {}, set()
    for r in insp:
        if is_chain(r["name"]) or norm(r["name"]) in cur or any(s in r["cuisine"] for s in SKIP_CUISINES):
            continue
        k = norm(r["name"])
        match = None
        for o in nearby(r["lat"], r["lon"]):
            ok = norm(o["name"])
            if (ok == k or (len(k) > 4 and (k in ok or ok in k))) and km((r["lat"], r["lon"]), (o["lat"], o["lon"])) < 0.12:
                match = o
                break
        if not match or match["chain"] or not (match["website"] or match["hours"]):
            continue  # not notable enough to show up on OpenStreetMap with details
        used_osm.add(match["id"])
        cands[r["id"]] = {**r, "hood": locate(r["lat"], r["lon"])[1] if locate else "", "kind": match["kind"], "website": match["website"],
                          "rooftop": match["rooftop"], "music": match["music"], "rsv": match["rsv"], "hrs": match["hrs"], "x": match["x"], "osm": match["id"]}
    for o in osm:
        if o["id"] in used_osm or o["kind"] in ("cafe", "ice_cream") or (insp and o["kind"] == "restaurant"):
            continue
        if is_chain(o["name"], o) or norm(o["name"]) in cur or re.search(r"playground|triangle", o["name"], re.I):
            continue
        if o["kind"] in ("restaurant", "bar", "pub", "biergarten", "nightclub") and not (o["website"] or o["hours"]):
            continue
        if o["kind"] == "restaurant" and OSM_SKIP_CUISINE.search(o["cuisine"]):
            continue
        boro, hood = locate(o["lat"], o["lon"]) if locate else ("", "")
        if locate and not boro:
            continue  # outside the city's official areas (the OSM box is a rectangle)
        cands[o["id"]] = {**o, "boro": boro, "hood": hood, "addr": ""}
    log(f"candidates: {len(cands)} notable places in {city['name']} after filters")
    return cands


# ---------------------------------------------------------------- AI tagging
PROMPT = """You tag places in CITY for a date night and friends night planning app.
For each place, decide from your own knowledge. If you do not actually recognize the specific place, return known:false. Never guess vibes for places you don't know.
Return JSON: {"items":[{"id":"...","known":true,"type":"dinner|drinks|late|free|skip","price":0,"cuisine":"...","tags":["..."],"why":"max 8 words","hood":"neighborhood name","boro":"AREAS|other"}]}
type: dinner = restaurant good for a night out, drinks = bar, late = activity or dessert or venue, free = costs nothing to get in, like a park, viewpoint or free museum (paid museums, tours and cinemas are late), skip = not good for a night out (takeout spot, office cafeteria, generic deli, chain).
price: 0 free, 1 CUR, 2 CUR2, 3 CUR3, 4 CUR4 per person.
cuisine (dinner only, else ""): one of CUISINE_LIST
tags: any that clearly apply, from: TAG_LIST
hood: the neighborhood in CITY, like HOODS. boro: AREA_HELP
If the place has closed for good or moved out of that neighborhood, return known:false. Same named places in different neighborhoods are different places.
PLACES (id | name | kind | cuisine hint | address | area | neighborhood):
"""


def prompt_for(city):
    areas = city.get("areas") or []
    cur = city.get("currency") or "$"
    # fixed lists first, then the contributor's text, and no % formatting (a "%" in a city name must not break it)
    base = PROMPT.replace("CUISINE_LIST", ", ".join(CUISINES)).replace("TAG_LIST", ", ".join(TAGS))
    return (base.replace("CITY", city["name"]).replace("AREAS", "|".join(a["code"] for a in areas) or "\"\"")
            .replace("CUR4", cur * 4).replace("CUR3", cur * 3).replace("CUR2", cur * 2).replace("CUR", cur)
            .replace("HOODS", ", ".join(h["label"] for h in city.get("hoods", [])[:4]))
            .replace("AREA_HELP", ", ".join(f'{a["code"]} {a["label"]}' for a in areas) + ", other for anywhere else" if areas
                     else 'leave "" (this city has no areas)'))


class OutOfQuota(Exception):
    pass


_dead = set()


def ai_call(prompt):
    errors = []
    for name, fn in (("GROQ_API_KEY", groq), ("GEMINI_API_KEY", gemini)):
        if not os.environ.get(name) or name in _dead:
            continue
        try:
            return fn(prompt)
        except OutOfQuota as e:
            errors.append(str(e))
        except RuntimeError as e:  # bad key or model gone: skip this provider for the rest of the run
            log("AI provider error, switching:", e)
            _dead.add(name)
            errors.append(str(e))
    raise OutOfQuota("; ".join(errors) or "no AI key set (add GROQ_API_KEY or GEMINI_API_KEY as a repo secret)")


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:  # only the provider's own message, never the raw body (it could echo request details into public logs)
            msg = str(json.loads(e.read().decode()).get("error", {}).get("message", ""))[:200]
        except Exception:
            msg = ""
        if e.code == 429 or e.code >= 500:
            raise OutOfQuota(f"{url.split('/')[2]} {e.code}: {msg}")
        raise RuntimeError(f"{url.split('/')[2]} {e.code}: {msg}")


_groq_model = None


def groq(prompt):
    global _groq_model
    if not _groq_model:
        # Groq retires models often, so pick the biggest current chat model instead of hardcoding one
        _groq_model = os.environ.get("GROQ_MODEL")
        if not _groq_model:
            try:
                j = get_json("https://api.groq.com/openai/v1/models", headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]}, tries=2)
            except Exception as e:
                raise RuntimeError(f"api.groq.com model list: {e}")
            names = [m["id"] for m in j.get("data", []) if m.get("active", True)
                     and not re.search(r"whisper|tts|guard|embed|compound|playai|orpheus|safeguard|vision", m["id"])]
            names.sort(key=lambda n: -max([int(x) for x in re.findall(r"(\d+)b\b", n)] or [0]))
            if not names:
                raise RuntimeError("no Groq chat model found")
            _groq_model = names[0]
            log("groq model:", _groq_model)
    model = _groq_model
    for attempt in range(3):
        try:
            j = post("https://api.groq.com/openai/v1/chat/completions",
                     {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}]},
                     {"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]})
            time.sleep(12)  # free tier tokens per minute
            return j["choices"][0]["message"]["content"]
        except OutOfQuota as e:
            if "per day" in str(e).lower() or attempt == 2:
                raise
            time.sleep(60)


_gem_model = None


def gemini(prompt):
    global _gem_model
    key = os.environ["GEMINI_API_KEY"]
    if not _gem_model:
        _gem_model = os.environ.get("GEMINI_MODEL")
        if not _gem_model:
            try:
                j = get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key}, tries=2)
            except Exception as e:
                raise RuntimeError(f"gemini model list: {e}")
            names = [m["name"].split("/")[-1] for m in j.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]
                     and not re.search(r"image|tts|audio|live|embed|preview|exp|thinking", m["name"])]
            names.sort(key=lambda n: (0 if "lite" in n else 1, -float((re.search(r"gemini-(\d+(\.\d+)?)", n) or [0, "0"])[1])))
            if not names:
                raise OutOfQuota("no free Gemini flash model found")
            _gem_model = names[0]
            log("gemini model:", _gem_model)
    j = post(f"https://generativelanguage.googleapis.com/v1beta/models/{_gem_model}:generateContent",
             {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}, {"x-goog-api-key": key})
    time.sleep(5)
    return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))


def parse_items(text):
    text = re.sub(r"```json|```", "", text).strip()
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        j = json.loads(m.group(0)) if m else {}
    return j.get("items", []) if isinstance(j, dict) else []


def clean_tag(item, cand, city):
    t = item.get("type")
    codes = [a["code"] for a in city.get("areas") or []]
    boro = (cand.get("boro") or item.get("boro") or "") if codes else ""
    if not item.get("known"):
        # the AI hasn't heard of it yet (often a new opening): ask again in RETRY_DAYS instead of never
        return {"skip": True, "unknown": True, "at": dt.date.today().isoformat()}
    if t not in ("dinner", "drinks", "late", "free") or (codes and boro not in codes):
        return {"skip": True, "at": dt.date.today().isoformat()}  # dated, so retry_due never treats it as an old entry
    tags = [x for x in item.get("tags", []) if x in TAGS]
    if cand.get("rooftop") and "rooftop" not in tags:
        tags.append("rooftop")
    if cand.get("music") and "music" not in tags:
        tags.append("music")
    price = item.get("price", 2)
    price = max(0, min(4, int(price))) if str(price).isdigit() else 2
    if t == "free":
        price = 0
    return {"n": cand["name"], "t": t, "h": (cand.get("hood") or item.get("hood") or "")[:30], "b": boro, "p": price,
            "c": item.get("cuisine") if t == "dinner" and item.get("cuisine") in CUISINES else "", "f": tags,
            "v": (item.get("why") or "")[:70], "lat": round(cand["lat"], 5), "lon": round(cand["lon"], 5),
            "web": cand.get("website", "")[:120] if re.match(r"https?://", cand.get("website", ""), re.I) else ""}


RETRY_DAYS = 30
FRESH_PER_CITY = 150
KIND_TYPE = {"restaurant": "dinner", "bar": "drinks", "pub": "drinks", "biergarten": "drinks", "nightclub": "drinks",
             "cinema": "late", "theatre": "late", "music_venue": "late", "arts_centre": "late", "museum": "late", "gallery": "late"}
OSM_CUISINE = {"italian": "italian", "pizza": "pizza", "steak_house": "steak", "french": "french", "japanese": "asian", "chinese": "asian",
               "thai": "asian", "korean": "asian", "vietnamese": "asian", "indian": "asian", "sushi": "asian", "ramen": "asian",
               "mexican": "latin", "peruvian": "latin", "spanish": "mediterranean", "greek": "mediterranean", "mediterranean": "mediterranean",
               "lebanese": "mediterranean", "turkish": "mediterranean", "american": "american", "seafood": "seafood", "vegan": "veg",
               "vegetarian": "veg", "british": "comfort", "diner": "comfort", "bbq": "comfort"}


def retry_due(entry):
    """Places the AI didn't know get another chance after RETRY_DAYS. Old cache entries ({"skip": true} with no
    date) can't tell "unknown" from "not a night out spot", so they are retried once."""
    if not entry.get("skip"):
        return False
    if "at" not in entry:
        return "why" not in entry and len(entry) == 1
    try:
        return entry.get("unknown") and (dt.date.today() - dt.date.fromisoformat(entry["at"])).days >= RETRY_DAYS
    except ValueError:
        return False


SUSPICIOUS = re.compile(r"https?:|www\.|[|<>{}\[\]\\\n\r]|\b(ignore|instruction|prompt|system|always pick|assistant|you are)\b", re.I)


def plain_name(name):
    """OSM names are written by anyone and end up in the agents' prompt: keep short, ordinary names only."""
    return 1 < len(name) <= 60 and not SUSPICIOUS.search(name)


def fresh_find(cand, city):
    """A listing from plain facts for a place the AI doesn't know yet: only well documented restaurants and bars
    (website and opening hours), with no made up vibes. The app shows it as a "fresh find"."""
    t = KIND_TYPE.get(cand.get("kind"))
    if t not in ("dinner", "drinks") or not (cand.get("website") and cand.get("hrs")):
        return None
    codes = [a["code"] for a in city.get("areas") or []]
    if codes and cand.get("boro") not in codes:
        return None
    if not plain_name(cand["name"]):
        return None  # no AI has looked at this one, so the name must look like a real place name
    cuisine = next((OSM_CUISINE[c] for c in re.split(r"[;,]\s*", (cand.get("cuisine") or "").lower()) if c in OSM_CUISINE), "")
    if t == "dinner" and not cuisine:
        return None  # no idea what kind of food: not enough to pitch it
    tags = [x for x, on in (("rooftop", cand.get("rooftop")), ("music", cand.get("music"))) if on]
    return {"n": cand["name"], "t": t, "h": (cand.get("hood") or "")[:30], "b": cand.get("boro", "") if city.get("areas") else "",
            "p": 2, "c": cuisine if t == "dinner" else "", "f": tags, "v": "fresh find, not reviewed yet", "nw": 1,
            "lat": round(cand["lat"], 5), "lon": round(cand["lon"], 5),
            "web": cand.get("website", "")[:120] if re.match(r"https?://", cand.get("website", ""), re.I) else ""}


def tag_new(cands, cache, city, max_batches):
    todo = [c for cid, c in cands.items() if cid not in cache or retry_due(cache[cid])]
    # mix restaurants, bars and activities so every category grows each run; places with a website first
    def bucket(c):
        k = c.get("kind")
        return 0 if c["id"].startswith("nyc:") else 1 if k in ("bar", "pub", "biergarten", "nightclub") else 2
    groups = [sorted([c for c in todo if bucket(c) == g], key=lambda c: (not c.get("website"), not c.get("hours"))) for g in range(3)]
    todo = [c for trio in __import__("itertools").zip_longest(*groups) for c in trio if c]
    log(f"to tag: {len(todo)} new places in {city['name']}, up to {max_batches} batches of {BATCH_SIZE} this run")
    done, prompt = 0, prompt_for(city)
    for b in range(max_batches):
        batch = todo[b * BATCH_SIZE:(b + 1) * BATCH_SIZE]
        if not batch:
            break
        lines = "\n".join(f"{c['id']} | {c['name']} | {c.get('kind', '')} | {c.get('cuisine', '')} | {c.get('addr', '')} | {c.get('boro', '')} | {c.get('hood', '')}" for c in batch)
        try:
            items = parse_items(ai_call(prompt + lines))
        except OutOfQuota as e:
            log("stopping, free AI limit reached for today:", e)
            break
        except Exception as e:  # bad JSON or one off error: skip this batch, retry next run
            log("batch failed, will retry next run:", e)
            continue
        by_id = {i.get("id"): i for i in items if isinstance(i, dict)}
        for c in batch:
            if c["id"] in by_id:
                cache[c["id"]] = clean_tag(by_id[c["id"]], c, city)
                done += 1
        if b % 5 == 4:
            save_cache(cache)
    log(f"tagged {done} places this run")


def save_cache(cache):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


# ---------------------------------------------------------------- popularity
def fetch_stats():
    url = os.environ.get("STATS_URL")
    if not url:
        return {}
    try:
        return get_json(url.rstrip("/") + "/stats", timeout=60)
    except Exception as e:
        log("stats unavailable:", e)
        return {}


def popularity(stats, name):
    s = stats.get(name) or {}
    raw = 1.0 * s.get("pick", 0) + 2.0 * s.get("save", 0) - 1.5 * s.get("veto", 0)
    return round(max(-3, min(5, math.copysign(math.log1p(abs(raw)), raw))), 2)


# ---------------------------------------------------------------- main
CITY_ID = re.compile(r"^[a-z][a-z-]{1,23}$")


def load_cities():
    """Every cities/<id>/city.json. Contributors add cities, so check the fields the pipeline relies on."""
    cities = []
    for p in sorted(CITIES.glob("*/city.json")):
        if p.parent.is_symlink() or p.is_symlink():
            sys.exit(f"{p}: city folders must be real folders, not links")
        c = json.loads(p.read_text(encoding="utf-8"))
        bbox = c.get("bbox")
        if c.get("id") != p.parent.name or not CITY_ID.match(c["id"]) or not c.get("name"):
            sys.exit(f"{p}: id must match its folder name (lowercase letters and dashes) and name is required")
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)
                and bbox[0] < bbox[2] and bbox[1] < bbox[3] and (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < 1.0):
            sys.exit(f"{p}: bbox must be [south, west, north, east] and cover a city, not a country")
        cities.append(c)
    return cities


def curated_info(picks, osm, locate, bbox):
    """Coordinates, hours and needs for the hand picked spots, from the one OSM place with the same name (in the
    same area when the city has areas). Skipped when the match is ambiguous, so we never attach the wrong hours.
    Then a pick's own "lat"/"lon" (looked up on OpenStreetMap by hand) gives at least its location."""
    by_name = {}
    for o in osm:
        by_name.setdefault(norm(o["name"]), []).append(o)
    info = {}
    for row in picks:
        name, hood, boro = row.get("n", ""), row.get("h", ""), row.get("b", "")
        hits = by_name.get(norm(name), [])
        if locate:
            hits = [o for o in hits if locate(o["lat"], o["lon"])[0] == boro]
            if len(hits) > 1:
                hits = [o for o in hits if hood and hood.split(" ")[0].lower() in locate(o["lat"], o["lon"])[1].lower()]
        if len(hits) != 1:
            lat, lon = row.get("lat"), row.get("lon")
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)) \
                    and bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3] and (not locate or locate(lat, lon)[0] == boro):
                info[name] = {"lat": round(lat, 5), "lon": round(lon, 5)}
            continue
        o = hits[0]
        info[name] = {k: v for k, v in {"lat": round(o["lat"], 5), "lon": round(o["lon"], 5), "hrs": o["hrs"],
                                        "x": o["x"], "rsv": o["rsv"]}.items() if v}
    return info


def build_city(city, cache, stats, max_batches):
    src = city.get("sources") or {}
    picks = city.get("picks") or []
    curated = [p.get("n", "") for p in picks]
    insp = fetch_inspections() if src.get("restaurants") == "nyc-inspections" else []
    locate = fetch_neighborhoods() if src.get("neighborhoods") == "nyc-nta" else None
    osm = fetch_osm(city)
    if len(osm) < 500 or (src.get("restaurants") and len(insp) < 1000) or (locate and locate.count < 150):
        raise RuntimeError(f"source data looks incomplete (osm {len(osm)}, inspections {len(insp)}); keeping the old spots")
    cands = build_candidates(city, insp, osm, curated, locate)
    tag_new(cands, cache, city, max_batches)
    save_cache(cache)

    live, seen = [], set()
    for cid, c in cache.items():
        if c.get("skip") or cid not in cands:   # not found this run = closed or no longer listed
            continue
        k = norm(c["n"])
        if k in seen:
            continue
        seen.add(k)
        # official neighborhood beats the AI's guess; booking, hours and needs are refreshed from OSM every run
        fresh = {k: cands[cid].get(k) for k in ("rsv", "hrs", "x") if cands[cid].get(k)}
        live.append({**c, "h": cands[cid].get("hood") or c["h"], **fresh, "pop": popularity(stats, c["n"])})
    finds = []
    for cid, c in cache.items():
        if c.get("unknown") and cid in cands:
            f = fresh_find(cands[cid], city)
            if f and norm(f["n"]) not in seen and norm(f["n"]) not in {norm(n) for n in curated}:
                finds.append({**f, "rsv": cands[cid].get("rsv", ""), "hrs": cands[cid]["hrs"], "x": cands[cid].get("x", [])})
    finds.sort(key=lambda f: (not f["rsv"], not f["x"], f["n"]))  # best documented first
    for f in finds[:FRESH_PER_CITY]:
        seen.add(norm(f["n"]))
        live.append(f)
    live.sort(key=lambda s: (s["t"], s["n"]))
    cur_pop = {n: popularity(stats, n) for n in curated if popularity(stats, n)}
    cur_info = curated_info(picks, osm, locate, city["bbox"])
    log(f"hand picked spots matched on OpenStreetMap: {len(cur_info)} of {len(curated)}")
    out = CITIES / city["id"] / "spots.json"
    out.write_text(json.dumps({"updated": dt.date.today().isoformat(), "count": len(live), "spots": live,
                               "curatedPop": cur_pop, "curatedInfo": cur_info}, ensure_ascii=False, separators=(",", ":")))
    by_type = {t: sum(1 for s in live if s["t"] == t) for t in ("dinner", "drinks", "late", "free")}
    log(f"{city['id']}/spots.json: {len(live)} live spots {by_type} ({min(len(finds), FRESH_PER_CITY)} fresh finds), {len([c for c in cands if c not in cache])} still waiting to be tagged")


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cities = load_cities()
    only = os.environ.get("CITY")
    if only:
        cities = [c for c in cities if c["id"] == only]
    stats = fetch_stats()
    per_city = max(1, MAX_BATCHES // max(1, len(cities)))  # share the free daily AI quota between cities
    failed = []
    for city in cities:
        log(f"=== {city['name']} ===")
        try:
            build_city(city, cache, stats, per_city)
        except Exception as e:  # one city's source being down shouldn't stop the others
            log(f"{city['id']} failed, keeping its old spots:", e)
            failed.append(city["id"])
    if failed and len(failed) == len(cities):
        sys.exit("every city failed")


if __name__ == "__main__":
    main()
