# Contributing

Thanks for helping. The app is one HTML file with no build step, so most changes are small and easy to test.

## Run it

```
python3 -m http.server 8000
```

Open http://localhost:8000/?mock. Mock mode runs scripted agents, so you don't need an AI key to test most changes.

## Good first contributions

* **Add a hand picked spot.** Add a line to the `RAW` list in `index.html`:
  `Name|type|Neighborhood|Borough|price|cuisine|tags|short why`
  * type: `d` dinner, `k` drinks, `l` late (activity, dessert, venue), `f` free
  * Borough: `M`, `BK` or `Q`. Price: `0` to `4`.
  * cuisine (dinner only): italian, pizza, steak, french, asian, latin, comfort, american, mediterranean, seafood, veg
  * tags, from: romantic cozy fancy chaotic artsy lowkey dancing nerdy rooftop music views photo dessert wait loud quiet cash veg late
  * Only real places that are open now, and no chains.
* **Report a closed place.** Open an issue, or add its exact name to `data/blocklist.txt`.
* **Better agent banter** in mock mode, so the no key demo is more fun.

## Rules for every change

1. **Run `python3 tools/csp.py` after editing the script in `index.html`.** The page only runs the exact script whose hash is in its Content Security Policy. If you skip this, the app won't load and CI fails.
2. **No new dependencies or third party scripts.** Everything stays free and self contained: no paid services, no frameworks, no trackers.
3. **Data only from NYC Open Data and OpenStreetMap.** Don't scrape Google Maps, Yelp, Resy or The Infatuation.
4. **Treat every outside input as hostile.** Share links, `spots.json`, OpenStreetMap tags and AI replies all go through `esc()`, links through `safeUrl()`. Users' AI keys live in the browser, so an injection bug can steal them.
5. **Never put an API key in code, issues or pull requests.** If you leak one, delete it in Google AI Studio or Groq right away.
6. Keep pull requests small and focused, and say how you tested.

## Security issues

Please don't open a public issue. See [SECURITY.md](SECURITY.md).

## Code of conduct

Be kind. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
