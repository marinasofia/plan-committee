# The Plan Committee

AI agents argue in a group chat and agree on one real NYC date night or friends night plan.

## How it works

* `index.html` is the whole app: one file, no build step, no server. It is hosted on Cloudflare Pages (https://plan-committee.pages.dev), which deploys every push to `main`; `_headers` sets the HTTP security headers. It is installable as an app (`manifest.webmanifest`, `sw.js`, `icons/`); `og.png` is the link preview image. Users bring their own free AI key. 125 hand picked spots live inside it (`const RAW`) and always rank first. Without a key the app runs a demo with scripted agents over the real shortlist; `index.html?mock` forces it for testing.
* Cities live in `cities/<id>/`: `city.json` (settings and hand picks, written by people) and `spots.json` (generated daily). `cities/index.json` lists them. The app loads the city at startup and validates every field; `tools/format_city.py` formats city files.
* `spots.json` is the extra spot list the app loads on every visit. It is built daily by `pipeline/build_spots.py` via `.github/workflows/update-spots.yml`, and the Actions bot commits `spots.json` and `data/tagged.json`.
* Pipeline: NYC Open Data restaurant inspections from the last 12 months (closed places drop out) plus OpenStreetMap places via Overpass. Restaurants must also be on OSM with a website or hours. Chains, takeout cuisines and curated spots are removed. A free AI (Groq, then Gemini) tags new places in batches; unknown places are skipped. Tags are cached in `data/tagged.json` so each place is tagged once.
* `worker/` is an optional Cloudflare Worker for anonymous usage counts (`STATS_URL`).

## Rules

* The project is open source (MIT code, ODbL place data). Contributor PRs run in users' browsers next to their AI keys: review every change to `index.html`, `sw.js` and workflows line by line, especially new hosts in fetch calls, CSP edits and anything rendered as HTML.

* Everything stays free: no paid services, no Supabase.
* Data only from NYC Open Data, OpenStreetMap and the free AI keys in repo secrets (`GROQ_API_KEY`, `GEMINI_API_KEY`). Never scrape Google Maps, Yelp, Resy or The Infatuation.
* Keep `index.html` a single file with no build step. The pipeline uses the Python standard library only.
* Keep explanations short.

## Security review on every change (the repo is public)

Act as a senior security engineer and pen test every change before it is committed. Run the security-auditor agent too, and fix or report what you find before pushing. Check at least:

* Secrets: no keys, tokens, emails or personal paths in code, data files, logs or git history. Send the Gemini key in the `x-goog-api-key` header, never in the URL, and never log request headers or raw error bodies that could echo a key.
* CSP: `index.html` only runs the inline script whose sha256 is in its Content Security Policy. After any edit to the script, run `python3 tools/csp.py`, or the app will not run. CI checks it.
* Hosting: the app has its own origin on Cloudflare Pages. Don't move it back to GitHub Pages: every repo on a `username.github.io` shares one origin and could read users' saved keys. Keep `_headers` (frame blocking, nosniff, no-cache for `sw.js`).
* Service worker (`sw.js`): only same origin GET requests, never AI calls or anything cross origin; keep pages network first so fixes reach people.
* XSS in `index.html`: share links (`#j=`, `#r=`, `#p=`), `spots.json`, OpenStreetMap data and AI replies are all untrusted. Everything put into `innerHTML` goes through `esc()`, links through `safeUrl()` (http and https only), colors through `safeColor()`. Users' AI keys live in localStorage, so any XSS steals them.
* GitHub Actions: no `pull_request_target` or comment triggers, least `permissions`, no `${{ }}` of untrusted input inside `run:`, secrets only in the step that needs them.
* Worker (`worker/`): validate and cap input, parameterized D1 queries, nothing a stranger posts can reach the page as HTML.
* New dependencies or third party scripts: avoid them; if needed, pin exact versions.

## Debugging the pipeline locally

* Run `MAX_BATCHES=2 python3 pipeline/build_spots.py` to use little AI quota. It writes `spots.json` and `data/tagged.json`, so run it on a copy if you don't want to commit the result.
* In the Claude Code sandbox, Python downloads from NYC Open Data get cut off by the proxy while curl works. Overpass often answers 502 when busy; the script retries with backoff.

## Security

Follow [SECURITY-RULES.md](SECURITY-RULES.md) for every change. Before this repo goes public, run the security kit scan and its publish checklist.
