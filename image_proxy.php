<?php
declare(strict_types=1);
require_once __DIR__ . '/lib/bootstrap.php';
header("Content-Security-Policy: default-src 'none'; frame-ancestors 'none'");
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header('Cross-Origin-Resource-Policy: same-origin');
try {
    if (!in_array($_SERVER['REQUEST_METHOD'] ?? 'GET', ['GET', 'HEAD'], true)) {
        header('Allow: GET, HEAD');
        http_response_code(405);
        exit;
    }
    $url = bt_validate_image_url(bt_param('url', '', 4096));
    $entry = bt_cached_fetch('image', $url, 86400, 604800, static function () use ($url): string {
        $response = bt_http_get($url, 8 * 1024 * 1024);
        bt_image_type($response['body']);
        return $response['body'];
    });
    $body = $entry['body'];
    $mime = bt_image_type($body);
    $etag = '"' . hash('sha256', $body) . '"';
    header('Content-Type: ' . $mime);
    header('Cache-Control: public, max-age=86400, stale-if-error=604800');
    header('ETag: ' . $etag);
    header('X-Binternet-Cache: ' . ($entry['stale'] ? 'STALE' : ($entry['cached'] ? 'HIT' : 'MISS')));
    if (trim($_SERVER['HTTP_IF_NONE_MATCH'] ?? '') === $etag) {
        http_response_code(304);
        exit;
    }
    header('Content-Length: ' . strlen($body));
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'HEAD') { echo $body; }
} catch (InvalidArgumentException $e) {
    http_response_code(400);
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    echo 'Invalid image URL.';
} catch (RuntimeException $e) {
    http_response_code(502);
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    echo 'Image unavailable. Please try again later.';
}
