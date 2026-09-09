# Pinterest HTTP 403 compatibility repair — 2026.09.08.3

## Evidence from the VPS

The operator ran release .2 and the isolated diagnostic with PHP 8.4.25 and cURL 8.22.0. Health, home and CSS returned 200; search returned a Binternet error page with HTTP 502. DNS returned one public IPv4 answer, TLS completed, cURL returned no transport error, and Pinterest returned HTTP 403 with 24 non-JSON bytes. The parameters-only baseline comparison also returned 403. Both requests used the same transport headers, so this comparison alone does not establish an IP ban or a user-agent regression.

The diagnostic confirmed the original production container remained running and unchanged, and removed its temporary container. No Nginx/FPM/permission/OOM fault was reported.

## Focused repair

Maintained Pinterest clients include `X-Pinterest-PWS-Handler: www/[username].js` on resource requests. In particular, [yt-dlp PR 12538](https://github.com/yt-dlp/yt-dlp/pull/12538/files) adds this header to address API 403 errors; it remains in the [current Pinterest extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/pinterest.py). The earlier [gallery-dl fix](https://github.com/mikf/gallery-dl/commit/b8b943fc38e6d159db764ec8a4c80ffefc623a45) documents a resource request failing without this header, and its [Pinterest API implementation](https://github.com/mikf/gallery-dl/blob/master/gallery_dl/extractor/pinterest.py) uses the header for BaseSearch requests too.

Binternet .3 adds that single routing header only for `https://www.pinterest.com/resource/BaseSearchResource/get/`. It does not forward the header to image CDN requests. Existing user agent, URL parameters, TLS verification, public address checks/pinning, no-redirect policy, timeouts and response limits are preserved.

This is an evidence-backed compatibility repair, not proof that this particular VPS will be accepted. The candidate must return actual image results before production cutover. A remaining 403 is reported as such; the release does not rotate proxies, borrow user session cookies, or skip the live search gate.

## Failure information

The PHP client keeps fixed error categories and numeric upstream HTTP/cURL codes. Search exposes only sanitized `X-Binternet-Upstream-Status` and `X-Binternet-Upstream-Error` headers and logs numeric metadata. The updater now identifies the failed endpoint and upstream status, for example:

```text
Candidate /search.php returned HTTP 502 (Pinterest HTTP 403; http_status). Candidate validation failed; cutover has not started.
```

Private `failure-diagnostics/failure.json` retains structured `http_error` metadata. Upstream response bodies, cookies, full URLs and query text are excluded from this new metadata.

## Validation limits

See [TEST_RESULTS.txt](TEST_RESULTS.txt) and [AUDIT.md](../AUDIT.md) for executed results. Local tests cover the actual transport function with controlled DNS/cURL I/O, error handling and a real local HTTP 502 response. Existing rendering, security/cache and upgrade simulations are also rerun. This workspace has no Docker daemon and cannot resolve Pinterest; .3's Alpine build, real Pinterest response and VPS cutover remain the deployment command's external checks.

## Português

O diagnóstico da VPS confirmou a recusa HTTP 403 do Pinterest; o 502 é a resposta do Binternet ao receber essa recusa. A versão .3 inclui o cabeçalho de roteamento usado pelos clientes mantidos citados acima, sem alterar os controles de conexão. Também preserva o status do Pinterest nos erros do atualizador.

A correção só estará confirmada na sua VPS quando o candidato retornar imagens reais. O comando de implantação mantém esse teste obrigatório e só substitui a produção depois de aprová-lo. Não é necessário alterar o Nginx Proxy Manager nem baixar outro diagnóstico antes de testar esta versão.
