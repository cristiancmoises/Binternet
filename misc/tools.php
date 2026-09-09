<?php
// Compatibility helpers. All network requests use the bounded HTTPS transport.
require_once __DIR__ . '/../lib/bootstrap.php';
function get_root_domain($url) { return is_string($url) ? parse_url($url, PHP_URL_HOST) : null; }
function get_url_scheme($url) { return is_string($url) ? parse_url($url, PHP_URL_SCHEME) : null; }
function request($url) {
    try {
        bt_validate_image_url($url);
        return bt_http_get($url, 8 * 1024 * 1024);
    } catch (InvalidArgumentException | RuntimeException $e) {
        return ['body' => null, 'content_type' => ''];
    }
}
