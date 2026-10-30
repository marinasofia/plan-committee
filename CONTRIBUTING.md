# Contributing

Thanks for helping. The app is one HTML file with no build step, so most changes are small and easy to test.

## Run it

```
python3 -m http.server 8000
```

Open http://localhost:8000/?mock. Mock mode runs scripted agents, so you don't need an AI key to test most changes.

## Good first contributions

* **Add a hand picked spot.** Add one line to `picks` in `cities/<city>/city.json`, for example:
  `{"n": "Via Carota", "t": "dinner", "h": "West Village", "b": "M", "p": 2, "c": "italian", "f": ["romantic", "cozy"], "v": "cozy Italian, no reservations"}`
  * `t`: dinner, drinks, late (activity, dessert, venue) or free. `p`: price 0 to 4. `b`: the city's area code, or `""` if the city has no areas.
  * `c` (dinner only): italian, pizza, steak, french, asian, latin, comfort, american, mediterranean, seafood, veg
  * `f`, from: romantic cozy fancy chaotic artsy lowkey dancing nerdy rooftop music views photo dessert wait loud quiet cash veg late
  * Optional `lat`, `lon`: only needed when the daily build can't find the place on OpenStreetMap by its exact name. Copy them from OpenStreetMap, never from Google Maps.
  * Only real places that are open now, and no chains. Run `python3 tools/format_city.py` to tidy the file.
* **Add a curated city pack.** The app already works anywhere ("Somewhere else" uses the open Overture lists, or OpenStreetMap live for cities not on them), but a pack adds hand picks, neighborhood chips and daily AI tags. Run:
  `python3 tools/new_city.py "Paris"` (add `--tz America/Chicago` for countries with several time zones, `--dry-run` to preview)
  It looks the city up on OpenStreetMap and writes `cities/<id>/city.json` (outline, center, time zone, currency, 9 neighborhood chips), an empty `spots.json`, and the line in `cities/index.json`. Then:
  * Check the neighborhood chips: keep the ones locals would pick, rename or drop the rest.
  * Add 10 to 30 hand picks you'd actually send a friend to (format above), run `python3 tools/format_city.py`, and open a pull request.
  * Text in city files (names, `v` blurbs, neighborhood labels) is shown to people and given to the AI, so keep it short and factual. Maintainers review it like code.
  * The daily pipeline fills `spots.json` from OpenStreetMap, and a free AI tags it over the next few days. Every city shares the same free daily AI quota, so new cities grow a little slower than the first two.
* **Fix a "Somewhere else" city.** Over 600 cities worldwide come from open place lists built every month from Overture Maps (`places/cities.json`, `pipeline/build_places.py`). To add a place or drop a closed one, edit `places/edits.json`, keyed by the city id from `places/cities.json`:
  `{"lisbon-pt": {"remove": ["Exact Name Of Closed Bar"], "add": [{"n": "Park Bar", "t": "drinks", "lat": 38.7105, "lon": -9.1466, "f": ["views", "rooftop"]}]}}`
  Same fields as hand picks, `lat`/`lon` required (copy them from OpenStreetMap or Overture, never Google Maps). Edits are applied on every rebuild. Their text is shown to people and given to the AI, so keep it short and factual: maintainers review it like code.
* **Add a city to the open list.** Add a line to `places/cities.json` (`id` like `city-cc`, `name`, `cc`, `lat`, `lon`, `km` from 1.5 to 4) and it's in next month's build.
* **Report a closed place.** Open an issue, or add its exact name to `data/blocklist.txt`.
* **Better agent banter** in mock mode, so the no key demo is more fun.

## Rules for every change

1. **Run `python3 tools/csp.py` after editing the script in `index.html`.** The page only runs the exact script whose hash is in its Content Security Policy. If you skip this, the app won't load and CI fails.
2. **No new dependencies or third party scripts.** Everything stays free and self contained: no paid services, no frameworks, no trackers.
3. **Data only from NYC Open Data, OpenStreetMap and Overture Maps.** Don't scrape Google Maps, Yelp, Resy or The Infatuation.
4. **Treat every outside input as hostile.** Share links, `spots.json`, OpenStreetMap tags and AI replies all go through `esc()`, links through `safeUrl()`. Users' AI keys live in the browser, so an injection bug can steal them.
5. **Never put an API key in code, issues or pull requests.** If you leak one, delete it in Google AI Studio or Groq right away.
6. Keep pull requests small and focused, and say how you tested.

## Security issues

Please don't open a public issue. See [SECURITY.md](SECURITY.md).

## Code of conduct

Be kind. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
