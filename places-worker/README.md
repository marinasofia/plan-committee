# Places cache (optional, free)

"Somewhere else" cities get their places from OpenStreetMap's public Overpass servers, which are often slow (30 to 60 seconds) or full. This Worker sits in front of them: the first person to open a city waits, everyone after gets it in under a second from Cloudflare KV, for 30 days. Free tier: 100,000 reads and 1,000 new cities a day.

It only passes public map data. It stores no names, IPs or keys, and answers only requests from the app's own origin (`ORIGIN` in `worker.js`).

## Deploy (5 minutes, free Cloudflare account)

```
cd places-worker
npx wrangler login
npx wrangler kv namespace create PLACES
```

Paste the `id` it prints into `wrangler.toml`, then:

```
npx wrangler deploy
```

It prints a URL like `https://plan-committee-places.<you>.workers.dev`. Put it in `index.html` as `PLACES_URL` (near the top of the script), run `python3 tools/csp.py`, and open a pull request.

Check it: `curl -H "Origin: https://plan-committee.pages.dev" "https://plan-committee-places.<you>.workers.dev/places?lat=38.71&lon=-9.14&km=2"` returns places, and the second call says `X-Cache: hit`.
