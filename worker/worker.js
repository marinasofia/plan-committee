// Anonymous usage counter for The Plan Committee. Free on Cloudflare Workers + D1.
// POST /e  {"kind":"pick"|"save"|"veto","names":["Via Carota", ...]}  -> counts +1
// GET  /stats -> {"Via Carota":{"pick":12,"save":3,"veto":1}, ...}
// No names of people, no IPs stored. Only place names and counts.
const KINDS = new Set(["pick", "save", "veto"]);
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
const json = (d, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { "Content-Type": "application/json", ...cors } });

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    if (req.method === "POST" && url.pathname === "/e") {
      let body; try { body = await req.json(); } catch { return json({ ok: false }, 400); }
      const kind = String(body.kind || "");
      const names = Array.isArray(body.names) ? body.names.slice(0, 4).map(n => String(n).slice(0, 60).trim()).filter(Boolean) : [];
      if (!KINDS.has(kind) || !names.length) return json({ ok: false }, 400);
      await env.DB.batch(names.map(n => env.DB.prepare(
        "INSERT INTO counts (name, kind, n) VALUES (?1, ?2, 1) ON CONFLICT(name, kind) DO UPDATE SET n = n + 1").bind(n, kind)));
      return json({ ok: true });
    }
    if (req.method === "GET" && url.pathname === "/stats") {
      const { results } = await env.DB.prepare("SELECT name, kind, n FROM counts").all();
      const out = {};
      for (const r of results) (out[r.name] ??= {})[r.kind] = r.n;
      return json(out);
    }
    return json({ ok: true, hint: "POST /e or GET /stats" });
  },
};
