// AgriSureGIS service worker (2026-10-12). Exists only so browsers treat the
// app as installable. It deliberately has no fetch handler and caches
// nothing: offline use is out of scope (.claude/Initial Documentations.md,
// "will not have a mobile-offline capability"), and cached /api or GeoServer
// responses would show stale typhoon/farm data. Every request goes straight
// to the network exactly as it does without a service worker.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
