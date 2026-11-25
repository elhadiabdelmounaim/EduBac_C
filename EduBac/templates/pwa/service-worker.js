/* Service worker EduBac — version {{ version }}
 *
 * Règles de sécurité :
 * - seules les ressources publiques sont mises en cache (fichiers /static/ et
 *   la page hors connexion) ;
 * - exception : la page d'un tableau mathématique déjà ouvert
 *   (/tableau-maths/<n>/) est gardée pour s'ouvrir sans réseau ; ce cache est
 *   vidé à la déconnexion et à chaque connexion ;
 * - les autres pages HTML, l'API, les fichiers privés, les sessions et toutes
 *   les requêtes autres que GET passent toujours par le réseau, sans cache ;
 * - sans réseau, une navigation affiche la page « hors connexion ».
 */
'use strict';

const VERSION = '{{ version }}';
const STATIC_CACHE = 'edubac-static-' + VERSION;
const OFFLINE_URL = '{{ offline_url }}';
const BOARDS_CACHE = 'edubac-boards';
const BOARD_PAGE = /^\/tableau-maths\/\d+\/$/;
const SESSION_PAGE = /^\/compte\/(de)?connexion\//;
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
      .filter((name) => name.startsWith('edubac-') && name !== STATIC_CACHE && name !== BOARDS_CACHE)
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

async function boardPage(event) {
  // Réseau d'abord (page à jour) ; copie gardée pour l'ouvrir hors connexion.
  const cache = await caches.open(BOARDS_CACHE);
  try {
    const preloaded = await event.preloadResponse;
    const response = preloaded || await fetch(event.request);
    if (response.ok && response.type === 'basic' && !response.redirected) {
      await cache.put(event.request.url, response.clone());
    }
    return response;
  } catch (error) {
    const copy = await cache.match(event.request.url);
    if (copy) return copy;
    const statics = await caches.open(STATIC_CACHE);
    return (await statics.match(OFFLINE_URL)) || Response.error();
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
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate' && SESSION_PAGE.test(url.pathname)) {
    // Déconnexion ou changement de compte : les pages de tableaux gardées sont effacées.
    event.waitUntil(caches.delete(BOARDS_CACHE));
  }
  if (request.method !== 'GET') return;
  if (request.mode === 'navigate') {
    event.respondWith(BOARD_PAGE.test(url.pathname) ? boardPage(event) : navigate(event));
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

/* Notifications sur le téléphone (Web Push).
 * Le message est chiffré par le serveur EduBac ; le navigateur le déchiffre ici.
 * Une seule notification par conversation (tag) : la suivante la remplace. */
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (error) { data = { body: event.data && event.data.text() }; }
  const title = data.title || 'EduBac';
  const options = {
    body: data.body || 'Vous avez une nouvelle notification.',
    icon: data.icon || '/static/pwa/icon-192.png',
    badge: data.badge || '/static/pwa/icon-maskable-192.png',
    tag: data.tag || undefined,
    renotify: !!data.tag,
    data: { url: (data.url && data.url.startsWith('/')) ? data.url : '/' },
    lang: 'fr',
  };
  event.waitUntil((async () => {
    await self.registration.showNotification(title, options);
    if (self.navigator && 'setAppBadge' in self.navigator) {
      const shown = await self.registration.getNotifications();
      self.navigator.setAppBadge(shown.length).catch(() => {});
    }
  })());
});

async function updateAppBadge() {
  if (!(self.navigator && 'setAppBadge' in self.navigator)) return;
  const shown = await self.registration.getNotifications();
  if (shown.length) self.navigator.setAppBadge(shown.length).catch(() => {});
  else if ('clearAppBadge' in self.navigator) self.navigator.clearAppBadge().catch(() => {});
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    await updateAppBadge();
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
        await client.focus();
        if ('navigate' in client) return client.navigate(target.href);
        return undefined;
      }
    }
    return self.clients.openWindow(target.href);
  })());
});

// L'appareil a renouvelé son abonnement : on prévient le serveur au prochain affichage.
self.addEventListener('pushsubscriptionchange', () => {
  self.clients.matchAll({ type: 'window' }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: 'edubac-push-resubscribe' }));
  });
});
