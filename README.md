# The Plan Committee

Everyone picks what they want. Each person gets an AI agent that argues for them in a group chat, and they agree on one real NYC plan.

* `index.html` is the whole app (no server). Users bring their own free AI key (Gemini, Groq, OpenRouter or any OpenAI compatible API).
* Installable as an app: `manifest.webmanifest`, `sw.js` (offline support) and `icons/`. `og.png` is the preview card for shared links.
* After editing the script in `index.html`, run `python3 tools/csp.py` to update its Content Security Policy hash.
* `spots.json` grows by itself every day (see below). 125 hand picked spots live inside `index.html` and always rank as top picks.

## How the spot list grows by itself

`.github/workflows/update-spots.yml` runs `pipeline/build_spots.py` every day:

1. Downloads every NYC restaurant inspected in the last 12 months from NYC Open Data. Places that stop getting inspected drop out, so closed restaurants disappear on their own.
2. Downloads bars, venues, museums, cinemas, parks and viewpoints from OpenStreetMap.
3. Keeps notable places (on OpenStreetMap with a website or hours), removes chains and takeout categories.
4. A free AI tags new places in batches (type, price, cuisine, vibe). Places the AI doesn't recognize are skipped, so it never makes up vibes. Each place is tagged once and cached in `data/tagged.json`.
5. Optional: reads anonymous usage counts (plans, saves, vetoes) so places people love rank higher.

Free limits: about 40 batches of 25 places per run fits inside Groq's free daily tokens. The first week fills the backlog, then each run only tags new openings.

## Setup (one time, about 10 minutes)

1. Create the repo and push:
   ```
   cd plan-committee
   git init -b main && git add . && git commit -m "The Plan Committee"
   gh repo create plan-committee --private --source=. --push
   ```
2. Add your free AI key: repo **Settings > Secrets and variables > Actions > New repository secret**
   * `GROQ_API_KEY` (free at console.groq.com/keys) and/or `GEMINI_API_KEY` (free at aistudio.google.com/apikey)
3. Run it once by hand: **Actions > Update spots > Run workflow**. After that it runs daily.
4. Turn on the website: **Settings > Pages > Deploy from branch > main / root**.
   * GitHub Pages on a **private** repo needs GitHub Pro. Students get Pro free with the GitHub Student Developer Pack (education.github.com/pack). Otherwise make the repo public.

## Optional: usage counts (Cloudflare, free, no card)

```
cd worker
npx wrangler login
npx wrangler d1 create plan-committee        # copy the database_id into wrangler.toml
npx wrangler d1 execute plan-committee --remote --file=schema.sql
npx wrangler deploy                          # prints your worker URL
```
Then paste the worker URL into `STATS_URL` near the top of the script in `index.html`, and add it as a repo **variable** (not secret) named `STATS_URL`. Only place names and counts are stored, nothing about people.

## Testing

Open `index.html?mock` to run scripted agents with no AI key.

Data: NYC Open Data (DOHMH Restaurant Inspection Results), © OpenStreetMap contributors (ODbL).
