<?php
declare(strict_types=1);

/** Only bounded numeric metadata and fixed reasons may leave the transport. */
final class BtUpstreamException extends RuntimeException
{
    public readonly string $reason;
    public readonly int $upstreamStatus;
    public readonly int $curlErrno;

    public function __construct(string $reason, int $upstreamStatus = 0, int $curlErrno = 0)
    {
        if (!in_array($reason, ['dns', 'dns_blocked', 'curl', 'http_status', 'empty_body'], true)) {
            throw new InvalidArgumentException('Unsupported upstream failure reason.');
        }
        $this->reason = $reason;
        $this->upstreamStatus = $upstreamStatus >= 100 && $upstreamStatus <= 599 ? $upstreamStatus : 0;
        $this->curlErrno = $curlErrno >= 0 && $curlErrno <= 9999 ? $curlErrno : 0;
        parent::__construct('Image provider is temporarily unavailable. Please try again shortly.');
    }
}

function bt_validate_url(string $url, array $hosts, int $maxBytes = 16384): array
{
    if (strlen($url) > $maxBytes || preg_match('/[\x00-\x20\x7f\\\\]/', $url)) {
        throw new InvalidArgumentException('Invalid image URL.');
    }
    $parts = parse_url($url);
    if (!is_array($parts) || ($parts['scheme'] ?? '') !== 'https'
        || !in_array(strtolower($parts['host'] ?? ''), $hosts, true)
        || isset($parts['user']) || isset($parts['pass']) || isset($parts['fragment'])
        || (isset($parts['port']) && $parts['port'] !== 443)) {
        throw new InvalidArgumentException('Only approved HTTPS image URLs are accepted.');
    }
    return $parts;
}

function bt_validate_image_url(string $url): string
{
    if (strlen($url) > 4096) { throw new InvalidArgumentException('Invalid image URL.'); }
    bt_validate_url($url, ['i.pinimg.com']);
    return $url;
}

function bt_public_ip(string $ip): bool
{
    // Requests intentionally use IPv4 only: no IPv4-mapped IPv6, NAT64 or zone IDs.
    if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4 | FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) {
        return false;
    }
    $n = ip2long($ip);
    foreach ([['0.0.0.0', 8], ['100.64.0.0', 10], ['192.0.0.0', 24], ['192.0.2.0', 24],
              ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4]] as [$network, $bits]) {
        $mask = -1 << (32 - $bits);
        if (($n & $mask) === (ip2long($network) & $mask)) { return false; }
    }
    return true;
}

/** The callback counts decoded bytes, including unknown-length/chunked bodies. */
function bt_http_body_sink(int $limit, string &$body): Closure
{
    return static function ($handle, string $chunk) use ($limit, &$body): int {
        if (strlen($body) + strlen($chunk) > $limit) { return 0; }
        $body .= $chunk;
        return strlen($chunk);
    };
}

function bt_http_get(string $url, int $limit = 2097152): array
{
    // Opaque search cursors expand when JSON-escaped and URL-encoded. Keep the
    // larger budget specific to this exact endpoint; image bounds stay intact.
    $urlLimit = str_starts_with($url, 'https://www.pinterest.com/resource/BaseSearchResource/get/?') ? 32768 : 16384;
    $parts = bt_validate_url($url, ['www.pinterest.com', 'i.pinimg.com'], $urlLimit);
    $host = strtolower($parts['host']);
    $ips = gethostbynamel($host);
    if (!$ips) { throw new BtUpstreamException('dns'); }
    foreach ($ips as $ip) {
        if (!bt_public_ip($ip)) { throw new BtUpstreamException('dns_blocked'); }
    }
    $ch = curl_init($url);
    if ($ch === false) { throw new BtUpstreamException('curl'); }
    $body = '';
    $headers = ['Accept: ' . ($host === 'i.pinimg.com' ? 'image/avif,image/webp,image/*' : 'application/json'), 'Accept-Language: en-US,en;q=0.8'];
    if ($host === 'www.pinterest.com' && ($parts['path'] ?? '') === '/resource/BaseSearchResource/get/') {
        // Pinterest's resource API expects its web-app handler identifier.
        $headers[] = 'X-Pinterest-PWS-Handler: www/[username].js';
    }
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_WRITEFUNCTION => bt_http_body_sink($limit, $body),
        CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_MAXREDIRS => 0,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_TIMEOUT => 10,
        CURLOPT_LOW_SPEED_LIMIT => 1024,
        CURLOPT_LOW_SPEED_TIME => 5,
        CURLOPT_MAXFILESIZE => $limit,
        CURLOPT_ENCODING => '',
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_PROXY => '',
        CURLOPT_RESOLVE => [$host . ':443:' . $ips[0]],
        CURLOPT_USERAGENT => 'Mozilla/5.0 (compatible; Binternet/2026.09; +https://github.com/cristiancmoises/Binternet)',
        CURLOPT_HTTPHEADER => $headers,
    ]);
    if (defined('CURLOPT_PROTOCOLS_STR')) {
        curl_setopt($ch, CURLOPT_PROTOCOLS_STR, 'https');
    } else {
        curl_setopt($ch, CURLOPT_PROTOCOLS, CURLPROTO_HTTPS);
    }
    $ok = curl_exec($ch);
    $curlErrno = curl_errno($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $type = (string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);
    if ($ok === false) { throw new BtUpstreamException('curl', $status, $curlErrno); }
    if ($status !== 200) { throw new BtUpstreamException('http_status', $status, $curlErrno); }
    if ($body === '') { throw new BtUpstreamException('empty_body', $status, $curlErrno); }
    return ['body' => $body, 'content_type' => $type, 'status' => $status];
}

function bt_image_type(string $body): string
{
    $info = @getimagesizefromstring($body);
    $mime = is_array($info) ? ($info['mime'] ?? '') : '';
    if (!in_array($mime, ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif'], true)) {
        throw new RuntimeException('The provider did not return a supported image.');
    }
    // Pixel bound prevents rendering pathological raster dimensions in browsers.
    if ($info[0] < 1 || $info[1] < 1 || $info[0] > 30000 || $info[1] > 30000 || $info[0] * $info[1] > 150000000) {
        throw new RuntimeException('This image exceeds the supported dimensions.');
    }
    return $mime;
}
