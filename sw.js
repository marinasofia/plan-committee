/* Offline support for the installed app.
   Security: only same origin GET requests are handled. AI calls (which carry the user's key) and every
   other cross origin request go straight to the network and are never cached. Pages and data are network
   first, so a fix pushed to GitHub reaches people on their next visit instead of being stuck in a cache. */
const CACHE = "pc-v2";
const SHELL = ["cities/index.json", "cities/nyc/city.json", "cities/nyc/spots.json", "manifest.webmanifest", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", e => {
  // the app page is stored from "./" under "index.html": hosts like Cloudflare redirect /index.html to /,
  // and a redirected response can't be used as the offline page
  e.waitUntil(caches.open(CACHE).then(c => Promise.all([c.addAll(SHELL),
    fetch("./").then(res => { if (res.ok && !res.redirected) return c.put("index.html", res); })]))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  // the app has its own origin on Cloudflare Pages (_headers blocks framing too), but only ever touch our own caches (pc-*): defense in depth for shared hosts
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith("pc-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  const isIcon = url.pathname.includes("/icons/");
  e.respondWith(isIcon
    ? caches.match(req).then(hit => hit || fetch(req))
    : fetch(req).then(res => {
        // only the app page itself is stored as the offline page (not og.png or spots.json opened in a tab),
        // keyed by path so ?query and invite data never land in the cache
        const appPage = /\/(index\.html)?$/.test(url.pathname);
        if (res.ok && res.type === "basic" && !res.redirected && (req.mode !== "navigate" || appPage)) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req.mode === "navigate" ? "index.html" : url.pathname, copy));
        }
        return res;
      }).catch(() => caches.match(req.mode === "navigate" ? "index.html" : url.pathname, { ignoreSearch: true })));
});
