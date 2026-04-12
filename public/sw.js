const CACHE_NAME = 'glass-factory-flow-v3';
const CORE_ASSETS = [
  '/',
  '/index.html',
  '/app.html',
  '/platform.html',
  '/admin.html',
  '/styles.css',
  '/app.js',
  '/client-app.js',
  '/admin-app.js',
  '/manifest.webmanifest',
  '/icon.svg',
];
const NETWORK_FIRST_PATHS = new Set(['/', '/index.html', '/app.js', '/client-app.js', '/admin-app.js']);

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('install', (event) => {
  event.waitUntil(
    Promise.all([
      self.skipWaiting(),
      caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)),
    ])
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      caches.keys().then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      ),
    ])
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== 'GET' ||
    request.url.includes('/v1/') ||
    !['http:', 'https:'].includes(url.protocol) ||
    url.origin !== self.location.origin
  ) {
    return;
  }

  const isShellRequest = request.mode === 'navigate' || NETWORK_FIRST_PATHS.has(url.pathname);

  event.respondWith(
    (isShellRequest
      ? fetch(request)
          .then((response) => {
            if (!response.ok || response.type !== 'basic') {
              return response;
            }

            const clone = response.clone();
            caches
              .open(CACHE_NAME)
              .then((cache) => cache.put(request, clone))
              .catch(() => {});
            return response;
          })
          .catch(() => caches.match(request))
      : caches.match(request).then((cached) => {
          if (cached) {
            return cached;
          }

          return fetch(request).then((response) => {
            if (!response.ok || response.type !== 'basic') {
              return response;
            }

            const clone = response.clone();
            caches
              .open(CACHE_NAME)
              .then((cache) => cache.put(request, clone))
              .catch(() => {});
            return response;
          });
        }))
  );
});