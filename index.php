<?php
declare(strict_types=1);
require_once __DIR__ . '/misc/view.php';
$preferences = bt_preferences();
require __DIR__ . '/misc/header.php';
?>
    <title>Binternet — A little more inspiration</title>
  </head>
  <body data-theme="<?= bt_escape($preferences['theme']) ?>">
    <a class="skip-link" href="#main">Skip to content</a>
    <?php bt_render_navigation($preferences); ?>
    <main id="main" class="home-main shell">
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow"><span class="status-dot" aria-hidden="true"></span> LESS CLUTTER. MORE INSPIRATION.</p>
        <h1 id="hero-title">A world of images.<br><span>Space to explore.</span></h1>
        <p class="hero-copy">Find the detail that sparks your next idea.<br class="wide-only"> Pinterest image search, with room to breathe.</p>
        <?php bt_render_search_form($preferences); ?>
        <p class="search-note"><?= bt_icon('shield') ?> Images served through this instance <span aria-hidden="true">·</span> No account needed</p>
      </section>

      <section class="discover" aria-labelledby="discover-title">
        <div class="section-heading">
          <div><p class="eyebrow">A PLACE TO START</p><h2 id="discover-title">Follow your curiosity</h2></div>
          <span class="muted small-text">Pick a direction. Make it yours.</span>
        </div>
        <div class="collection-grid">
          <?php
          $collections = [
              ['Architecture', 'architectural photography', 'architecture', 'Lines, light & perspective'],
              ['Nature', 'landscape nature photography', 'nature', 'A breath of somewhere else'],
              ['Interiors', 'minimal interior design', 'interiors', 'Spaces worth staying in'],
              ['Design', 'graphic design typography', 'design', 'Ideas with a point of view'],
              ['Photography', 'cinematic street photography', 'photography', 'Ordinary, seen differently'],
              ['Art', 'abstract art painting', 'abstract', 'Color outside the lines'],
          ];
          foreach ($collections as [$title, $search, $art, $description]): ?>
            <a class="collection collection-<?= bt_escape($art) ?>" href="<?= bt_escape(bt_page_url('search.php', $preferences, ['q' => $search])) ?>">
              <span class="collection-art" aria-hidden="true"><i></i><i></i><i></i></span>
              <span class="collection-copy"><strong><?= bt_escape($title) ?></strong><span><?= bt_escape($description) ?></span></span>
              <span class="collection-arrow" aria-hidden="true">↗</span>
            </a>
          <?php endforeach; ?>
        </div>
      </section>

      <?php bt_render_preferences($preferences); ?>
      <section class="home-features" aria-label="About this search">
        <div><?= bt_icon('layout') ?><h3>Your kind of gallery</h3><p>Five layouts, from a flowing masonry wall to a focused, full-width view.</p></div>
        <div><?= bt_icon('image') ?><h3>Room for the details</h3><p>Responsive previews by default. Choose high quality, original, or data saver.</p></div>
        <div><?= bt_icon('shield') ?><h3>A lighter way to look</h3><p>No client-side JavaScript. Search and image requests pass through this server.</p></div>
      </section>
    </main>
    <?php require __DIR__ . '/misc/footer.php'; ?>
