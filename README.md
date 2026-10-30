<p align="center"><img src="og.png" alt="The Plan Committee: AI agents argue in a group chat and agree on one NYC plan" width="720"></p>

<h1 align="center">The Plan Committee</h1>

<p align="center">
  Everyone picks what they want. Each person gets an AI agent that fights for them in a group chat.<br>
  They agree on one real NYC plan: dinner, drinks, something after.
</p>

<p align="center">
  <a href="https://plan-committee.pages.dev/"><b>Try it live</b></a> ·
  <a href="https://plan-committee.pages.dev/?mock">Try it with no AI key</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

<p align="center">
  <a href="https://github.com/marinasofia/plan-committee/actions/workflows/security.yml"><img alt="Security checks" src="https://github.com/marinasofia/plan-committee/actions/workflows/security.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-1c1b1a"></a>
</p>

## What it does

<img src="docs/setup.png" alt="Setup screen" width="300" align="right">

* **Date night or friends night.** Add your people, or send an invite link to the group chat so everyone picks on their own phone. Friends never need a key or an account.
* **Your people, saved.** Send friends a profile link: 6 quick taps and their taste and agent personality are saved on your phone. Next time you just tap who's coming.
* **Agents with personalities.** Dramatic, stubborn, chill, the mediator, chaotic. An optional Wallet agent guards the budget.
* **Any city.** Pick "Somewhere else" and type any city: places come live from OpenStreetMap. New York and London also have curated packs refreshed daily, and adding yours is one command and one pull request ([how](CONTRIBUTING.md)).
* **Real places only.** 153 hand picked spots (125 in New York, 28 in London), plus 1,325 more tagged from NYC Open Data and OpenStreetMap, refreshed every day. Closed restaurants drop out on their own.
* **A plan you can use.** Map, website, reserve (straight to Resy or OpenTable when we know the page), add to calendar, share the whole argument as a replay link.
* **Your AI, your key.** Bring a free Gemini, Groq or OpenRouter key, or point it at any OpenAI compatible API. The key stays in your browser and is sent only to the provider you chose.
* **Installable.** Add it to your home screen and it opens like an app.

<br clear="right">

## Why I built it

Picking a place for six people takes longer than the dinner itself. I wanted to see whether a group of AI agents, each loyal to one person, could argue it out and land on a plan everyone accepts, and whether a multi agent product could run with no server and no bill. The agents turned out to be the easy part. The hard parts were fitting inside free tier quotas, treating share links, OpenStreetMap names and AI replies as hostile input, and keeping an app that stores people's API keys safe from the content it renders.

## By the numbers

* 2 cities: New York and London ([`cities/index.json`](cities/index.json)).
* 153 hand picked spots: 125 in New York, 28 in London (`picks` in [`cities/*/city.json`](cities)).
* 1,325 more spots tagged by the pipeline: 513 in New York, 812 in London ([`cities/*/spots.json`](cities), built 2026-10-28).
* 2 open data sources: NYC Open Data and OpenStreetMap. No scraping.
* 0 packages: no `package.json`, no `requirements.txt`. The pipeline is Python standard library only.
* 0 build steps: `index.html` is served as is.
* $0 to host: Cloudflare Pages free plan, GitHub Actions for the daily build, and everyone brings their own free AI key.

## How it works

* **No server, no build step.** The whole app is [`index.html`](index.html). Open it in a browser and it runs.
* **No database.** Plans, picks and invites live in the link itself (after the `#`, which never reaches any server) and in your browser.
* **The spot list grows by itself.** For every city, a daily GitHub Action ([`pipeline/build_spots.py`](pipeline/build_spots.py)) pulls fresh data, filters out chains and takeout spots, and has a free AI tag new places by vibe, price and cuisine. Places the AI doesn't recognize are skipped, so it never makes up vibes. In New York, neighborhoods come from the city's official NTA map and override the AI's answer. In London they come from the AI's answer, because that city pack lists no neighborhood source.
* **Locked down.** A hash based Content Security Policy, a service worker that never touches AI calls, and a security scan on every pull request. See [SECURITY.md](SECURITY.md).

One night, from picks to plan (function names are from `index.html`):

```
city.json + spots.json
        |
        v
  shortlist()      ranks 18 real places for tonight: price, hours, needs, weather, distance
        |
        v
  runRounds()      each agent gets one message per round, in character, with the shortlist in its prompt
        |
        v
  makePlan()       one more AI call turns the chat into JSON: title, 3 stops, verdict
        |
        v
  findSpot()       every stop must match a place on the shortlist, or it is dropped
        |
        v
  renderTicket()   map, reserve, calendar and a share link, every string escaped before it hits the page
```

## Run it yourself

```
git clone https://github.com/marinasofia/plan-committee.git
cd plan-committee
python3 -m http.server 8000
```

Open http://localhost:8000/?mock for scripted agents with no AI key, or http://localhost:8000 to use your own key.

### Host your own copy (free)

1. Fork the repo.
2. In Cloudflare (free, no card): **Workers & Pages > Create > Pages > Connect to Git**, pick your fork. Framework preset **None**, no build command, output directory `/`. Every push to `main` deploys on its own, and `_headers` adds the security headers.
3. For the daily spot updates, add a free `GROQ_API_KEY` (console.groq.com/keys) and/or `GEMINI_API_KEY` (aistudio.google.com/apikey) under **Settings > Secrets and variables > Actions**, then run **Actions > Update spots** once.

GitHub Pages works too, but every repo on your `username.github.io` shares one origin, so any of them could read the AI keys people save in the app. Cloudflare gives the app its own address.

Free limits: about 40 batches of 25 places per run fits inside Groq's free daily tokens. The first week fills the backlog, then each run only tags new openings.

### Optional: usage counts (Cloudflare, free, no card)

```
cd worker
npx wrangler login
npx wrangler d1 create plan-committee        # copy the database_id into wrangler.toml
npx wrangler d1 execute plan-committee --remote --file=schema.sql
npx wrangler deploy                          # prints your worker URL
```

Paste the worker URL into `STATS_URL` near the top of the script in `index.html`, run `python3 tools/csp.py`, and add it as a repo **variable** named `STATS_URL`. Only place names and counts are stored, nothing about people. The worker answers only the app's origin (CORS) and rejects bodies over 1 KB; set `ORIGIN` in `worker.js` to your own address. Rate limiting is left to a Cloudflare rate limiting rule on the worker route, so add one before you point a public site at it.

## Contributing

New spots, better agent banter, other cities, bug fixes: all welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and look for issues labeled **good first issue**.

## License and data

* Code: [MIT](LICENSE).
* Restaurant data: NYC Open Data (DOHMH Restaurant Inspection Results) and Neighborhood Tabulation Areas.
* Place data: © OpenStreetMap contributors, available under the [Open Database License](https://opendatacommons.org/licenses/odbl/). `cities/*/spots.json` and `data/tagged.json` are derived from it and are shared under the ODbL too. See [DATA-LICENSE.md](DATA-LICENSE.md).
