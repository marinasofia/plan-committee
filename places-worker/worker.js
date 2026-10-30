// Shared cache in front of OpenStreetMap for The Plan Committee's "Somewhere else" cities. Free on Cloudflare Workers + KV.
// GET /places?lat=38.71&lon=-9.14&km=2.5  ->  {"elements":[...]}: named restaurants, bars, late and free spots around that point.
// The first person to open a city waits for OpenStreetMap; everyone after gets it from KV for 30 days.
// Only public map data passes through. Nothing about people is stored or logged.
const ORIGIN = "https://plan-committee.pages.dev";  // change it if you host your own copy
const OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"];
const UA = "plan-committee-places/1.0 (+https://github.com/marinasofia/plan-committee)";
const TTL = 30 * 86400;
// only the tags the app reads (osmSpot in index.html), so a city is a third of the size
const KEEP = ["name", "brand", "brand:wikidata", "disused", "abandoned", "amenity", "tourism", "leisure", "cuisine", "website", "contact:website",
  "opening_hours", "fee", "live_music", "rooftop", "diet:vegan", "diet:vegetarian", "diet:gluten_free", "payment:cash", "wheelchair",
  "addr:suburb", "addr:neighbourhood", "addr:quarter", "addr:district", "wikidata"];
const cors = { "Access-Control-Allow-Origin": ORIGIN, "Access-Control-Allow-Methods": "GET,OPTIONS", "Vary": "Origin" };
const json = (body, status = 200, extra = {}) => new Response(body, { status, headers: { "Content-Type": "application/json", ...cors, ...extra } });

function query(lat, lon, km) {
  const dy = km / 111, dx = dy / Math.cos(lat * Math.PI / 180);
  const b = [lat - dy, lon - dx, lat + dy, lon + dx].map(v => v.toFixed(4)).join(",");
  return `[out:json][timeout:90];(nw["amenity"~"^(restaurant|bar|pub|biergarten|nightclub|cinema|theatre|ice_cream|arts_centre)$"]["name"](${b});` +
    `nw["tourism"~"^(museum|gallery|viewpoint)$"]["name"](${b});nwr["leisure"~"^(park|garden)$"]["name"]["wikidata"](${b}););out center tags 2500;`;
}
const slim = e => {
  const t = {}; for (const k of KEEP) if (typeof e.tags?.[k] === "string") t[k] = e.tags[k].slice(0, 300);
  const lat = e.lat ?? e.center?.lat, lon = e.lon ?? e.center?.lon;
  return typeof lat === "number" && typeof lon === "number" && t.name ? { lat: +lat.toFixed(5), lon: +lon.toFixed(5), tags: t } : null;
};

export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const url = new URL(req.url);
    if (req.method !== "GET" || url.pathname !== "/places") return json('{"hint":"GET /places?lat=&lon=&km="}', 404);
    if (req.headers.get("Origin") !== ORIGIN) return json('{"error":"origin"}', 403);  // only the app, not a free proxy for everyone
    // a ~1 km grid and half-km sizes keep the number of distinct cities (and KV entries) small
    const lat = Math.round(Number(url.searchParams.get("lat")) * 100) / 100, lon = Math.round(Number(url.searchParams.get("lon")) * 100) / 100;
    const km = Math.round(Number(url.searchParams.get("km")) * 2) / 2;
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 85 || Math.abs(lon) > 180 || !(km >= 1.5 && km <= 4)) return json('{"error":"bad request"}', 400);
    const key = `p:${lat.toFixed(2)},${lon.toFixed(2)},${km}`;
    const hit = env.PLACES && await env.PLACES.get(key);
    if (hit) return json(hit, 200, { "X-Cache": "hit" });
    let elements = null;
    for (const host of OVERPASS) {
      try {
        const r = await fetch(host, { method: "POST", headers: { "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ data: query(lat, lon, km) }), signal: AbortSignal.timeout(100000) });
        if (!r.ok) continue;
        const j = await r.json();
        if (Array.isArray(j?.elements)) { elements = j.elements.slice(0, 8000).map(slim).filter(Boolean); break; }
      } catch { /* busy or slow: try the mirror */ }
    }
    if (!elements) return json('{"error":"OpenStreetMap is busy"}', 503);
    const body = JSON.stringify({ elements });
    if (env.PLACES && elements.length) ctx.waitUntil(env.PLACES.put(key, body, { expirationTtl: TTL }));
    return json(body, 200, { "X-Cache": "miss" });
  },
};
