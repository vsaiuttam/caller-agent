/*
 * Samvaad's service worker: makes the console installable and quick to
 * reopen. It caches the app itself, never data:
 *
 *   /api/*        always the network (calls, transcripts and auth are live)
 *   pages         network first; offline, the cached app shell opens instead
 *   /assets/*     cache first (Vite names them by content hash, so a cached
 *                 file never goes stale)
 *   fonts, icons  served from cache, refreshed in the background
 *
 * Bump VERSION to drop every cache on the next visit.
 */
const VERSION = "v1";
const SHELL = `samvaad-shell-${VERSION}`;
const RUNTIME = `samvaad-runtime-${VERSION}`;
const PRECACHE = ["/", "/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== RUNTIME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;
  const isFont = url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com";

  if (sameOrigin && url.pathname.startsWith("/api/")) return;
  if (!sameOrigin && !isFont) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  if (sameOrigin && url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(RUNTIME).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // Stale while revalidate: fonts, icons, the manifest.
  event.respondWith(
    caches.open(RUNTIME).then((cache) =>
      cache.match(request).then((hit) => {
        const network = fetch(request)
          .then((response) => {
            if (response.ok || response.type === "opaque") cache.put(request, response.clone());
            return response;
          })
          .catch(() => hit);
        return hit || network;
      }),
    ),
  );
});
