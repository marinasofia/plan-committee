# Security

To report a security issue, use **Report a vulnerability** in this repository's Security tab. Please don't open a public issue.

You can expect a reply within a week.

## What the app talks to

The app has no server of its own. From your browser it only contacts:

* **The AI provider you chose** (Gemini, Groq, OpenRouter or your own API), with your key, for the agents' messages.
* **Open-Meteo**, with the city center and date, for the forecast.
* **OpenStreetMap** for cities without a curated pack ("Somewhere else", or a link to such a city): Nominatim once to find the city (only this site's address as referrer), then Overpass (overpass-api.de, and the community mirror overpass.private.coffee if the first is slow) with the city center. With a key, one AI call adds prices and vibes to those places. When the optional places cache (`places-worker/`, a Cloudflare Worker) is turned on, those Overpass requests go through it instead: same city center, same public map data, nothing about you stored.

Your key, names and picks never go to OpenStreetMap or Open-Meteo.
