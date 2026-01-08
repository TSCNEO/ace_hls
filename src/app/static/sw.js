const CACHE_NAME = 'acehls-v1';
const urlsToCache = [
    '/',
    '/static/index.html', // mapped by Flask often, but keeping generic
    'https://cdn.vidstack.io/player/theme.css',
    'https://cdn.vidstack.io/player/video.css',
    'https://cdn.vidstack.io/player'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                // We catch errors here so one failed file doesn't break everything
                return cache.addAll(urlsToCache).catch(err => console.error(err));
            })
    );
});

self.addEventListener('fetch', event => {
    // Network first for API, Cache first for assets?
    // For simplicity: Network First, falling back to cache
    event.respondWith(
        fetch(event.request).catch(() => {
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
});
