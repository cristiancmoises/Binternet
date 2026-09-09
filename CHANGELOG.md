# Changelog

## 2026.09.08.4

- Restore Next page using the canonical Pinterest `resource.options.bookmarks[0]` cursor and invalidate incorrectly parsed search caches. Retain legacy cursor support and stop on malformed, terminal or repeated cursors.
- Add optional infinite scrolling alongside manual pages, preserving all appearance and quality settings. Keep Next page available without JavaScript and after loading errors.
- Load one bounded same-origin request at a time; append sanitized, lazy-loaded image cards in separate gallery sections, filter duplicates, expose pause/retry/status controls and stop on provider end or repeated results. No artificial total page cap; long sessions retain DOM nodes.
- Require the candidate JavaScript asset and distinct images across two live search pages before production cutover. Preserve explicit upstream opt-out and rollback.
- Add cursor, HTTP, JavaScript and deployment pagination regressions; retain all previous runtime and transport protections.

## 2026.09.08.3

- Add the documented `X-Pinterest-PWS-Handler: www/[username].js` routing header only to the Pinterest search API request, following maintained gallery-dl/yt-dlp clients. The VPS .2 diagnostic confirmed upstream HTTP 403; .3 still requires the real candidate search to prove compatibility on this VPS.
- Retain numeric upstream status and fixed error categories instead of discarding cURL/HTTP failure evidence. Search explains Pinterest refusal and rate limiting without exposing response bodies, cookies or user queries.
- Report the failing local endpoint and Pinterest status during candidate validation; preserve this sanitized metadata in private failure evidence before cleanup.
- Extend transport/error and deployment regressions. Keep the existing image quality modes, themes, galleries, non-root/read-only runtime, mandatory live candidate gate and rollback.

## 2026.09.08.2

- Fixed the observed Alpine Nginx startup failure under a read-only root filesystem: proxy, SCGI and uWSGI temporary paths now use the existing bounded `/var/cache/nginx` tmpfs, alongside client/FastCGI temporary paths.
- Direct the initial Nginx error log to stderr before configuration parsing; validate PHP-FPM/Nginx configuration before launching services.
- Preserve private failed-candidate logs, state/health and Docker errors before cleanup, and print their location.
- Added regression coverage for startup paths and failed-candidate diagnostics; retained non-root execution, read-only root, dropped capabilities, existing port/network preservation and rollback.

## 2026.09.08.1

Based on cristiancmoises/Binternet `b8dc197b4930b50ba7356d579d684182e93af428`.

- Added true black, charcoal, midnight, paper and forest themes.
- Added masonry, grid, compact, justified and focus galleries, responsive images and explicit quality modes.
- Reworked search forms, keyboard focus, result metadata, empty/error handling and pagination; preferences travel in links and forms without JavaScript.
- Added bounded search/image caching, stale fallback, ETags, upstream timeouts and fixed lock shards.
- Corrected double-escaped search queries, malformed array inputs and unbounded upstream responses.
- Restricted the image proxy to HTTPS image CDN requests with public-address pinning, no redirects, byte limits and raster validation.
- Hardened web route exposure and the non-root Docker runtime; updated Compose to build this source tree.
- Added candidate-first VPS upgrades, configuration snapshots and automatic/manual rollback, without reusing the existing candidate's port.
- Added regression, HTTP and deployment simulation tests, CI gates, bilingual deployment documentation and an evidence-based audit report.
