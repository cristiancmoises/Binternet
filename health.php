<?php
declare(strict_types=1);
require_once __DIR__ . '/lib/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
try {
    if (!extension_loaded('curl') || !extension_loaded('mbstring')) { throw new RuntimeException(); }
    bt_cache_dir();
    echo json_encode(['status' => 'ok', 'version' => BT_VERSION]);
} catch (RuntimeException $e) {
    http_response_code(503);
    echo '{"status":"unavailable"}';
}
