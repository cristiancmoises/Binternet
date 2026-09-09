# Architecture and operating limits

The application uses PHP, Nginx and local CSS, with one optional local JavaScript file for infinite scrolling. Search results are server-rendered and all gallery images use the same-origin image proxy. Manual pages work without JavaScript. There is no database, account system, third-party font, analytics or browser contact with Pinterest during normal browsing. Opening the explicit Pinterest/source links leaves the instance and has the usual third-party privacy implications.

## Request flow

`index.php` renders a GET form. `search.php` validates the query/bookmark, reads preferences, calls the search service and renders cards with responsive proxied images. The search service makes one HTTPS request to Pinterest's existing unauthenticated search resource. The endpoint is unofficial and may change or block the VPS; errors are surfaced and are never replaced with invented results.

The continuation token comes from `resource.options.bookmarks[0]` in the complete Pinterest payload. Explicit empty, malformed or terminal canonical tokens stop pagination instead of reviving a legacy token. Previously supported response shapes remain fallbacks when the canonical field is absent. Tokens are bounded and validated before being passed back in `options.bookmarks`; a token equal to the requested bookmark is discarded. The server renders a real Next page link when a usable continuation remains. See [the pagination repair](PAGINATION_FIX.md).

`image_proxy.php` accepts HTTPS URLs on exactly `i.pinimg.com`, without credentials, fragments or nonstandard ports. It resolves IPv4 addresses, rejects private/reserved destinations, pins the selected public address for the TLS request, disables redirects and environment proxies, verifies TLS, caps decoded bytes, verifies raster type and dimensions, and emits its own MIME and security headers. SVG is not served. The network layer has 3-second connection/10-second transfer deadlines, plus low-speed termination. System DNS resolution precedes the cURL deadline and depends on the host resolver configuration; this is a remaining operational timeout boundary.

Supported raster responses: JPEG, PNG, GIF, WebP and AVIF where the PHP runtime recognizes the format. Images are passed through without lossy re-encoding or upscaling. Search quality depends on variants actually supplied by Pinterest. The Original choice may transfer substantially larger files; images over 8 MiB or 150 megapixels are rejected to bound resource use.

## Cache and concurrency

The cache defaults to `/tmp/binternet-cache`; `BINTERNET_CACHE_DIR` can override it. Docker uses an ephemeral tmpfs. The application does not maintain a separate browser search-history store; ordinary browser history can still contain search URLs. Search cache keys are SHA-256 hashes of versioned query/bookmark tuples. Release 2026.09.08.5 adds the `v3:` key namespace to bypass older parsed entries that discarded valid continuation tokens. Cache contents include image titles, URLs and continuation bookmarks.

- Search fresh lifetime: 120 seconds; stale results up to 600 seconds on contention or provider failure, visibly identified in the page.
- Image fresh lifetime: 24 hours; stale images up to 7 days on failure.
- Maximum cache payload: 64 MiB and 512 entries. Writes evict oldest entries and clean files older than 7 days. Lock files have a fixed count.
- Sixteen nonblocking lock shards coalesce repeated work and bound contention. A request without a cached copy waits at most two seconds for a lock before failing; hash collisions can cause unrelated requests to share a lock.
- Cache writes are atomic and serialized with a nonblocking writer lock. A busy writer may skip caching, while the successful response is still returned.
- Image responses include ETags and cache headers. HTML has `no-store`; browsers may retain image bytes, independently of the server cache.

There is no background scheduler. Cleanup is performed on writes; a quiet cache can retain expired data until the next write or container restart, within its disk bound. The deployment recipe constrains memory, process count, write locations and privileges. Traffic limiting happens in Nginx; behind NPM all clients can share the proxy IP unless a separately audited real-IP policy is configured. The application does not trust arbitrary forwarded client addresses.

## Optional infinite scrolling

Browsing defaults to `scroll=manual`. Selecting Infinite scroll carries `scroll=infinite` through the same GET preferences and pagination links. The page includes `/static/infinite-scroll.js` only when automatic loading can be useful. If scripting or required browser APIs are unavailable, the rendered Next page link continues to work.

An intersection observer requests the next page near the end of the gallery. Only one page request runs at a time. Each request has a 15-second deadline, rejects redirects and accepts at most 2 MiB of HTML. The next URL must stay on the same origin and search endpoint, retain the same query and preferences, and contain a valid bookmark. CSP permits scripts and connections from the same origin only; inline scripts remain disallowed.

Fetched markup is parsed as data. The script validates image-proxy URLs and reconstructs allowed card elements and text; it does not insert fetched scripts or copy arbitrary markup into the active document. Image keys are deduplicated across appended pages. Seen bookmarks prevent automatic request cycles. A response with no new images stops automatic loading; a remaining Next page link can still be used manually. HTTP errors and timeouts pause further automatic requests until an explicit retry. The controls also allow pausing and resuming normal loading.

There is no fixed maximum page count. Provider end markers, missing continuations, repeated pages and errors govern continuation. Already loaded cards remain in the document and the deduplication sets grow with the session. CSS can defer rendering of offscreen page groups, but it does not remove their DOM or guarantee bounded browser memory. Manual pages remain available for long sessions or browsers with less memory.

## Scope boundaries

`health.php` checks PHP extensions and the cache directory, not Pinterest. The deployment candidate checks the local homepage, stylesheet and script. By default it also searches for `architecture`, requires image results and a valid next-page link, follows that link, and requires distinct new images on the second page before cutover. The explicit `--skip-upstream-check` option skips both live page checks while retaining the local checks. These checks do not prove every image is reachable, exercise browser scrolling, or prove that a public reverse proxy has refreshed a cached container address. Keep NPM configured to the stable `binternet:8080` name on a shared Docker network, or the existing host/port route. When NPM has cached an old container IP, saving only the affected proxy host refreshes its upstream configuration; do not restart unrelated services automatically.

See the audit report for executed tests and gaps. There is no claim of a formal penetration test, reproducible Docker dependency snapshot or guaranteed upstream availability.

Pagination cursors are capped at 4096 UTF-8 bytes. Nginx request lines have a 16 KiB buffer; only the exact outbound Pinterest search endpoint permits encoded URLs up to 32 KiB. This accounts for encoding expansion while retaining bounded requests.
