<?php
declare(strict_types=1);
require_once __DIR__ . '/../lib/bootstrap.php';

function bt_icon(string $name): string
{
    $paths = [
        'search' => '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
        'shield' => '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/><path d="m8 12 3 3 5-6"/>',
        'layout' => '<rect x="3" y="3" width="7" height="11" rx="1"/><rect x="14" y="3" width="7" height="6" rx="1"/><rect x="3" y="18" width="7" height="3" rx="1"/><rect x="14" y="13" width="7" height="8" rx="1"/>',
        'image' => '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',
        'arrow' => '<path d="M4 12h15m-6-6 6 6-6 6"/>',
        'settings' => '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
        'grid' => '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        'compact' => '<path d="M3 4h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4zM3 11h4v4H3zm7 0h4v4h-4zm7 0h4v4h-4zM3 18h4v3H3zm7 0h4v3h-4zm7 0h4v3h-4z"/>',
        'justified' => '<path d="M3 3h11v7H3zm15 0h3v7h-3zM3 14h5v7H3zm9 0h9v7h-9z"/>',
        'focus' => '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 16h16"/>',
    ];
    return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . ($paths[$name] ?? $paths['image']) . '</svg>';
}

function bt_page_url(string $page, array $preferences, array $parameters = []): string
{
    return $page . '?' . http_build_query(array_merge($preferences, $parameters), '', '&', PHP_QUERY_RFC3986);
}

function bt_render_hidden_preferences(array $preferences): void
{
    foreach ($preferences as $key => $value) {
        echo '<input type="hidden" name="' . bt_escape($key) . '" value="' . bt_escape($value) . '">';
    }
}

function bt_render_navigation(array $preferences, string $query = '', bool $isSearch = false): void
{
    ?>
    <header class="site-header shell">
      <a class="brand" href="<?= bt_escape(bt_page_url('index.php', $preferences)) ?>" aria-label="Binternet home"><span class="brand-mark" aria-hidden="true"><?= bt_icon('layout') ?></span>Binternet<span class="brand-period" aria-hidden="true">.</span></a>
      <nav aria-label="Main navigation"><a class="nav-active" href="<?= bt_escape(bt_page_url('index.php', $preferences)) ?>">Explore</a><a href="#preferences"><?= bt_icon('settings') ?><span>Appearance</span></a><a class="external-nav" href="https://securityops.co" rel="noreferrer">SecurityOps <span aria-hidden="true">↗</span></a></nav>
    </header>
    <?php
}

function bt_render_search_form(array $preferences, string $query = ''): void
{
    ?>
    <form class="search-form" action="search.php" method="get" role="search">
      <label class="sr-only" for="image-query">Search Pinterest images</label>
      <span class="search-symbol"><?= bt_icon('search') ?></span>
      <input id="image-query" type="search" name="q" value="<?= bt_escape($query) ?>" placeholder="What inspires you?" required maxlength="160" autocomplete="off" enterkeyhint="search">
      <?php bt_render_hidden_preferences($preferences); ?>
      <button class="button search-submit" type="submit"><span>Search</span><?= bt_icon('arrow') ?></button>
    </form>
    <?php
}

function bt_quality_label(string $quality): string
{
    return ['auto' => 'Adaptive quality', 'high' => 'High quality', 'original' => 'Original images', 'saver' => 'Data saver'][$quality] ?? 'Adaptive quality';
}

function bt_render_preferences(array $preferences, string $query = '', string $bookmark = ''): void
{
    $themes = ['black' => 'Pure black', 'charcoal' => 'Charcoal', 'midnight' => 'Midnight', 'paper' => 'Paper', 'forest' => 'Forest'];
    $views = ['masonry' => 'Masonry', 'grid' => 'Grid', 'compact' => 'Compact', 'justified' => 'Justified', 'focus' => 'Focus'];
    ?>
    <details id="preferences" class="preferences" <?= $query === '' ? 'open' : '' ?>>
      <summary><span><?= bt_icon('settings') ?>Make it your space</span><span class="preference-summary"><?= bt_escape($themes[$preferences['theme']]) ?> <span aria-hidden="true">/</span> <?= bt_escape($views[$preferences['view']]) ?><span class="details-chevron" aria-hidden="true">⌄</span></span></summary>
      <form class="preference-form" action="<?= $query === '' ? 'index.php' : 'search.php' ?>" method="get">
        <?php if ($query !== ''): ?><input type="hidden" name="q" value="<?= bt_escape($query) ?>"><?php endif; ?>
        <?php if ($bookmark !== ''): ?><input type="hidden" name="bookmark" value="<?= bt_escape($bookmark) ?>"><?php endif; ?>
        <fieldset class="theme-options"><legend>Background</legend><div class="theme-swatches">
          <?php foreach ($themes as $value => $label): ?>
            <label class="theme-option"><input type="radio" name="theme" value="<?= bt_escape($value) ?>" <?= $preferences['theme'] === $value ? 'checked' : '' ?>><span class="theme-swatch swatch-<?= bt_escape($value) ?>" aria-hidden="true"></span><span><?= bt_escape($label) ?></span></label>
          <?php endforeach; ?>
        </div></fieldset>
        <div class="select-field"><label for="gallery-view">Gallery</label><select name="view" id="gallery-view"><?php foreach ($views as $value => $label): ?><option value="<?= bt_escape($value) ?>" <?= $preferences['view'] === $value ? 'selected' : '' ?>><?= bt_escape($label) ?></option><?php endforeach; ?></select></div>
        <div class="select-field"><label for="image-quality">Preview quality</label><select name="quality" id="image-quality"><?php foreach (['auto', 'high', 'original', 'saver'] as $quality): ?><option value="<?= bt_escape($quality) ?>" <?= $preferences['quality'] === $quality ? 'selected' : '' ?>><?= bt_escape(bt_quality_label($quality)) ?></option><?php endforeach; ?></select></div>
        <div class="select-field"><label for="browse-mode">Browsing</label><select name="scroll" id="browse-mode"><option value="manual" <?= ($preferences['scroll'] ?? 'manual') === 'manual' ? 'selected' : '' ?>>Manual pages</option><option value="infinite" <?= ($preferences['scroll'] ?? 'manual') === 'infinite' ? 'selected' : '' ?>>Infinite scroll</option></select></div>
        <button class="button button-secondary" type="submit">Apply</button>
        <p class="preference-help">Settings travel with your links. Infinite scroll loads more as you browse; you can pause it anytime. Original images use more data.</p>
      </form>
    </details>
    <?php
}

function bt_render_layouts(array $preferences, string $query, string $bookmark): void
{
    $layouts = ['masonry' => ['Masonry', 'layout'], 'grid' => ['Grid', 'grid'], 'compact' => ['Compact', 'compact'], 'justified' => ['Justified', 'justified'], 'focus' => ['Focus', 'focus']];
    echo '<nav class="layout-switcher" aria-label="Gallery layout">';
    foreach ($layouts as $value => [$label, $icon]) {
        $url = bt_page_url('search.php', $preferences, ['q' => $query, 'view' => $value] + ($bookmark !== '' ? ['bookmark' => $bookmark] : []));
        echo '<a href="' . bt_escape($url) . '" title="' . bt_escape($label) . '" aria-label="' . bt_escape($label) . ' layout"' . ($preferences['view'] === $value ? ' aria-current="true"' : '') . '>' . bt_icon($icon) . '<span>' . bt_escape($label) . '</span></a>';
    }
    echo '</nav>';
}

function bt_render_image(array $item, array $preferences, int $position): void
{
    $title = trim((string) ($item['title'] ?? ''));
    if ($title === '') {
        $title = 'Image ' . ($position + 1);
    }
    $original = (string) $item['url'];
    $variants = array_values(array_filter($item['variants'] ?? [], static fn(array $variant): bool => !empty($variant['url']) && ($variant['width'] ?? 0) > 0));
    usort($variants, static fn(array $a, array $b): int => $a['width'] <=> $b['width']);
    $chosen = $original;
    if ($preferences['quality'] === 'saver' && $variants !== []) {
        $chosen = $variants[0]['url'];
        foreach ($variants as $variant) {
            if ($variant['width'] <= 360) {
                $chosen = $variant['url'];
            }
        }
    } elseif ($preferences['quality'] !== 'original' && $variants !== []) {
        $target = ['auto' => 736, 'high' => 1200][$preferences['quality']] ?? 736;
        $chosen = $variants[count($variants) - 1]['url'];
        foreach ($variants as $variant) {
            if ($variant['width'] >= $target) {
                $chosen = $variant['url'];
                break;
            }
        }
    }
    $srcset = [];
    if ($preferences['quality'] === 'auto') {
        foreach ($variants as $variant) {
            $srcset[(int) $variant['width']] = bt_image_url($variant['url']) . ' ' . (int) $variant['width'] . 'w';
        }
        if (($item['width'] ?? 0) > 0) {
            $srcset[(int) $item['width']] = bt_image_url($original) . ' ' . (int) $item['width'] . 'w';
        }
    }
    $sizes = match ($preferences['view']) {
        'focus' => '(max-width: 760px) 94vw, 920px',
        'compact' => '(max-width: 600px) 30vw, (max-width: 1100px) 20vw, 190px',
        'justified' => '(max-width: 600px) 90vw, (max-width: 1100px) 45vw, 400px',
        default => '(max-width: 600px) 46vw, (max-width: 1000px) 30vw, (max-width: 1400px) 23vw, 270px',
    };
    $width = max(0, (int) ($item['width'] ?? 0));
    $height = max(0, (int) ($item['height'] ?? 0));
    $ratio = $height > 0 ? $width / $height : 1.0;
    $shape = $ratio > 1.35 ? 'wide' : ($ratio < 0.8 ? 'tall' : 'square');
    ?>
    <figure class="image-card image-<?= $shape ?>">
      <a class="image-link" href="<?= bt_escape(bt_image_url($original)) ?>" aria-label="<?= bt_escape('Open original image: ' . $title) ?>">
        <img src="<?= bt_escape(bt_image_url($chosen)) ?>" <?php if ($srcset !== []): ?>srcset="<?= bt_escape(implode(', ', $srcset)) ?>" sizes="<?= bt_escape($sizes) ?>"<?php endif; ?> alt="<?= bt_escape($title) ?>" <?php if ($width > 0 && $height > 0): ?>width="<?= $width ?>" height="<?= $height ?>"<?php endif; ?> loading="<?= $position < 4 ? 'eager' : 'lazy' ?>" decoding="async" <?= $position === 0 ? 'fetchpriority="high"' : '' ?>>
        <span class="image-open" aria-hidden="true">View original ↗</span>
      </a>
      <figcaption><span class="image-title"><?= bt_escape($title) ?></span><?php if ($width > 0 && $height > 0): ?><span class="image-dimensions"><?= $width ?> × <?= $height ?></span><?php endif; ?></figcaption>
    </figure>
    <?php
}
