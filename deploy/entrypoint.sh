#!/bin/sh
set -eu
mkdir -p /run/php /var/cache/nginx/client_temp /var/cache/nginx/fastcgi_temp \
    /var/cache/nginx/proxy_temp /var/cache/nginx/scgi_temp /var/cache/nginx/uwsgi_temp
# -e applies before Nginx parses the config, avoiding Alpine's read-only log path.
# Validate before either long-running service is started.
/usr/sbin/php-fpm84 --test
/usr/sbin/nginx -e stderr -t
php_pid=
nginx_pid=
shutdown() {
    trap '' TERM INT
    [ -z "$nginx_pid" ] || kill -TERM "$nginx_pid" 2>/dev/null || true
    [ -z "$php_pid" ] || kill -TERM "$php_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap 'shutdown; exit 0' TERM INT
/usr/sbin/php-fpm84 --nodaemonize &
php_pid=$!
/usr/sbin/nginx -e stderr -g 'daemon off;' &
nginx_pid=$!
while kill -0 "$php_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
    sleep 1 &
    wait $! || true
done
echo 'A web service exited; shutting down the container.' >&2
shutdown
exit 1
