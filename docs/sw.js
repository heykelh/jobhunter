// Service worker minimal : rend le site installable comme une appli.
// Aucune mise en cache : les offres affichées sont toujours celles du dernier passage.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
