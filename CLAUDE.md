# The Plan Committee

AI agents argue in a group chat and agree on one real NYC date night or friends night plan.

## How it works

* `index.html` is the whole app: one file, no build step, no server. Users bring their own free AI key. 125 hand picked spots live inside it (`const RAW`) and always rank first. `index.html?mock` runs scripted agents with no key.
* `spots.json` is the extra spot list the app loads on every visit. It is built daily by `pipeline/build_spots.py` via `.github/workflows/update-spots.yml`, and the Actions bot commits `spots.json` and `data/tagged.json`.
* Pipeline: NYC Open Data restaurant inspections from the last 12 months (closed places drop out) plus OpenStreetMap places via Overpass. Restaurants must also be on OSM with a website or hours. Chains, takeout cuisines and curated spots are removed. A free AI (Groq, then Gemini) tags new places in batches; unknown places are skipped. Tags are cached in `data/tagged.json` so each place is tagged once.
* `worker/` is an optional Cloudflare Worker for anonymous usage counts (`STATS_URL`).

## Rules

* Everything stays free: no paid services, no Supabase.
* Data only from NYC Open Data, OpenStreetMap and the free AI keys in repo secrets (`GROQ_API_KEY`, `GEMINI_API_KEY`). Never scrape Google Maps, Yelp, Resy or The Infatuation.
* Keep `index.html` a single file with no build step. The pipeline uses the Python standard library only.
* Keep explanations short.

## Debugging the pipeline locally

* Run `MAX_BATCHES=2 python3 pipeline/build_spots.py` to use little AI quota. It writes `spots.json` and `data/tagged.json`, so run it on a copy if you don't want to commit the result.
* In the Claude Code sandbox, Python downloads from NYC Open Data get cut off by the proxy while curl works. Overpass often answers 502 when busy; the script retries with backoff.
