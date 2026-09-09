<?php
declare(strict_types=1);
require_once __DIR__ . '/misc/view.php';
$preferences = bt_preferences();
$query = '';
$bookmark = '';
$error = null;
$result = ['results' => [], 'bookmark' => null, 'cached' => false, 'stale' => false];
try {
    $query = trim(bt_param('q', '', 160));
    $bookmark = bt_param('bookmark', '', 2048);
    if ($query === '') {
        throw new InvalidArgumentException('Enter a search term to find images.');
    }
    $result = bt_search($query, $bookmark === '' ? null : $bookmark);
} catch (InvalidArgumentException $exception) {
    http_response_code(400);
    $error = ['title' => 'Let’s try that search again', 'message' => 'Enter a search term of up to 160 bytes. If you followed an old page link, start a new search.'];
} catch (BtUpstreamException $exception) {
    http_response_code(502);
    header('X-Binternet-Upstream-Error: ' . $exception->reason);
    if ($exception->upstreamStatus !== 0) {
        header('X-Binternet-Upstream-Status: ' . $exception->upstreamStatus);
    }
    error_log('Binternet upstream failure: class=BtUpstreamException reason=' . $exception->reason
        . ' status=' . $exception->upstreamStatus . ' curl_errno=' . $exception->curlErrno);
    $error = match ($exception->upstreamStatus) {
        403 => ['title' => 'Pinterest refused this search', 'message' => 'Pinterest refused this server’s request. Repeating the search may not resolve the refusal. Please try again later.'],
        429 => ['title' => 'Pinterest is limiting requests', 'message' => 'Pinterest is rate-limiting this instance. Please wait before trying again.'],
        default => ['title' => 'The image source is taking a break', 'message' => 'Pinterest could not return results right now. Please try again in a moment or use a different search.'],
    };
} catch (RuntimeException $exception) {
    http_response_code(502);
    $error = ['title' => 'The image source is taking a break', 'message' => 'Pinterest could not return results right now. Please try again in a moment or use a different search.'];
}
$infinite = ($preferences['scroll'] ?? 'manual') === 'infinite';
$hasNext = is_string($result['bookmark']) && $result['bookmark'] !== '';
require __DIR__ . '/misc/header.php';
?>
    <title><?= bt_escape($query !== '' ? $query . ' — Binternet' : 'Search — Binternet') ?></title>
    <?php if ($infinite && $error === null && $result['results'] !== [] && $hasNext): ?><script src="static/infinite-scroll.js?v=<?= bt_escape(BT_VERSION) ?>" defer></script><?php endif; ?>
  </head>
  <body data-theme="<?= bt_escape($preferences['theme']) ?>">
    <a class="skip-link" href="#main">Skip to results</a>
    <?php bt_render_navigation($preferences, $query, true); ?>
    <main id="main" class="results-main shell">
      <?php bt_render_search_form($preferences, $query); ?>
      <div class="results-heading">
        <div>
          <p class="eyebrow">YOUR NEXT IDEA STARTS HERE</p>
          <h1><?= bt_escape($query !== '' ? $query : 'Explore images') ?></h1>
          <?php if ($error === null): ?>
            <p class="result-meta"><?= count($result['results']) ?> images on this page <span aria-hidden="true">·</span> <?= bt_escape(bt_quality_label($preferences['quality'])) ?>
              <?php if ($result['stale']): ?><span class="cache-status">Saved results · live source unavailable</span>
              <?php elseif ($result['cached']): ?><span class="cache-status">From cache</span><?php endif; ?>
            </p>
          <?php endif; ?>
        </div>
        <?php if ($query !== ''): bt_render_layouts($preferences, $query, $bookmark); endif; ?>
      </div>
      <?php bt_render_preferences($preferences, $query, $bookmark); ?>
      <?php if ($error !== null): ?>
        <section class="empty-state" role="status">
          <?= bt_icon('search') ?><h2><?= bt_escape($error['title']) ?></h2>
          <p><?= bt_escape($error['message']) ?></p>
          <a class="button button-secondary" href="<?= bt_escape(bt_page_url('index.php', $preferences)) ?>">Back to explore</a>
        </section>
      <?php elseif ($result['results'] === []): ?>
        <section class="empty-state" role="status">
          <?= bt_icon('image') ?><h2>No images here yet</h2>
          <p>Try a broader phrase, a different spelling, or a new direction.</p>
          <a class="button button-secondary" href="<?= bt_escape(bt_page_url('index.php', $preferences)) ?>">Explore a new idea</a>
        </section>
        <div id="image-gallery" class="image-gallery" data-scroll="<?= $infinite ? 'infinite' : 'manual' ?>"></div>
        <nav id="pagination" class="pagination" aria-label="Search result pages">
          <?php if ($hasNext): ?>
            <a id="next-page" class="button" rel="next" href="<?= bt_escape(bt_page_url('search.php', $preferences, ['q' => $query, 'bookmark' => $result['bookmark']])) ?>">Next page <?= bt_icon('arrow') ?></a>
          <?php else: ?><p class="muted">You’ve reached the end of these results. Try a new search.</p><?php endif; ?>
        </nav>
      <?php else: ?>
        <div id="image-gallery" class="image-gallery" data-scroll="<?= $infinite ? 'infinite' : 'manual' ?>">
        <section class="gallery-page gallery gallery-<?= bt_escape($preferences['view']) ?>" aria-label="Image search results">
          <?php foreach ($result['results'] as $position => $item): bt_render_image($item, $preferences, $position); endforeach; ?>
        </section>
        </div>
        <?php if ($infinite): ?>
          <div class="scroll-controls">
            <p id="scroll-status" role="status" aria-live="polite" aria-atomic="true"><?= $hasNext ? 'Scroll down to load more images.' : 'You’ve reached the end of these results.' ?></p>
            <button id="scroll-toggle" class="button button-secondary" type="button" aria-pressed="false" hidden>Pause auto-loading</button>
            <button id="scroll-retry" class="button button-secondary" type="button" hidden>Retry loading</button>
          </div>
          <div id="scroll-sentinel" aria-hidden="true"></div>
          <noscript><p class="muted">Automatic loading needs JavaScript. You can keep browsing with Next page.</p></noscript>
        <?php endif; ?>
        <nav id="pagination" class="pagination" aria-label="Search result pages">
          <?php if ($bookmark !== ''): ?><a class="text-link" href="<?= bt_escape(bt_page_url('search.php', $preferences, ['q' => $query])) ?>">← First page</a><?php endif; ?>
          <?php if ($hasNext): ?>
            <a id="next-page" class="button" rel="next" href="<?= bt_escape(bt_page_url('search.php', $preferences, ['q' => $query, 'bookmark' => $result['bookmark']])) ?>">Next page <?= bt_icon('arrow') ?></a>
          <?php else: ?><p class="muted">You’ve reached the end of these results. Try a new search.</p><?php endif; ?>
        </nav>
      <?php endif; ?>
    </main>
    <?php require __DIR__ . '/misc/footer.php'; ?>
