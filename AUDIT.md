# Binternet 2026.09.08.5 audit

Date: 2026-09-09. Base: `b8dc197b4930b50ba7356d579d684182e93af428` from [cristiancmoises/Binternet](https://github.com/cristiancmoises/Binternet/tree/b8dc197b4930b50ba7356d579d684182e93af428).

## Cursor-size repair in .5

The operator supplied a healthy .4 candidate and a prepared-phase failure: no valid Next page link. A published Pinterest response contains a valid 2064-byte cursor, exceeding .4’s 2048-byte cap. This demonstrates a compatibility defect; the actual VPS cursor length remains unobserved. Release .5 uses a consistent 4096-byte bound, cache v3, a 16 KiB local request-line capacity and a 32 KiB URL limit scoped to the exact upstream search endpoint. Synthetic fixtures cover 2064/4096/4097 bytes, UTF-8 byte counting and worst-case JSON/percent-encoding expansion. The exact candidate checker traversed two actual local PHP pages with a 2064-byte cursor and distinct images; only Docker inspection was mocked. The mandatory live two-page gate remains unchanged. See the fixture source in [PAGINATION_FIX.md](docs/PAGINATION_FIX.md).

The optional pinned-.4 diagnostic has six lifecycle/HTTP/privacy regression tests and seven PHP metadata boundary/privacy fixture checks. It never performs cutover and excludes raw cursors, response bodies and environment values from its public report.

## Pagination repair and optional infinite scrolling

The missing Next page control was traced to the parser ignoring canonical `resource.options.bookmarks[0]` metadata. Release .4 reads this cursor, respects explicit end/invalid metadata, supports legacy fields when canonical metadata is absent and uses cache v2; .5 advances this to v3. Raw first/second/end responses are exercised through the parser and real local HTTP pages. Infinite mode is explicitly selected; manual pages remain the default and work without JavaScript.

The optional self-hosted script constrains continuation URLs to the same query/preferences/origin, limits each HTML response to 2 MiB and one active request with a 15-second deadline, rebuilds safe image-card DOM, filters duplicates and stops on errors/cycles. Pause/retry controls and real continuation links remain available. Each page uses a separate gallery section. There is no artificial total page limit; long sessions retain DOM nodes and must still be assessed in an actual browser. The VPS candidate now checks both live pages for distinct image URLs before cutover. See [PAGINATION_FIX.md](docs/PAGINATION_FIX.md).

## Confirmed VPS failure and API compatibility repair

The user built .2 and supplied a diagnostic showing healthy PHP/Nginx, working DNS/TLS/cache, and HTTP 403 from Pinterest before JSON processing. Health/home/CSS passed; search correctly failed the candidate gate with local 502. Production remained the same running container. Release .3 adds the routing header present in maintained yt-dlp/gallery-dl clients and preserves sanitized upstream error metadata through deployment validation. The user subsequently confirmed that .3 worked. This is user-reported VPS evidence; .5 has not been deployed here. No IP-ban conclusion is made. See [PINTEREST_403_FIX.md](docs/PINTEREST_403_FIX.md) for source evidence and limits.

## Confirmed startup repair

The user successfully built 2026.09.08.1 on the IONOS VPS, then provided runtime logs proving Nginx failed to create `/var/lib/nginx/tmp/proxy` on the read-only root filesystem while PHP-FPM was ready. Release 2026.09.08.2 explicitly places all five Nginx temp paths in the existing tmpfs and selects stderr before configuration parsing. Startup configuration checks and private failure evidence are added. See [STARTUP_FIX.md](docs/STARTUP_FIX.md) for the evidence and fix. The subsequent user-supplied .2 diagnostic confirms that startup repair worked on the VPS. The operator built .4, but its two-page gate failed before cutover. The .5 image has not been built or deployed here.

## Outcome and scope

The source was reviewed, improved and tested locally. This is a source-level security and functional review with offline fixtures and simulated deployment failures. It is **not** a completed production penetration test or a claim that every vulnerability has been found. No VPS connection, remote deployment, repository push or GitHub workflow execution was performed.

Reviewed areas: all public PHP entry points, shared rendering, query/bookmark validation, upstream response parsing, outbound HTTP restrictions, image validation, cache bounds and locking, themes/layout forms, Nginx routes/headers/traffic budgets, Docker runtime and source packaging, upgrade/rollback state transitions, and CI definitions.

## Executed evidence

| Check | Result | What it establishes |
| --- | --- | --- |
| PHP syntax | 14 files passed | Current PHP source parses on the local PHP 8.3 runtime. |
| Security regression suite | 27 test groups passed | Parameter, URL, DNS-address classification, chunk callback, raster validation, provider parsing, cache expiry/count/byte and stale-fallback behavior; actual transport function with controlled DNS/cURL fixtures verifies API header scoping and typed failures. |
| HTTP integration suite | 16 passed; 2 Docker/nginx-only checks skipped | Real local PHP HTTP requests using private, test-seeded caches; includes all 20 gallery × quality combinations, escaping, preferences, pagination, images, headers and assets. |
| Upgrade/rollback and HTTP-failure regression suite | 41 passed (Docker simulated; HTTP pagination/error tests use real local servers) | Simulated Docker configuration/state transitions, candidate failure, failed cutover restoration, image-ID pinning, retained-container policy and unrelated-container protection, upstream status preservation and exclusion of cookies/bodies/query terms from HTTP error metadata. |
| Nginx syntax, startup and route checks | 7 passed with actual local Nginx | A regression requires all temporary paths in the writable mount; an actual local Nginx run exercises the adapted configuration and serves CSS/JavaScript with the correct MIME/CSP while protecting private paths. Paths/includes/port and process mode are adapted for this environment. This does not establish actual Alpine container/FPM startup. |
| JavaScript pagination state machine and safe DOM construction | 18 Node tests passed | Concurrency, URL/context validation, duplicate/end/cycle handling, explicit retry, pause, timeout/cancellation, byte cap and safe card construction. Unit fixtures do not establish actual browser layout or scrolling. |
| Shell/Python checks | Passed | ShellCheck for both shell entry points, Python compilation, fish syntax for the exact copy-and-deploy command, and `git diff --check`. |
| Live Pinterest request | Blocked by environment | `gethostbynamel('www.pinterest.com')` returned false; no real search response could be validated here. |
| Browser visual inspection | Blocked by environment | The available browser rejected local navigation with `ERR_BLOCKED_BY_CLIENT`; no visual, mobile-device or screen-reader validation is claimed. |
| Actual Docker build/runtime, PHP 8.4 matrix, GitHub CI, VPS/NPM smoke test | Not executed here | Docker is not available in the workspace. Container and source-archive tests are authored in CI; the VPS upgrade executes a real build and candidate checks before cutover. |

`docs/TEST_RESULTS.txt` contains the final commands/results without secrets. HTTP tests explicitly skip Docker-generated source downloads and Nginx-only routes when using the PHP development server. Those skips are expected and are not reported as passes. The test-only seeded images/results are never enabled by a production configuration switch.

## Findings addressed

| Baseline finding | Impact | Resolution |
| --- | --- | --- |
| Canonical cursor outside resource_response was ignored | Next page disappeared despite available continuation | Parse canonical metadata with precedence/end validation, invalidate old parsed caches and prove second-page traversal. |
| Manual-only browsing interrupted long image sessions | Each continuation required a page navigation | Optional same-origin infinite mode with one bounded request, sanitized append, duplicate/loop guards and manual fallback. |
| Request arrays and invalid values entered string operations | PHP errors and unstable responses | Scalar, length, UTF-8 and control-character validation before output/network use; safe preference allowlists. |
| Query escaped before network use, then escaped again in HTML | Incorrect searches and double encoding | Preserve raw validated query; escape only when rendering HTML or encoding URLs. |
| Search had no cURL deadline/streaming byte cap or reliable HTTP failure handling | Worker exhaustion and misleading empty results | Bound connect/transfer/decoded bytes; check HTTP success, JSON shape and provider response; show useful errors. |
| User-provided CSRF value entered upstream request headers | Unnecessary trust in caller-controlled header data | Remove client token forwarding; request continuation through bounded GET parameters. |
| Proxy trusted any `image/*` header and accepted HTTP/custom ports/userinfo | Active image formats, ambiguous content and unnecessary network exposure | HTTPS on exact CDN host; reject credentials/fragments/non-443 ports; verify raster bytes and dimensions; emit own MIME. |
| `CURLOPT_MAXFILESIZE` was the only response-size defense | Unknown-length/chunked bodies could exceed intended bound | Write callback checks every decoded chunk before appending. |
| Allowed-host resolution was not pinned to a verified destination | DNS destination uncertainty | Reject private/reserved IPv4 results and pin the chosen public address; redirects and environment proxy use disabled. |
| Every gallery thumbnail requested an original | High transfer cost and slow perceived search | Responsive source variants, quality controls, lazy decoding/loading, dimensions, image caching and ETags; exact original remains linked. |
| No bounded result/image cache | Repeated upstream work | Atomic caches with fixed lock shards, 64 MiB/512-entry caps, expiry and bounded stale fallback. |
| Compose referenced the original upstream registry image | Custom fork changes absent at deployment | Build the delivered local source and tag the SecurityOps release. |
| Full repository lived under the web root without comprehensive path restrictions | Potential code/config/metadata disclosure | Explicit public endpoint and static-asset routes; deny unmatched paths. |
| Modified source could differ from the GitHub footer link | Download did not match deployed code | Build and serve a filtered corresponding-source archive at exact `/source.tar.gz`; keep repository link separately. |
| Nginx inherited Alpine proxy/SCGI/uWSGI temporary paths outside writable tmpfs | Confirmed candidate startup failure on the VPS | Configure all five paths explicitly under `/var/cache/nginx`; use early `-e stderr`; validate configuration before launch. |
| Pinterest resource request lacked the routing header used by maintained clients | API compatibility gap associated with HTTP 403 in those clients; .2 receives 403 on the VPS | Add the header only to the exact search resource endpoint; retain the live VPS result gate to verify this repair. |
| Transport discarded HTTP status/cURL error and deployment reported only generic 502 | Required separate diagnosis to distinguish upstream refusal from local failure | Typed bounded failure metadata, sanitized application headers/logs and endpoint/upstream status in private deployment evidence. |
| Failed candidate was removed before retaining startup evidence | Missing root-cause logs | Capture private Docker logs, inspect, state/health and operation errors before cleanup. |
| Existing-container replacement needed configuration preservation and recovery | Port/network changes or an unrecoverable cutover | Snapshot privately, reject unsupported custom setups before stopping, validate separate candidate, preserve bindings/networks and retain/restore the old container. |
| Retained container with `restart=always` could restart after daemon reboot | Port conflict with replacement | Disable retained restart policy and restore its exact original policy during rollback. |

## Remaining limits and operational checks

1. **Pinterest availability/schema.** This is an unofficial upstream resource. Authentication changes, rate limits, empty results, CDN variants or VPS blocking can still prevent results. The candidate requires a real first page, a usable continuation and distinct second-page images by default; it refuses cutover on failure. A short or temporarily inconsistent result set can fail this deliberately strict gate. `--skip-upstream-check` is an explicit operator opt-out, not a fix.
2. **Actual container dependency/runtime validation.** The recipe uses Alpine 3.24/PHP 8.4; packages are resolved at build time rather than pinned to a complete immutable snapshot. [Alpine's release policy](https://alpinelinux.org/releases/) states the community repository is supported until the next stable release. Keep the base/extension packages updated, run the CI container job and scan the built image before making any claim about its CVE state. No CVE scan or SBOM-based vulnerability check was executed here.
3. **DNS deadline.** `gethostbynamel` runs before cURL's 10-second transfer deadline and depends on the system resolver. The production FPM worker has a 25-second request termination limit; the CLI/development server does not supply that production bound.
4. **Resource bounds trade off image coverage.** Only supported raster images up to 8 MiB, 30,000 pixels per side and 150 megapixels are proxied. Extremely large originals, SVG, malformed content and unsupported variants are rejected. No universal speed or original-image availability guarantee is made.
5. **Cache/data retention.** Server caches can contain image URLs/titles and bookmarks. Writes evict by size/count and clean old entries; quiet caches may retain expired data until the next write/restart. Browser image caches have separate lifetimes. Nginx instance logs omit query strings, but the user's existing NPM logging policy is outside this package.
6. **NPM and custom Docker configuration.** Existing networks/names/bindings are preserved. A proxy that caches the old IP may need only the affected Proxy Host saved after a successful local health check. Custom mounts, static IPs, privileged/device settings and certain unusual network configurations are rejected for an explicit migration. Power loss/SIGKILL/daemon failure may require the saved manual rollback helper.
7. **Visual/accessibility/performance evidence.** Semantic labels, focus styling and reduced-motion rules are implemented, and HTML/preference/layout cases are tested. Actual visual comparison, assistive technology, low-end mobile rendering and concurrent live load remain to be evaluated. No invented Lighthouse score, security score or live speedup is reported.
8. **Supply chain and repository controls.** Existing GitHub actions use version tags. Review workflow permissions, pin actions by reviewed commit if desired, and configure required checks/branch protection in the actual repository. CI files in this archive are not evidence of remote CI completion.

The complete reproducible local test commands are in README.md and the deployment docs. The next-stage prompt focuses on the concrete external checks above.
