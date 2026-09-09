<?php
// SPDX-License-Identifier: AGPL-3.0-or-later
declare(strict_types=1);

const BT_VERSION = '2026.09.08.5';
require_once __DIR__ . '/cache.php';
require_once __DIR__ . '/http.php';
require_once __DIR__ . '/search.php';

function bt_escape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function bt_param(string $name, string $default = '', int $max = 160): string
{
    $value = $_GET[$name] ?? $default;
    if (!is_string($value) || strlen($value) > $max || preg_match('/[\x00-\x1f\x7f]/', $value) || !preg_match('//u', $value)) {
        throw new InvalidArgumentException('Invalid ' . $name . ' parameter.');
    }
    return trim($value);
}

function bt_preferences(): array
{
    $choices = [
        'theme' => ['black', 'charcoal', 'midnight', 'paper', 'forest'],
        'view' => ['masonry', 'grid', 'compact', 'justified', 'focus'],
        'quality' => ['auto', 'high', 'original', 'saver'],
        'scroll' => ['manual', 'infinite'],
    ];
    $prefs = [];
    foreach ($choices as $key => $values) {
        $value = $_GET[$key] ?? $values[0];
        $prefs[$key] = is_string($value) && in_array($value, $values, true) ? $value : $values[0];
    }
    return $prefs;
}

function bt_image_url(string $url): string
{
    return '/image_proxy.php?' . http_build_query(['url' => $url], '', '&', PHP_QUERY_RFC3986);
}

function bt_security_headers(): void
{
    header("Content-Security-Policy: default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Referrer-Policy: no-referrer');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    header('Cache-Control: no-store');
}
