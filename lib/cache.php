<?php
declare(strict_types=1);

function bt_cache_dir(): string
{
    $dir = getenv('BINTERNET_CACHE_DIR') ?: sys_get_temp_dir() . '/binternet-cache';
    if (!is_dir($dir) && !@mkdir($dir, 0700, true) && !is_dir($dir)) {
        throw new RuntimeException('Cache is unavailable.');
    }
    if (is_link($dir) || !is_writable($dir)) {
        throw new RuntimeException('Cache is unavailable.');
    }
    return rtrim($dir, '/');
}

function bt_cache_path(string $namespace, string $key): string
{
    if (!in_array($namespace, ['search', 'image'], true)) {
        throw new InvalidArgumentException('Invalid cache namespace.');
    }
    return bt_cache_dir() . '/' . $namespace . '-' . hash('sha256', $key) . '.cache';
}

function bt_cache_get(string $namespace, string $key, int $maxAge): ?array
{
    $path = bt_cache_path($namespace, $key);
    clearstatcache(true, $path);
    $mtime = @filemtime($path);
    if ($mtime === false || time() - $mtime > $maxAge || is_link($path)) {
        return null;
    }
    $size = @filesize($path);
    if ($size === false || $size > 8 * 1024 * 1024) {
        return null;
    }
    $body = @file_get_contents($path);
    return $body === false ? null : ['body' => $body, 'age' => max(0, time() - $mtime)];
}

function bt_cache_put(string $namespace, string $key, string $body): void
{
    if (strlen($body) > 8 * 1024 * 1024) {
        return;
    }
    $dir = bt_cache_dir();
    $path = bt_cache_path($namespace, $key);
    $lock = @fopen($dir . '/write.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) {
        if ($lock) { fclose($lock); }
        return; // Caching must not delay a successful request.
    }
    $tmp = false;
    try {
        $files = glob($dir . '/*.cache') ?: [];
        $entries = [];
        $bytes = 0;
        foreach ($files as $file) {
            $size = @filesize($file) ?: 0;
            $mtime = @filemtime($file) ?: 0;
            if ($mtime < time() - 604800 || is_link($file)) {
                @unlink($file);
                continue;
            }
            $entries[] = [$file, $mtime, $size];
            $bytes += $size;
        }
        usort($entries, static fn(array $a, array $b): int => $a[1] <=> $b[1]);
        while ($entries && ($bytes + strlen($body) > 64 * 1024 * 1024 || count($entries) >= 512)) {
            [$file, , $size] = array_shift($entries);
            if (@unlink($file)) { $bytes -= $size; }
        }
        $tmp = @tempnam($dir, '.write-');
        if ($tmp !== false) {
            @chmod($tmp, 0600);
            if (@file_put_contents($tmp, $body) === strlen($body)) {
                @rename($tmp, $path);
            }
        }
    } finally {
        if ($tmp !== false && is_file($tmp)) { @unlink($tmp); }
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

/** Fixed lock shards bound both concurrent upstream calls and lock-file count. */
function bt_cached_fetch(string $namespace, string $key, int $ttl, int $staleAge, callable $fetch): array
{
    $cached = bt_cache_get($namespace, $key, $staleAge);
    if ($cached !== null && $cached['age'] <= $ttl) {
        return ['body' => $cached['body'], 'cached' => true, 'stale' => false];
    }
    $shard = hexdec(substr(hash('sha256', $namespace . $key), 0, 2)) % 16;
    $lock = @fopen(bt_cache_dir() . '/fetch-' . $shard . '.lock', 'c');
    if (!$lock) { throw new RuntimeException('Search is temporarily busy.'); }
    $acquired = false;
    try {
        $deadline = microtime(true) + 2;
        do {
            $acquired = flock($lock, LOCK_EX | LOCK_NB);
            if ($acquired) { break; }
            if ($cached !== null) {
                return ['body' => $cached['body'], 'cached' => true, 'stale' => true];
            }
            usleep(50000);
            $ready = bt_cache_get($namespace, $key, $ttl);
            if ($ready !== null) {
                return ['body' => $ready['body'], 'cached' => true, 'stale' => false];
            }
        } while (microtime(true) < $deadline);
        if (!$acquired) { throw new RuntimeException('Search is temporarily busy.'); }
        $ready = bt_cache_get($namespace, $key, $ttl);
        if ($ready !== null) {
            return ['body' => $ready['body'], 'cached' => true, 'stale' => false];
        }
        try {
            $body = $fetch();
            bt_cache_put($namespace, $key, $body);
            return ['body' => $body, 'cached' => false, 'stale' => false];
        } catch (RuntimeException $e) {
            if ($cached !== null) {
                return ['body' => $cached['body'], 'cached' => true, 'stale' => true];
            }
            throw $e;
        }
    } finally {
        if ($acquired) { flock($lock, LOCK_UN); }
        fclose($lock);
    }
}
