# Binternet · SecurityOps

A lightweight Pinterest image browser with no login wall and a same-origin image proxy. Manual browsing works without JavaScript; infinite scrolling is optional. This package extends [cristiancmoises/Binternet](https://github.com/cristiancmoises/Binternet) from commit `b8dc197b4930b50ba7356d579d684182e93af428`.

Release: **2026.09.08.4**.

## What changed

Release 2026.09.08.4 restores the next-page link by reading Pinterest's canonical continuation bookmark and adds optional infinite scrolling. Deployment now checks two live result pages before cutover. See [pagination repair and limits](docs/PAGINATION_FIX.md). The [API compatibility repair from .3](docs/PINTEREST_403_FIX.md) and the read-only Nginx startup repair from .2 are retained.

- **Five themes:** Black (default), Charcoal, Midnight, Paper and Forest.
- **Five galleries:** Masonry, Grid, Compact, Justified and Focus.
- **Image quality:** automatic responsive previews, high quality, original resolution and a data-saver option. Original files remain available through the local proxy. Images are never artificially upscaled or recompressed.
- **Faster repeat searches:** bounded server caches, request coalescing, browser image caching and lazy loading. Cold search speed and availability still depend on Pinterest.
- **Usable without JavaScript:** search, preferences, pagination and image opening use ordinary forms and links. Preferences are carried in the URL.
- **Optional infinite scrolling:** choose Infinite scroll in Browsing to append more results as you approach the end of a page. Pause and retry controls are provided; the Next page link remains the manual fallback. Manual pages are the default.
- **Hardened requests:** HTTPS image-host allowlist, public IPv4 destination pinning, no redirects, byte/time limits, raster validation and escaped output.
- **Controlled VPS replacement:** build and verify a separate Docker candidate, preserve production bindings and networks, retain the previous container and automatically restore it if cutover fails.

## Deploy on the existing IONOS VPS

See [English instructions](docs/DEPLOYMENT.md) or [Instruções em português](docs/DEPLOYMENT.pt-BR.md). They include copy-and-deploy commands for `root@securityops.co`, SSH port `5119`, the existing `binternet` container and host port `5134`.

For a fresh local Docker instance:

```sh
docker compose up -d --build
```

The fresh Compose service uses a loopback port and builds **this directory**. Use the existing-container upgrade script for the IONOS installation so current Docker networks and port bindings are preserved. Do not run a fresh Compose stack over an existing production name.

## Test

PHP 8.3 or 8.4 with curl, mbstring and DOM, Python 3, Node.js for the script tests, and Docker for container tests:

```sh
find . -type f -name '*.php' -not -path './.git/*' -print0 | xargs -0 -n1 php -l
php tests/security.php
python3 tests/integration.py
node --test tests/infinite-scroll.test.js
NGINX_BIN=nginx python3 -m unittest discover -s tests -p 'test_nginx_runtime.py' -v
python3 -m unittest discover -s deploy -p 'test_*.py' -v
```

The CI workflow additionally builds the hardened Docker image and checks route exposure. See [AUDIT.md](AUDIT.md) for exact evidence and remaining checks; an authored CI job is not a claim that it has already passed on GitHub. Release .3 was confirmed working by the VPS operator. The .4 Docker build, live Pinterest pagination and browser behavior still need verification on a host that can run them.

## Technical details

Read [architecture and limits](docs/ARCHITECTURE.md), [changelog](CHANGELOG.md), [executed upgrade prompt](UPGRADE_PROMPT.md) and [next development prompt](docs/NEXT_PROMPT.md).

Pinterest's unauthenticated endpoint is unofficial. It may change, return no results or block requests from a particular VPS. The application reports those failures and can show explicitly marked recent cached results. The health endpoint checks the local application; deployment separately requires a first result page, a usable continuation link and new images on the second page before cutover by default. Infinite scrolling has no fixed page ceiling, but ends when Pinterest stops providing results or repeats pages. Images already appended remain in the document, so long sessions use more browser memory.

## Attribution and license

Binternet originated with Ahwxorg, with image-proxy and utility contributions from LibreX/LibreY. Original upstream information and historical instance listings are preserved in [UPSTREAM_README.md](docs/UPSTREAM_README.md); those listings have not been reverified. The existing [AGPL-3.0 license](LICENSE) remains unchanged. A matching copy of the running source is available at `/source.tar.gz` in the Docker build. The donation page clearly attributes its preserved donation links to the original upstream author.

Binternet is not affiliated with Pinterest Inc. Images and trademarks belong to their respective owners. The image proxy temporarily caches content to operate the service; this is not a grant of permission to reuse an image. Report content issues to the originating platform.
