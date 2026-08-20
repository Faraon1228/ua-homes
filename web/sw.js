// UA-Dim Service Worker — PWA offline support
importScripts('/precache-manifest.js');

const CACHE = `ua-dim-v6-${self.__UA_BUILD_ID || 'development'}`;
const IMAGE_CACHE = 'ua-dim-images-v1';
const OFFLINE_ASSETS = [
  ...(self.__UA_PRECACHE_ASSETS || []),
  '/vendor/react.production.min.js',
  '/vendor/react-dom.production.min.js',
  '/ua-homes-manifest.json',
  '/privacy.html',
  '/terms.html',
  '/cookie-policy.html',
  '/privacy-consent.css',
  '/privacy-consent.js',
];

async function trimCache(cache, maxEntries) {
  const keys = await cache.keys();
  await Promise.all(
    keys.slice(0, Math.max(0, keys.length - maxEntries)).map(key => cache.delete(key))
  );
}

// On install: cache the shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(OFFLINE_ASSETS))
  );
  self.skipWaiting();
});

// On activate: remove old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => ![CACHE, IMAGE_CACHE].includes(k)).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy: network first, fall back to cache
self.addEventListener('fetch', e => {
  // Don't intercept API calls — always go to network
  if (e.request.url.includes('/api/') || e.request.url.includes('/api-backend/')) return;

  const url = new URL(e.request.url);
  const sameOrigin = url.origin === self.location.origin;
  const coreAsset =
    sameOrigin &&
    ['script', 'style', 'worker'].includes(e.request.destination);

  if (e.request.method === 'GET' && coreAsset) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          if (resp.status !== 200) {
            return caches.match(e.request, { ignoreSearch: true }).then(cached => cached || resp);
          }
          caches.open(CACHE).then(cache => cache.put(e.request, resp.clone()));
          return resp;
        })
        .catch(() =>
          caches.match(e.request, { ignoreSearch: true }).then(cached => cached || Response.error())
        )
    );
    return;
  }

  if (e.request.method === 'GET' && e.request.destination === 'image') {
    e.respondWith(
      caches.open(IMAGE_CACHE).then(cache =>
        cache.match(e.request).then(cached =>
          cached || fetch(e.request).then(resp => {
            if (!resp.ok && resp.type !== 'opaque') return resp;
            return cache.put(e.request, resp.clone())
              .then(() => trimCache(cache, 80))
              .then(() => resp);
          })
        )
      )
    );
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then(resp => {
        // Cache successful GET responses for HTML/CSS/JS
        if (e.request.method === 'GET' && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      })
      .catch(() =>
        caches.match(e.request, { ignoreSearch: true }).then(cached =>
          cached || (e.request.mode === 'navigate'
            ? caches.match('/real-estate-demo.html')
            : Response.error())
        )
      )
  );
});
