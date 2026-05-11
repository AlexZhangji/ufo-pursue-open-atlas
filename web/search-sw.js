/* PURSUE search service worker
 *
 * Cache-first for everything the search page needs to function:
 *   - search.html
 *   - search_index/* (meta.json · documents.json · embeddings.f16.bin)
 *   - thumbs/*.jpg (lazy-populated as the grid scrolls)
 *   - the three CDN deps (minisearch · marked · transformers.js wrapper)
 *
 * NOT cached here:
 *   - transformers.js model weights — the library uses IndexedDB itself
 *     (env.useBrowserCache = true in search.html), and double-caching the
 *     ~25 MB of ONNX blobs would just waste storage.
 *
 * Bump CACHE_VERSION when search_index/* gets rebuilt. The activate step
 * deletes any cache whose name doesn't match the current version, so old
 * indexes get garbage-collected on the next reload.
 */

const CACHE_VERSION = 'pursue-search-v8';

// Listed for documentation, not for install-time prefetch — we let the
// first page load drive the cache populate so the user doesn't pay 13 MB
// twice (once via fetch, once via SW prefetch).
const KNOWN_PATHS = [
  './search.html',
  './search_index/meta.json',
  './search_index/documents.json',
  './search_index/embeddings.f16.bin',
];

self.addEventListener('install', (event) => {
  // Skip waiting so a new SW takes over without requiring a tab close.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n !== CACHE_VERSION).map((n) => caches.delete(n))
    );
    await self.clients.claim();
  })());
});

function shouldCache(url) {
  // Only handle GET requests we know are static / immutable per CACHE_VERSION.
  if (url.pathname.endsWith('/search.html')) return true;
  if (url.pathname.includes('/search_index/')) return true;
  if (url.pathname.includes('/thumbs/')) return true;
  if (url.host === 'cdn.jsdelivr.net') return true;
  if (url.host === 'fonts.googleapis.com') return true;
  if (url.host === 'fonts.gstatic.com') return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch { return; }
  if (!shouldCache(url)) return;

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_VERSION);
    const hit = await cache.match(req);
    if (hit) return hit;

    // Miss → fetch + cache. We use ignoreSearch:false above so query-stringed
    // URLs (transformers.js sometimes adds ?revision=…) are cached separately,
    // which is correct.
    try {
      const resp = await fetch(req);
      // Only cache successful, non-opaque responses. Opaque (cross-origin no-cors)
      // would still cache but we can't read them for diagnostics.
      if (resp && resp.status === 200) {
        cache.put(req, resp.clone()).catch(() => {});
      }
      return resp;
    } catch (e) {
      // Offline & not in cache: let the browser show its default error.
      throw e;
    }
  })());
});

// Allow the page to nuke the cache (e.g. after we ship a new index build).
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'PURGE_CACHE') {
    event.waitUntil((async () => {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
      event.source && event.source.postMessage({ type: 'PURGE_OK' });
    })());
  }
});
