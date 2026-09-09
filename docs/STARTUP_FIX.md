# Read-only Nginx startup fix — 2026.09.08.2

## Confirmed evidence

The user successfully built release 2026.09.08.1 on the IONOS VPS using Alpine 3.24, PHP 8.4.25 and Nginx 1.30.4. The candidate then exited. A separate diagnostic run showed:

```
nginx: could not open error log file: /var/lib/nginx/logs/error.log (Read-only file system)
nginx: mkdir() /var/lib/nginx/tmp/proxy failed (Read-only file system)
fpm is running
ready to handle connections
```

The fatal failure is an omitted Nginx temporary-path override. PHP-FPM was ready. The startup supervisor correctly stopped PHP-FPM after Nginx failed, and the deployment failed before production cutover.

## Correction

The root filesystem remains read-only. No extra privilege or writable mount is added.

| Nginx purpose | Explicit writable path |
| --- | --- |
| Client request bodies | `/var/cache/nginx/client_temp` |
| FastCGI | `/var/cache/nginx/fastcgi_temp` |
| HTTP proxy | `/var/cache/nginx/proxy_temp` |
| SCGI | `/var/cache/nginx/scgi_temp` |
| uWSGI | `/var/cache/nginx/uwsgi_temp` |

All paths reside in the already configured 16 MiB tmpfs. The entry point creates all five directories and checks the FPM/Nginx configurations before launching services. Both Nginx validation and startup use `-e stderr`, which selects the initial error log before parsing configuration. See [Nginx command-line parameters](https://nginx.org/en/docs/switches.html), [proxy temporary paths](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_temp_path), [SCGI paths](https://nginx.org/en/docs/http/ngx_http_scgi_module.html#scgi_temp_path) and [uWSGI paths](https://nginx.org/en/docs/http/ngx_http_uwsgi_module.html#uwsgi_temp_path).

The updater now saves private failure evidence before candidate removal. It does not weaken candidate health, CSS or live search checks.

## Validation limits

Regression tests exercise effective Nginx paths and actual local Nginx startup/static HTTP routing with adapted temporary paths. The available local Nginx differs from the VPS Alpine build; no new Docker/VPS deployment is claimed here. The supplied upgrade command performs the real image build and candidate check on the VPS before replacing production.

## Português

A falha vinha de diretórios temporários padrão do Nginx que não estavam no tmpfs. A correção define os cinco caminhos e encaminha o log inicial para stderr. O contêiner continua sem privilégios, com sistema de arquivos somente para leitura. O pacote também guarda logs do candidato antes de removê-lo, caso ocorra outra falha. Use as instruções atualizadas de implantação; o contêiner atual permanece ativo durante a construção e validação do candidato.
