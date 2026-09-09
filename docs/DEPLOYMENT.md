# Docker deployment — 2026.09.08.4

This release upgrades the existing `binternet` container on the IONOS VPS. It does not require a Docker Compose project or change the separate `binternet-candidate-20260907` container.

## Copy and upgrade from your computer

Download `binternet-securityops-2026.09.08.4.tar.gz` to `~/Downloads`. The archive has a single top-level directory named `binternet-securityops-2026.09.08.4`. Run this in fish, bash, or zsh:

```sh
scp -P 5119 ~/Downloads/binternet-securityops-2026.09.08.4.tar.gz root@securityops.co:/root/ && ssh -p 5119 root@securityops.co 'bash -c "set -e; install -d -m 700 /opt/binternet-releases; tar -xzf /root/binternet-securityops-2026.09.08.4.tar.gz -C /opt/binternet-releases; cd /opt/binternet-releases/binternet-securityops-2026.09.08.4; sha256sum --quiet -c MANIFEST.sha256; bash deploy/upgrade.sh"'
```

The VPS needs Docker and Python 3. It builds the image locally and must reach Alpine's package repositories, the image registry, Pinterest, and its image CDN. SSH uses your existing authentication; no credentials are included in this project. The release directory is overwritten if you repeat extraction of this exact release, so keep local source customizations separately.

## What the upgrade does

1. Inspects the running container and writes a mode-0600 snapshot inside a mode-0700 `/opt/binternet-backups/<timestamp-id>/` directory. The snapshot may contain environment secrets; do not share it.
2. Rejects custom mounts/volumes, static container IPs, shared/host networking, privileged mode, devices, custom extra capabilities, and unsupported port mappings before stopping anything. These configurations need an explicit migration instead of silently losing settings.
3. Builds `binternet-securityops:2026.09.08.4` while production continues running. The tested image ID is used for both the candidate and the final replacement.
4. Starts a uniquely named candidate on an automatically allocated `127.0.0.1` port. The existing host ports 5134 and 15134 are not used for the candidate. Checks Docker health, health JSON with the exact release version, the search form, the gallery stylesheet and the local infinite-scroll script. It searches Pinterest for `architecture`, requires a first page with image results and a usable Next page link, follows that link, and requires distinct new images on the second page. Both live pages must pass before cutover.
5. Removes its own candidate, stops production, retains the original container under `binternet-rollback-<timestamp-id>`, and creates the replacement as `binternet`. The retained original has its restart policy temporarily disabled so a host reboot cannot make it reclaim production ports; rollback restores its original policy and retry count. The interruption is limited to this cutover and readiness check; this is not a zero-downtime deployment.
6. Preserves existing published TCP 8080 mappings, including `0.0.0.0:5134`, environment values, restart policy, configured resource limits, DNS/extra-host settings, application labels, Docker networks, and their aliases. Compose ownership labels are intentionally not transferred because this replacement is managed by the upgrade script. Avoid running an older Compose file afterward: it could replace this release.
7. Confirms the replacement is healthy. A cutover failure triggers restoration of the retained original container, including its name and network aliases. The exact manual rollback command is printed on success.

Environment values must fit a Docker env file; multiline values are rejected. Cache paths must be inside `/tmp`. The default memory ceiling is 1536 MiB when the original has no explicit limit; an existing limit is retained. Allow space and memory for production and the temporary candidate together while testing.

If Pinterest is unavailable, the default candidate check prevents cutover. To deliberately accept that search availability is unverified, run on the VPS:

```sh
bash /opt/binternet-releases/binternet-securityops-2026.09.08.4/deploy/upgrade.sh --skip-upstream-check
```

This option skips both live Pinterest page checks. Local health, the homepage, stylesheet and script checks still run. It does not solve an upstream block, outage or pagination bug.

## Nginx Proxy Manager

The updater preserves all attached Docker networks and the `binternet` service name. It does not restart or reconfigure `npm-attachment`. A proxy host already using `http://binternet:8080` on a shared Docker network can keep those settings. A proxy using the VPS address and port 5134 retains the same published binding.

If the local health check passes but the public route returns 502, NPM may still have cached the previous container IP. Save only this affected Proxy Host in NPM to refresh its configuration; no broad proxy restart is needed.

After upgrading, verify the public URL configured in NPM as well as the local endpoint:

```sh
ssh -p 5119 root@securityops.co 'docker ps --filter name=binternet; curl --fail --silent --show-error http://127.0.0.1:5134/health.php'
```

The health endpoint tests application dependencies/cache access; it does not contact Pinterest. The candidate's separate first- and second-page checks test upstream search and continuation at deployment time. Continued Pinterest availability cannot be guaranteed.

## Rollback

Keep the stopped original container until you are satisfied with the new release. Do not prune stopped containers during this period. Run the exact command printed by the updater, for example on the VPS:

```sh
python3 /opt/binternet-backups/TIMESTAMP-ID/upgrade.py rollback /opt/binternet-backups/TIMESTAMP-ID/deployment.json
```

Replace `TIMESTAMP-ID` with the directory printed during your actual deployment. The rollback helper is copied beside the snapshot and remains usable if you remove the extracted source directory. It verifies ownership before removing the replacement and refuses to remove an unrelated container. It also verifies that the retained original exists before removing the active replacement.

Automatic restoration covers normal command failures, Ctrl+C, SIGTERM, and SSH hangup after cutover begins. Power loss, Docker daemon failure, and SIGKILL can interrupt restoration; use the saved rollback helper after the host is available. The updater and rollback share a host lock so two copies cannot cut over simultaneously.

## Fresh installation

`docker-compose.yml` is for a new installation with no container named `binternet`:

```sh
docker compose up -d --build
```

It publishes `127.0.0.1:5134`. For containerized NPM, attach `binternet` to the existing network shared with NPM, using that network's real name, then configure `http://binternet:8080`. Use the upgrade script for the current IONOS deployment instead of starting a second Compose container with a conflicting name.

## Runtime and verification

The image uses Alpine 3.24 and PHP 8.4. Nginx and PHP-FPM run as an unprivileged user under `tini`; a supervisor exits the container if either service exits. The root filesystem is read-only, Linux capabilities are removed, privilege escalation is disabled, and `/tmp`, `/run`, and Nginx temporary storage use bounded tmpfs mounts. The cache is disposable and is not carried across upgrades.

Only the five public PHP endpoints, CSS/image assets, the exact `/static/infinite-scroll.js` script and the exact `/source.tar.gz` download are served. The download is generated during the Docker build and contains this deployed version’s corresponding source, license, build/deployment files, tests, and documentation; it excludes Git metadata, environment secrets, caches, and generated artifacts. Review the build context before adding private files to a fork, because the source download intentionally makes the included source public. Repository metadata, library code, deployment scripts, tests, and documentation are not web routes. Content Security Policy allows scripts and fetch requests only from the same origin (`script-src 'self'; connect-src 'self'`) and prohibits inline scripts and styles. The local script is loaded only when infinite scrolling is selected and another result page is available; manual pages work without JavaScript. Nginx logs paths without query strings, applies search/image request budgets, and excludes health checks from those budgets. Behind NPM, rate budgets apply to its aggregate address because arbitrary forwarded client headers are not trusted.

Run deployment logic tests with:

```sh
python3 -m unittest discover -s deploy -p 'test_*.py' -v
```

These tests exercise configuration preservation, private file permissions, candidate failure, cutover failure/restoration, image-ID pinning, and protection of unrelated containers with a mocked Docker interface. They do not substitute for a Docker build or production smoke test. The operator confirmed release .3 working on the VPS. This development environment has no Docker daemon and cannot run live Pinterest or real-browser checks. The .4 image build, both live pagination checks and browser verification remain external checks. No VPS login or .4 deployment was performed while preparing this release.

## Startup failure diagnostics

The startup repair introduced in 2026.09.08.2 fixes the observed `/var/lib/nginx/tmp/proxy` read-only startup failure. All five Nginx temporary directories now point into the existing tmpfs. Nginx uses `-e stderr` so even early startup logs avoid Alpine's compiled default log path. The protections remain enabled.

If a candidate fails, the updater prints a private `failure-diagnostics` directory under the deployment backup. It saves container logs, state/health, inspect data and Docker operation errors before cleanup. These files can contain sensitive configuration; share only the relevant error lines.


## Pinterest API compatibility in .3

The .2 candidate was healthy but Pinterest returned HTTP 403. Release .3 adds the resource routing header used by maintained clients. The normal command above still requires actual image results before cutover. If the request is refused again, the error identifies `/search.php` and `Pinterest HTTP 403`, with structured metadata in the private `failure-diagnostics/failure.json`. See [repair evidence](PINTEREST_403_FIX.md).


## Pagination and optional infinite scrolling in .4

The parser now reads `resource.options.bookmarks[0]`, with explicit end markers taking precedence over legacy metadata. Search cache keys use a new `v2:` namespace so a cached .3 result that lost its continuation does not hide the repaired link. Manual pages remain the default; choosing Infinite scroll carries `scroll=infinite` in search and pagination URLs.

The browser loads one same-origin page at a time, with a 15-second deadline and a 2 MiB HTML response limit. It rebuilds allowed image cards from validated data, removes duplicate images, and stops automatic requests on repeated pages or errors. Pause, Retry loading and Next page remain available as appropriate. There is no fixed page ceiling; retained cards still consume browser memory as a session grows. See [pagination repair and verification limits](PAGINATION_FIX.md).
