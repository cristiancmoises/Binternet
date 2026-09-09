<?php
declare(strict_types=1);

function bt_search_bookmark_token(mixed $value): ?string
{
    if (!is_string($value) || $value === '' || strlen($value) > 2048
        || !preg_match('//u', $value) || preg_match('/[\s\p{Cc}\p{Z}]/u', $value)
        || in_array($value, ['-end-', '-end'], true) || str_starts_with($value, 'Y2JOb25lO')) {
        return null;
    }
    return $value;
}

function bt_search_response_bookmark(array $payload, array $response): ?string
{
    // Current responses place the next cursor outside resource_response. An
    // explicit end/empty/malformed cursor here must not revive a legacy one.
    if (array_key_exists('resource', $payload)) {
        $resource = $payload['resource'];
        if (!is_array($resource)) { return null; }
        if (array_key_exists('options', $resource)) {
            $options = $resource['options'];
            if (!is_array($options)) { return null; }
            if (array_key_exists('bookmarks', $options)) {
                $bookmarks = $options['bookmarks'];
                return is_array($bookmarks) && array_is_list($bookmarks)
                    ? bt_search_bookmark_token($bookmarks[0] ?? null) : null;
            }
        }
    }
    // Retain previously supported response shapes, accepting only a scalar
    // singular cursor or the first item of an explicitly named cursor list.
    foreach ([$response, is_array($response['data'] ?? null) ? $response['data'] : []] as $metadata) {
        if (array_key_exists('bookmark', $metadata)) {
            return bt_search_bookmark_token($metadata['bookmark']);
        }
        if (array_key_exists('bookmarks', $metadata)) {
            $bookmarks = $metadata['bookmarks'];
            return is_array($bookmarks) && array_is_list($bookmarks)
                ? bt_search_bookmark_token($bookmarks[0] ?? null) : null;
        }
    }
    return null;
}

function bt_parse_results(array $payload): array
{
    $response = $payload['resource_response'] ?? null;
    if (!is_array($response) || (isset($response['status']) && $response['status'] !== 'success')) {
        throw new RuntimeException('Image provider returned an unexpected response.');
    }
    $data = $response['data'] ?? null;
    $rows = is_array($data) ? ($data['results'] ?? (array_is_list($data) ? $data : null)) : null;
    if (!is_array($rows) || !array_is_list($rows)) {
        throw new RuntimeException('Image provider returned an unexpected response.');
    }
    $results = [];
    $seen = [];
    foreach (array_slice($rows, 0, 100) as $row) {
        if (!is_array($row) || !is_array($row['images'] ?? null)) { continue; }
        $variants = [];
        foreach ($row['images'] as $candidate) {
            if (!is_array($candidate) || !is_string($candidate['url'] ?? null)) { continue; }
            try { $url = bt_validate_image_url($candidate['url']); } catch (InvalidArgumentException $e) { continue; }
            $w = filter_var($candidate['width'] ?? null, FILTER_VALIDATE_INT);
            $h = filter_var($candidate['height'] ?? null, FILTER_VALIDATE_INT);
            if (!$w || !$h || $w < 1 || $h < 1 || $w > 30000 || $h > 30000 || $w * $h > 150000000) { continue; }
            $variants[$w] = ['url' => $url, 'width' => $w, 'height' => $h];
        }
        if (!$variants) { continue; }
        ksort($variants, SORT_NUMERIC);
        $variants = array_values($variants);
        $largest = $variants[count($variants) - 1];
        $orig = $row['images']['orig'] ?? null;
        if (is_array($orig) && is_string($orig['url'] ?? null)) {
            foreach ($variants as $variant) {
                if ($variant['url'] === $orig['url']) { $largest = $variant; break; }
            }
        }
        if (isset($seen[$largest['url']])) { continue; }
        $seen[$largest['url']] = true;
        $title = $row['title'] ?? $row['grid_title'] ?? $row['description'] ?? 'Pinterest image';
        if (!is_string($title) || trim($title) === '') { $title = 'Pinterest image'; }
        $title = mb_substr(strip_tags($title), 0, 240, 'UTF-8');
        $id = $row['id'] ?? '';
        $results[] = $largest + ['id' => is_scalar($id) ? (string) $id : '', 'title' => $title, 'variants' => $variants];
    }
    return ['results' => $results, 'bookmark' => bt_search_response_bookmark($payload, $response)];
}

function bt_search_cache_key(string $query, string $bookmark = ''): string
{
    // Invalidate old parsed entries whose canonical next cursor was discarded.
    return 'v2:' . json_encode([$query, $bookmark], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
}

function bt_search(string $query, ?string $bookmark = null): array
{
    $bookmark = $bookmark ?? '';
    foreach ([[$query, 160], [$bookmark, 2048]] as [$value, $max]) {
        if (strlen($value) > $max || preg_match('/[\x00-\x1f\x7f]/', $value) || !preg_match('//u', $value)) {
            throw new InvalidArgumentException('Invalid search parameter.');
        }
    }
    if (trim($query) === '') { throw new InvalidArgumentException('Enter a search term.'); }
    if ($bookmark !== '' && bt_search_bookmark_token($bookmark) === null) {
        throw new InvalidArgumentException('Invalid search parameter.');
    }
    $start = microtime(true);
    $entry = bt_cached_fetch('search', bt_search_cache_key($query, $bookmark), 120, 600, static function () use ($query, $bookmark): string {
        $options = ['query' => $query, 'scope' => 'pins', 'page_size' => 25, 'rs' => 'typed'];
        if ($bookmark !== '') { $options['bookmarks'] = [$bookmark]; }
        $params = ['source_url' => '/search/pins/?' . http_build_query(['q' => $query]),
            'data' => json_encode(['options' => $options, 'context' => new stdClass()], JSON_THROW_ON_ERROR)];
        $response = bt_http_get('https://www.pinterest.com/resource/BaseSearchResource/get/?' . http_build_query($params, '', '&', PHP_QUERY_RFC3986));
        try { $payload = json_decode($response['body'], true, 64, JSON_THROW_ON_ERROR); }
        catch (JsonException $e) { throw new RuntimeException('Image provider returned an unexpected response.'); }
        if (!is_array($payload)) { throw new RuntimeException('Image provider returned an unexpected response.'); }
        return json_encode(bt_parse_results($payload), JSON_THROW_ON_ERROR | JSON_INVALID_UTF8_SUBSTITUTE);
    });
    try { $data = json_decode($entry['body'], true, 64, JSON_THROW_ON_ERROR); }
    catch (JsonException $e) { throw new RuntimeException('Search cache is unavailable.'); }
    if (!is_array($data) || !is_array($data['results'] ?? null)) { throw new RuntimeException('Search cache is unavailable.'); }
    if (($data['bookmark'] ?? null) === $bookmark) { $data['bookmark'] = null; }
    header('Server-Timing: search;dur=' . round((microtime(true) - $start) * 1000, 1));
    header('X-Binternet-Cache: ' . ($entry['stale'] ? 'STALE' : ($entry['cached'] ? 'HIT' : 'MISS')));
    return $data + ['cached' => $entry['cached'], 'stale' => $entry['stale']];
}
