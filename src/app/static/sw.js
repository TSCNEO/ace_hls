const CACHE_NAME = 'acehls-v2.5.0-dev';
const urlsToCache = [
    '/',
    '/index.html',
    '/style.css',
    '/script.js',
    '/vendor/hls.min.js',
    '/placeholder.svg'
];

function shouldBypassCache(request) {
    if (request.method !== 'GET') return true;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return true;
    if (url.pathname.startsWith('/api/')) return true;
    if (url.pathname.startsWith('/hls/')) return true;
    if (url.pathname.endsWith('.m3u8')) return true;
    if (url.pathname.endsWith('.ts')) return true;
    return false;
}

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache).catch(err => console.error(err));
            })
    );
    self.skipWaiting();
});

self.addEventListener('fetch', event => {
    if (shouldBypassCache(event.request)) {
        event.respondWith(fetch(event.request));
        return;
    }

    event.respondWith(
        fetch(event.request).then(response => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
            return response;
        }).catch(() => {
            return caches.match(event.request);
        })
    );
});

self.addEventListener('activate', event => {
    const cacheWhitelist = [CACHE_NAME];
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheWhitelist.indexOf(cacheName) === -1) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});
