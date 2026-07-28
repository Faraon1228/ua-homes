// UA Homes Service Worker — PWA offline support
const CACHE = 'ua-homes-v1';
const OFFLINE_ASSETS = [
  '/real-estate-demo.html',
  '/ua-homes-manifest.json',
];

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
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy: network first, fall back to cache
self.addEventListener('fetch', e => {
  // Don't intercept API calls — always go to network
  if (e.request.url.includes('/api/')) return;

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
      .catch(() => caches.match(e.request))
  );
});
