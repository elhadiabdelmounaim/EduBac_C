/* Service worker EduBac — version {{ version }}
 *
 * Règles de sécurité :
 * - seules les ressources publiques sont mises en cache (fichiers /static/ et
 *   la page hors connexion) ;
 * - les pages HTML, l'API, les fichiers privés, les sessions et toutes les
 *   requêtes autres que GET passent toujours par le réseau, sans cache ;
 * - sans réseau, une navigation affiche la page « hors connexion ».
 */
'use strict';

const VERSION = '{{ version }}';
const STATIC_CACHE = 'edubac-static-' + VERSION;
const OFFLINE_URL = '{{ offline_url }}';
const PRECACHE = [{% for url in precache %}'{{ url }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter((name) => name.startsWith('edubac-') && name !== STATIC_CACHE)
      .map((name) => caches.delete(name)));
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
    await self.clients.claim();
  })());
});

async function navigate(event) {
  try {
    const preloaded = await event.preloadResponse;
    if (preloaded) return preloaded;
    return await fetch(event.request);
  } catch (error) {
    const cache = await caches.open(STATIC_CACHE);
    return (await cache.match(OFFLINE_URL)) || Response.error();
  }
}

async function staticAsset(event) {
  // Affiche la copie locale tout de suite et la rafraîchit en arrière-plan.
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(event.request);
  const network = fetch(event.request).then((response) => {
    if (response.ok && response.type === 'basic') cache.put(event.request, response.clone());
    return response;
  }).catch(() => cached);
  if (cached) {
    event.waitUntil(network);
    return cached;
  }
  return network;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    event.respondWith(navigate(event));
    return;
  }
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(staticAsset(event));
  }
  // Tout le reste (API, /media/, pièces jointes, fichiers privés) : réseau uniquement.
});

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});
