FROM alpine:3.24 AS source
COPY . /source/
RUN tar -czf /source.tar.gz -C /source .

FROM alpine:3.24

RUN apk add --no-cache ca-certificates nginx tini \
      php84 php84-fpm php84-curl php84-dom php84-fileinfo \
      php84-mbstring php84-opcache php84-openssl \
    && mkdir -p /var/www/binternet /run/php /var/cache/nginx \
    && rm -f /etc/nginx/http.d/default.conf \
    && chown -R nginx:nginx /run /var/cache/nginx /var/log/nginx

COPY deploy/nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/http.d/binternet.conf
COPY deploy/php-fpm.conf /etc/php84/php-fpm.conf
COPY deploy/php.ini /etc/php84/conf.d/99-binternet.ini
COPY deploy/entrypoint.sh /usr/local/bin/binternet-entrypoint
COPY index.php search.php image_proxy.php donate.php health.php /var/www/binternet/
COPY misc/ /var/www/binternet/misc/
COPY static/ /var/www/binternet/static/
COPY lib/ /var/www/binternet/lib/
COPY --from=source /source.tar.gz /var/www/binternet/source.tar.gz
RUN chmod 755 /usr/local/bin/binternet-entrypoint

ENV BINTERNET_CACHE_DIR=/tmp/binternet-cache
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/health.php || exit 1
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/binternet-entrypoint"]
