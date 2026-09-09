<?php
declare(strict_types=1);

/** Offline regression checks. Upstream HTTP is never required. */
// Cached production searches below also exercise response headers.
ob_start();
$root = dirname(__DIR__);
$testDir = sys_get_temp_dir() . '/binternet-security-' . bin2hex(random_bytes(8));
mkdir($testDir, 0700, true);
putenv('BINTERNET_CACHE_DIR=' . $testDir . '/cache');
require $root . '/lib/bootstrap.php';

// Execute the production transport unchanged in an isolated namespace. Only
// DNS and cURL I/O are replaced, so the real option-building/error paths run
// without contacting Pinterest or adding test switches to application code.
$transportCode = file_get_contents($root . '/lib/http.php');
$transportCode = preg_replace('/^<\?php\s*declare\(strict_types=1\);/',
    'namespace BinternetTransportFixture; use \\RuntimeException; use \\InvalidArgumentException; use \\Closure;', $transportCode, 1, $replacements);
if ($replacements !== 1) { throw new RuntimeException('Cannot load transport fixture'); }
eval($transportCode);
eval(<<<'PHP'
namespace BinternetTransportFixture;
function gethostbynamel(string $host): array|false {
    $GLOBALS['bt_transport_fixture']['dns_calls']++;
    return $GLOBALS['bt_transport_fixture']['ips'];
}
function curl_init(string $url): object|false {
    $GLOBALS['bt_transport_fixture']['init_calls']++;
    $GLOBALS['bt_transport_fixture']['url'] = $url;
    return $GLOBALS['bt_transport_fixture']['init_ok'] ? new \stdClass() : false;
}
function curl_setopt_array(object $handle, array $options): bool {
    $GLOBALS['bt_transport_fixture']['options'] = $options;
    return true;
}
function curl_setopt(object $handle, int $option, mixed $value): bool {
    $GLOBALS['bt_transport_fixture']['options'][$option] = $value;
    return true;
}
function curl_exec(object $handle): bool {
    $fixture = &$GLOBALS['bt_transport_fixture'];
    foreach ($fixture['chunks'] as $chunk) {
        if (($fixture['options'][CURLOPT_WRITEFUNCTION])($handle, $chunk) !== strlen($chunk)) {
            $fixture['errno'] = 23; // CURLE_WRITE_ERROR, as returned for an aborted sink.
            return false;
        }
    }
    return $fixture['ok'];
}
function curl_errno(object $handle): int { return $GLOBALS['bt_transport_fixture']['errno']; }
function curl_getinfo(object $handle, int $option): int|string {
    return $option === CURLINFO_RESPONSE_CODE ? $GLOBALS['bt_transport_fixture']['status'] : 'application/json';
}
function curl_close(object $handle): void { $GLOBALS['bt_transport_fixture']['close_calls']++; }
PHP);

// Exercise the real search request serializer through that same I/O fixture.
$searchCode = file_get_contents($root . '/lib/search.php');
$searchCode = preg_replace('/^<\?php\s*declare\(strict_types=1\);/',
    'namespace BinternetTransportFixture; use \\RuntimeException; use \\InvalidArgumentException; use \\JsonException; use \\stdClass;',
    $searchCode, 1, $replacements);
if ($replacements !== 1) { throw new RuntimeException('Cannot load search transport fixture'); }
eval($searchCode);

function transportFixture(array $overrides = []): void
{
    $GLOBALS['bt_transport_fixture'] = $overrides + [
        'ips' => ['1.1.1.1'], 'dns_calls' => 0, 'init_ok' => true, 'init_calls' => 0,
        'ok' => true, 'status' => 200, 'errno' => 0, 'chunks' => ['{"ok":true}'],
        'options' => [], 'close_calls' => 0,
    ];
}

$passed = 0;
$failed = 0;
function check(bool $condition, string $message = 'Expectation failed'): void
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
function rejects(callable $callback, string $exception = InvalidArgumentException::class): void
{
    try { $callback(); }
    catch (Throwable $error) {
        check($error instanceof $exception, 'Unexpected exception: ' . get_class($error));
        return;
    }
    throw new RuntimeException('Expected rejection');
}
function test(string $name, callable $callback): void
{
    global $passed, $failed;
    try {
        $callback();
        $passed++;
        echo "PASS $name\n";
    } catch (Throwable $error) {
        $failed++;
        fwrite(STDERR, "FAIL $name: " . $error->getMessage() . "\n");
    }
}
function cleanDirectory(string $directory): void
{
    foreach (scandir($directory) ?: [] as $entry) {
        if ($entry === '.' || $entry === '..') { continue; }
        $path = $directory . '/' . $entry;
        if (is_dir($path) && !is_link($path)) { cleanDirectory($path); }
        else { unlink($path); }
    }
    rmdir($directory);
}
register_shutdown_function(static function () use ($testDir): void {
    if (is_dir($testDir)) { cleanDirectory($testDir); }
});

test('Parameters preserve query characters before output escaping', static function (): void {
    $_GET = ['q' => '  art & design "日本"  '];
    check(bt_param('q') === 'art & design "日本"');
    check(bt_param('missing', 'fallback') === 'fallback');
    check(bt_escape('<a href="x">&') === '&lt;a href=&quot;x&quot;&gt;&amp;');
});

test('Malformed, oversized and control-character parameters are rejected', static function (): void {
    foreach ([['nested'], str_repeat('a', 161), "a\0b", "a\r\nb", "a\x7fb", "\xff"] as $invalid) {
        $_GET = ['q' => $invalid];
        rejects(static fn() => bt_param('q'));
    }
    $_GET = ['q' => str_repeat('a', 160)];
    check(strlen(bt_param('q')) === 160);
});

test('Preference values are allow-listed and arrays fall back safely', static function (): void {
    $_GET = ['theme' => ['black'], 'view' => '"><script>', 'quality' => 'unsafe', 'scroll' => ['infinite']];
    check(bt_preferences() === ['theme' => 'black', 'view' => 'masonry', 'quality' => 'auto', 'scroll' => 'manual']);
    $_GET = ['theme' => 'paper', 'view' => 'focus', 'quality' => 'original', 'scroll' => 'infinite'];
    check(bt_preferences() === $_GET);
    $_GET = ['scroll' => '"><script>alert(1)</script>'];
    check(bt_preferences()['scroll'] === 'manual');
});

test('Proxy links encode complete upstream URLs as a single parameter', static function (): void {
    $upstream = 'https://i.pinimg.com/originals/aa/bb/photo.jpg?x=1&y="quoted"';
    $link = bt_image_url($upstream);
    check(str_starts_with($link, '/image_proxy.php?'));
    parse_str((string) parse_url($link, PHP_URL_QUERY), $params);
    check($params === ['url' => $upstream]);
    check(!str_contains($link, '"'));
});

test('Image URL allow-list rejects SSRF and parser-confusion candidates', static function (): void {
    $bad = [
        '', 'file:///etc/passwd', 'gopher://127.0.0.1/', '//i.pinimg.com/a.jpg',
        'http://i.pinimg.com/a.jpg', 'https://example.com/a.jpg',
        'https://i.pinimg.com.evil.example/a.jpg', 'https://evil-i.pinimg.com/a.jpg',
        'https://i.pinimg.com@127.0.0.1/a.jpg', 'https://name:secret@i.pinimg.com/a.jpg',
        'https://i.pinimg.com:8443/a.jpg', 'https://i.pinimg.com/a.jpg#fragment',
        "https://i.pinimg.com/a.jpg\r\nHost: 127.0.0.1", 'https://i.pinimg.com\\@127.0.0.1/a.jpg',
        'https://127.0.0.1/a.jpg', 'https://2130706433/a.jpg', 'https://[::1]/a.jpg',
        'https://www.pinterest.com/', 'https://i.pinimg.com./a.jpg',
        'https://i.pinimg.com/' . str_repeat('a', 4096),
    ];
    foreach ($bad as $url) { rejects(static fn() => bt_validate_image_url($url)); }
    foreach (['https://i.pinimg.com/originals/ab/cd/image.jpg', 'https://i.pinimg.com:443/a.webp', 'https://I.PINIMG.COM/a.png'] as $url) {
        check(bt_validate_image_url($url) === $url);
    }
});

test('DNS filtering rejects internal, metadata, mapped and reserved addresses', static function (): void {
    $bad = ['127.0.0.1', '10.2.3.4', '172.16.0.1', '192.168.1.1', '169.254.169.254',
        '0.0.0.0', '100.64.0.1', '192.0.0.1', '192.0.2.1', '198.18.0.1',
        '198.51.100.1', '203.0.113.1', '224.0.0.1', '240.0.0.1', '255.255.255.255',
        '::1', '::ffff:127.0.0.1', '64:ff9b::a00:1', 'localhost', '2130706433'];
    foreach ($bad as $ip) { check(!bt_public_ip($ip), 'Address was not blocked: ' . $ip); }
    check(bt_public_ip('1.1.1.1'));
    check(bt_public_ip('8.8.8.8'));
});

test('Unknown-length response callback aborts before crossing byte cap', static function (): void {
    $body = '';
    $sink = bt_http_body_sink(10, $body);
    check($sink(null, '1234') === 4);
    check($sink(null, '567890') === 6);
    check($body === '1234567890');
    check($sink(null, 'overflow') === 0);
    check($body === '1234567890', 'Oversized chunk was buffered');
    $body = '';
    $sink = bt_http_body_sink(3, $body);
    check($sink(null, str_repeat('x', 1024 * 1024)) === 0 && $body === '');
});

test('Resource request sends the Pinterest handler only to the exact search endpoint', static function (): void {
    $handler = 'X-Pinterest-PWS-Handler: www/[username].js';
    foreach ([
        ['https://www.pinterest.com/resource/BaseSearchResource/get/?data=fixture', true],
        ['https://WWW.PINTEREST.COM/resource/BaseSearchResource/get/', true],
        ['https://www.pinterest.com/', false],
        ['https://www.pinterest.com/resource/BaseSearchResource/get/extra', false],
        ['https://i.pinimg.com/resource/BaseSearchResource/get/', false],
        ['https://i.pinimg.com/originals/fixture.jpg', false],
    ] as [$url, $expectsHandler]) {
        transportFixture();
        $response = BinternetTransportFixture\bt_http_get($url);
        check($response['status'] === 200 && $response['body'] === '{"ok":true}');
        $options = $GLOBALS['bt_transport_fixture']['options'];
        $headers = $options[CURLOPT_HTTPHEADER];
        check(in_array($handler, $headers, true) === $expectsHandler, $url);
        check(in_array('Accept-Language: en-US,en;q=0.8', $headers, true));
        check(in_array(str_contains($url, 'i.pinimg.com') ? 'Accept: image/avif,image/webp,image/*' : 'Accept: application/json', $headers, true));
        check(count($headers) === ($expectsHandler ? 3 : 2));
        check($options[CURLOPT_SSL_VERIFYPEER] === true && $options[CURLOPT_SSL_VERIFYHOST] === 2);
        check($options[CURLOPT_FOLLOWLOCATION] === false && $options[CURLOPT_MAXREDIRS] === 0);
        check($options[CURLOPT_PROXY] === '' && count($options[CURLOPT_RESOLVE]) === 1);
        check(str_ends_with($options[CURLOPT_RESOLVE][0], ':443:1.1.1.1'));
        check($GLOBALS['bt_transport_fixture']['close_calls'] === 1);
    }
});

test('Transport failures retain safe DNS, cURL and upstream HTTP metadata', static function (): void {
    foreach ([
        [['ips' => false], 'dns', 0, 0],
        [['ips' => ['1.1.1.1', '127.0.0.1']], 'dns_blocked', 0, 0],
        [['init_ok' => false], 'curl', 0, 0],
        [['ok' => false, 'status' => 0, 'errno' => 60], 'curl', 0, 60],
        [['status' => 403], 'http_status', 403, 0],
        [['status' => 429], 'http_status', 429, 0],
        [['status' => 302], 'http_status', 302, 0],
        [['chunks' => []], 'empty_body', 200, 0],
    ] as [$fixture, $reason, $status, $errno]) {
        transportFixture($fixture + ['chunks' => ['private-upstream-response-body']]);
        try {
            BinternetTransportFixture\bt_http_get('https://www.pinterest.com/resource/BaseSearchResource/get/?data=private-query');
            throw new RuntimeException('Expected upstream failure');
        } catch (BinternetTransportFixture\BtUpstreamException $error) {
            check($error instanceof RuntimeException);
            check($error->reason === $reason && $error->upstreamStatus === $status && $error->curlErrno === $errno);
            check(!str_contains($error->getMessage(), 'private-'));
            check(!str_contains($error->getMessage(), 'https://'));
            if (str_starts_with($reason, 'dns')) { check($GLOBALS['bt_transport_fixture']['init_calls'] === 0); }
            if (($fixture['init_ok'] ?? true) && !str_starts_with($reason, 'dns')) {
                check($GLOBALS['bt_transport_fixture']['close_calls'] === 1);
            }
        }
    }
    $bounded = new BtUpstreamException('curl', 999999, -1);
    check($bounded->upstreamStatus === 0 && $bounded->curlErrno === 0);
    rejects(static fn() => new BtUpstreamException("http_status\r\nInjected: value"));
});

test('Transport byte-cap failure exposes cURL metadata without returning partial content', static function (): void {
    transportFixture(['chunks' => ['1234', '5678', 'oversized-private-body']]);
    try {
        BinternetTransportFixture\bt_http_get('https://www.pinterest.com/resource/BaseSearchResource/get/', 8);
        throw new RuntimeException('Oversized transport body was accepted');
    } catch (BinternetTransportFixture\BtUpstreamException $error) {
        check($error->reason === 'curl' && $error->curlErrno === 23 && $error->upstreamStatus === 200);
        check(!str_contains($error->getMessage(), 'private-body'));
        check($GLOBALS['bt_transport_fixture']['close_calls'] === 1);
    }
});

test('Image validation rejects active markup and forged content types', static function (): void {
    foreach (['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<html><img src=x onerror=alert(1)></html>', '{"image":"not an image"}', '', 'GIF89a'] as $body) {
        rejects(static fn() => bt_image_type($body), RuntimeException::class);
    }
    $gif = base64_decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', true);
    check(bt_image_type($gif) === 'image/gif');
    $huge = substr_replace($gif, pack('vv', 30001, 30001), 6, 4);
    rejects(static fn() => bt_image_type($huge), RuntimeException::class);
});

function searchFixture(): array
{
    $image = static fn(string $url, int $width, int $height): array => compact('url', 'width', 'height');
    $pin = [
        'id' => '123456789', 'title' => '<script>alert(1)</script> Art & "design"',
        'images' => [
            'orig' => $image('https://i.pinimg.com/originals/fixture.jpg', 1800, 1200),
            '236x' => $image('https://i.pinimg.com/236x/fixture.jpg', 236, 157),
            '736x' => $image('https://i.pinimg.com/736x/fixture.jpg', 736, 490),
            'evil' => $image('https://127.0.0.1/private.jpg', 9999, 9999),
        ],
    ];
    return ['resource_response' => ['status' => 'success', 'data' => ['results' => [
        $pin, $pin, null, ['images' => 'bad'],
        ['images' => ['orig' => $image('https://i.pinimg.com/oversized.jpg', 30001, 30001)]],
        ['images' => ['orig' => ['url' => 'https://i.pinimg.com/missing-dimensions.jpg']]],
    ]], 'bookmark' => 'opaque/next+page==']];
}

test('Search parser chooses real original and removes duplicate and invalid pins', static function (): void {
    $parsed = bt_parse_results(searchFixture());
    check(count($parsed['results']) === 1);
    $pin = $parsed['results'][0];
    check($pin['url'] === 'https://i.pinimg.com/originals/fixture.jpg');
    check(array_column($pin['variants'], 'width') === [236, 736, 1800]);
    check(!str_contains($pin['title'], '<'));
    check($parsed['bookmark'] === 'opaque/next+page==');
});

test('Search parser handles provider failures, empty results and end bookmarks', static function (): void {
    foreach ([[], ['resource_response' => ['status' => 'failure']], ['resource_response' => ['data' => 'invalid']],
        ['resource_response' => ['data' => ['results' => ['associative' => []]]]]] as $bad) {
        rejects(static fn() => bt_parse_results($bad), RuntimeException::class);
    }
    check(bt_parse_results(['resource_response' => ['data' => []]])['results'] === []);
    foreach (['-end-', '-end', 'Y2JOb25lOencoded-end', '', ['array'], str_repeat('a', 4097), "line\r\nbreak", "\xff"] as $bookmark) {
        $fixture = searchFixture();
        $fixture['resource_response']['bookmark'] = $bookmark;
        check(bt_parse_results($fixture)['bookmark'] === null);
    }
});

test('Canonical Pinterest response advances to the second page and stops at the end', static function (): void {
    // Keep the real nesting in raw JSON: the cursor is a sibling of
    // resource_response, not part of its image list or legacy bookmark field.
    $first = json_decode(<<<'JSON'
{"resource_response":{"status":"success","data":{"results":[{"id":"101","title":"First page","images":{"orig":{"url":"https://i.pinimg.com/originals/first.jpg","width":1200,"height":800}}}]}},"resource":{"name":"BaseSearchResource","options":{"query":"architecture","bookmarks":["opaque/page+two=="]}}}
JSON, true, 64, JSON_THROW_ON_ERROR);
    $second = json_decode(<<<'JSON'
{"resource_response":{"status":"success","data":[{"id":"102","title":"Second page","images":{"orig":{"url":"https://i.pinimg.com/originals/second.jpg","width":1200,"height":800}}}]},"resource":{"name":"BaseSearchResource","options":{"query":"architecture","bookmarks":["-end-"]}}}
JSON, true, 64, JSON_THROW_ON_ERROR);
    $pageOne = bt_parse_results($first);
    $pageTwo = bt_parse_results($second);
    check($pageOne['results'][0]['id'] === '101' && $pageOne['bookmark'] === 'opaque/page+two==');
    check($pageTwo['results'][0]['id'] === '102' && $pageTwo['bookmark'] === null);
    bt_cache_put('search', bt_search_cache_key('pagination fixture'), json_encode($pageOne, JSON_THROW_ON_ERROR));
    bt_cache_put('search', bt_search_cache_key('pagination fixture', $pageOne['bookmark']), json_encode($pageTwo, JSON_THROW_ON_ERROR));
    $servedOne = bt_search('pagination fixture');
    $servedTwo = bt_search('pagination fixture', $servedOne['bookmark']);
    check($servedOne['cached'] && $servedTwo['cached']);
    check($servedTwo['results'][0]['id'] === '102' && $servedTwo['bookmark'] === null);
});

test('Canonical bookmark metadata takes precedence and never resurrects an ended cursor', static function (): void {
    $fixture = searchFixture();
    $fixture['resource']['options']['bookmarks'] = ['canonical-next', 'ignored-next'];
    check(bt_parse_results($fixture)['bookmark'] === 'canonical-next');
    foreach ([[], null, '', 'scalar-next', ['-end-'], ['-end'], ['Y2JOb25lOencoded-end'],
        [null], [['nested-cursor']], ['next' => 'associative'], [1 => 'sparse'], [''],
        [' leading'], ['trailing '], ['two words'], ["no\u{00a0}space"], ["line\nfeed"],
        ["\xff"], [str_repeat('x', 4097)]] as $bookmarks) {
        $fixture['resource']['options']['bookmarks'] = $bookmarks;
        check(bt_parse_results($fixture)['bookmark'] === null, 'Invalid canonical metadata fell back to a legacy cursor');
    }
    foreach ([null, 'malformed', ['options' => null], ['options' => 'malformed']] as $resource) {
        $fixture['resource'] = $resource;
        check(bt_parse_results($fixture)['bookmark'] === null);
    }
    $fixture['resource'] = ['options' => ['bookmarks' => [str_repeat('x', 4096)]]];
    check(strlen(bt_parse_results($fixture)['bookmark']) === 4096);
});

test('Long Pinterest cursors survive parsing and cached pagination within a byte limit', static function (): void {
    check(BT_BOOKMARK_MAX_BYTES === 4096);
    foreach ([str_repeat('a', 2064), str_repeat('b', 4096), str_repeat('é', 2048)] as $cursor) {
        $fixture = searchFixture();
        $fixture['resource']['options']['bookmarks'] = [$cursor];
        check(bt_parse_results($fixture)['bookmark'] === $cursor);
        unset($fixture['resource']);
        $fixture['resource_response']['bookmark'] = $cursor;
        check(bt_parse_results($fixture)['bookmark'] === $cursor, 'Legacy long cursor was lost');
        $_GET = ['bookmark' => $cursor];
        check(bt_param('bookmark', '', BT_BOOKMARK_MAX_BYTES) === $cursor);
        $nextPage = bt_parse_results(searchFixture());
        bt_cache_put('search', bt_search_cache_key('long cursor fixture', $cursor), json_encode($nextPage, JSON_THROW_ON_ERROR));
        check(count(bt_search('long cursor fixture', $cursor)['results']) === 1);
    }
    foreach ([str_repeat('c', 4097), str_repeat('é', 2048) . 'x'] as $cursor) {
        check(bt_search_bookmark_token($cursor) === null, 'Cursor limit counted characters instead of bytes');
        $_GET = ['bookmark' => $cursor];
        rejects(static fn() => bt_param('bookmark', '', BT_BOOKMARK_MAX_BYTES));
        rejects(static fn() => bt_search('long cursor fixture', $cursor));
    }
});

test('Long opaque cursors round trip through the real bounded search request', static function (): void {
    $query = str_repeat('/', 160);
    foreach ([str_repeat('/', 4096), str_repeat('é', 2048), str_repeat('"', 4096), str_repeat('\\', 4096)] as $cursor) {
        transportFixture(['chunks' => [json_encode(searchFixture(), JSON_THROW_ON_ERROR)]]);
        $result = \BinternetTransportFixture\bt_search($query, $cursor);
        check(count($result['results']) === 1);
        check($GLOBALS['bt_transport_fixture']['init_calls'] === 1);
        $url = $GLOBALS['bt_transport_fixture']['url'];
        check(strlen($url) <= 32768, 'Valid cursor exceeded the outbound URL budget');
        parse_str((string) parse_url($url, PHP_URL_QUERY), $params);
        $payload = json_decode($params['data'], true, 64, JSON_THROW_ON_ERROR);
        check($payload['options']['query'] === $query);
        check($payload['options']['bookmarks'] === [$cursor], 'Request serializer altered the cursor');
        check($payload['options']['scope'] === 'pins' && $payload['options']['page_size'] === 25);
    }
});

test('The larger outbound URL budget is restricted to the exact search endpoint', static function (): void {
    $search = 'https://www.pinterest.com/resource/BaseSearchResource/get/?data=';
    transportFixture();
    \BinternetTransportFixture\bt_http_get($search . str_repeat('a', 32768 - strlen($search)));
    check($GLOBALS['bt_transport_fixture']['init_calls'] === 1);
    foreach ([$search . str_repeat('a', 32769 - strlen($search)),
        'https://www.pinterest.com/resource/OtherResource/get/?data=' . str_repeat('a', 16384),
        'https://i.pinimg.com/originals/' . str_repeat('a', 16384)] as $url) {
        transportFixture();
        rejects(static fn() => \BinternetTransportFixture\bt_http_get($url));
        check($GLOBALS['bt_transport_fixture']['dns_calls'] === 0 && $GLOBALS['bt_transport_fixture']['init_calls'] === 0,
            'Oversized URL reached DNS/cURL');
    }
    rejects(static fn() => bt_validate_url($search . str_repeat('a', 16384), ['www.pinterest.com']));
    rejects(static fn() => bt_validate_image_url('https://i.pinimg.com/' . str_repeat('a', 4096)));
});

test('Legacy response cursors remain supported only when canonical cursors are absent', static function (): void {
    $fixture = searchFixture();
    foreach ([[], ['options' => []], ['options' => ['query' => 'architecture']]] as $resource) {
        $fixture['resource'] = $resource;
        check(bt_parse_results($fixture)['bookmark'] === 'opaque/next+page==');
    }
    unset($fixture['resource_response']['bookmark']);
    $fixture['resource_response']['data']['bookmark'] = 'legacy-data-next';
    check(bt_parse_results($fixture)['bookmark'] === 'legacy-data-next');
    unset($fixture['resource_response']['data']['bookmark']);
    $fixture['resource_response']['data']['bookmarks'] = ['legacy-data-list-next'];
    check(bt_parse_results($fixture)['bookmark'] === 'legacy-data-list-next');
    $fixture['resource_response']['bookmarks'] = ['legacy-response-list-next'];
    check(bt_parse_results($fixture)['bookmark'] === 'legacy-response-list-next');
    $fixture['resource_response']['bookmark'] = '-end-';
    check(bt_parse_results($fixture)['bookmark'] === null);
    $fixture['resource_response']['bookmark'] = ['nested' => 'must-not-follow'];
    check(bt_parse_results($fixture)['bookmark'] === null);
    unset($fixture['resource_response']['bookmark'], $fixture['resource_response']['bookmarks'], $fixture['resource_response']['data']['bookmarks']);
    check(bt_parse_results($fixture)['bookmark'] === null);
});

test('Cached search refuses a repeated cursor and ignores the previous parsed cache version', static function (): void {
    $query = 'repeated cursor fixture';
    $cursor = 'same-next-cursor';
    $fixture = searchFixture();
    $fixture['resource']['options']['bookmarks'] = [$cursor];
    $parsed = bt_parse_results($fixture);
    bt_cache_put('search', bt_search_cache_key($query, $cursor), json_encode($parsed, JSON_THROW_ON_ERROR));
    $served = bt_search($query, $cursor);
    check($served['cached'] && $served['bookmark'] === null);
    check(count($served['results']) === 1, 'Loop protection removed valid images');
    foreach (['v1:', 'v2:'] as $version) {
        $oldKey = $version . json_encode([$query, $cursor], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        check(bt_search_cache_key($query, $cursor) !== $oldKey);
        bt_cache_put('search', $oldKey, '{"results":[],"bookmark":null}');
    }
    check(count(bt_search($query, $cursor)['results']) === 1);
});

test('Invalid search and bookmark parameters fail before transport', static function (): void {
    foreach ([['', ''], ['   ', ''], [str_repeat('a', 161), ''], ['q', str_repeat('b', 4097)], ['q', "bad\nbookmark"],
        ['q', 'two words'], ['q', '-end-'], ['q', 'Y2JOb25lOencoded-end']] as [$query, $bookmark]) {
        rejects(static fn() => bt_search($query, $bookmark));
    }
    check(bt_search_cache_key('a:b', 'c') !== bt_search_cache_key('a', 'b:c'));
});

test('Cache keys cannot escape the private cache directory', static function (): void {
    $path = bt_cache_path('search', '../../outside');
    check(dirname($path) === bt_cache_dir());
    check((bool) preg_match('/^search-[a-f0-9]{64}\.cache$/', basename($path)));
    rejects(static fn() => bt_cache_path('../outside', 'key'));
});

test('Cache writes, expiration and oversized entry rejection', static function (): void {
    bt_cache_put('search', 'roundtrip', '{"test":true}');
    check(bt_cache_get('search', 'roundtrip', 60)['body'] === '{"test":true}');
    touch(bt_cache_path('search', 'roundtrip'), time() - 120);
    clearstatcache();
    check(bt_cache_get('search', 'roundtrip', 60) === null);
    bt_cache_put('image', 'too-big', str_repeat('x', 8 * 1024 * 1024 + 1));
    check(bt_cache_get('image', 'too-big', 60) === null);
    file_put_contents(bt_cache_path('search', 'external-big'), str_repeat('x', 8 * 1024 * 1024 + 1));
    check(bt_cache_get('search', 'external-big', 60) === null);
    unlink(bt_cache_path('search', 'external-big'));
});

test('Cache reads reject symbolic links', static function () use ($testDir): void {
    $outside = $testDir . '/private.txt';
    file_put_contents($outside, 'must not disclose');
    $link = bt_cache_path('search', 'symlink');
    symlink($outside, $link);
    check(bt_cache_get('search', 'symlink', 60) === null);
    unlink($link);
});

test('Fresh cache avoids network work and stale cache survives failure', static function (): void {
    $calls = 0;
    $fetch = static function () use (&$calls): string { $calls++; return 'fresh'; };
    $first = bt_cached_fetch('search', 'single-flight', 60, 300, $fetch);
    $second = bt_cached_fetch('search', 'single-flight', 60, 300, $fetch);
    check($calls === 1 && !$first['cached'] && $second['cached']);
    touch(bt_cache_path('search', 'single-flight'), time() - 120);
    clearstatcache();
    $stale = bt_cached_fetch('search', 'single-flight', 60, 300, static function (): string {
        throw new RuntimeException('simulated upstream failure');
    });
    check($stale['stale'] && $stale['body'] === 'fresh');
    rejects(static fn() => bt_cached_fetch('search', 'uncached-failure', 60, 300, static function (): string {
        throw new RuntimeException('simulated upstream failure');
    }), RuntimeException::class);
});

test('Cache entry count is bounded under many unique searches', static function (): void {
    for ($i = 0; $i < 530; $i++) {
        bt_cache_put('search', 'entry-limit-' . $i, 'small fixture');
    }
    check(count(glob(bt_cache_dir() . '/*.cache') ?: []) <= 512);
    check(bt_cache_get('search', 'entry-limit-529', 60)['body'] === 'small fixture');
});

test('Cache total bytes stay within 64 MiB during image churn', static function (): void {
    $body = str_repeat('x', 8 * 1024 * 1024);
    for ($i = 0; $i < 10; $i++) { bt_cache_put('image', 'byte-limit-' . $i, $body); }
    $total = 0;
    foreach (glob(bt_cache_dir() . '/*.cache') ?: [] as $path) { $total += filesize($path); }
    check($total <= 64 * 1024 * 1024, 'Cache exceeded total-byte cap');
});

echo "\n$passed passed; $failed failed. Offline unit/fixture tests only.\n";
exit($failed ? 1 : 0);
