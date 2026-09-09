<?php
declare(strict_types=1);
require_once __DIR__ . '/misc/view.php';
$preferences = bt_preferences();
require __DIR__ . '/misc/header.php';
?>
    <title>Upstream support — Binternet</title>
  </head>
  <body data-theme="<?= bt_escape($preferences['theme']) ?>">
    <a class="skip-link" href="#main">Skip to content</a>
    <?php bt_render_navigation($preferences); ?>
    <main id="main" class="shell home-main">
      <section class="empty-state">
        <p class="eyebrow">PROJECT ROOTS</p>
        <h1>Support the original author</h1>
        <p>Binternet began with Ahwxorg. The donation links below support the original upstream author; they are preserved from the original project.</p>
        <p><a class="button button-secondary" href="https://ko-fi.com/Ahwxorg" rel="noopener noreferrer">Ahwxorg on Ko-fi ↗</a></p>
        <p><a class="text-link" href="https://www.buymeacoffee.com/ahwx" rel="noopener noreferrer">Ahwxorg on Buy Me a Coffee ↗</a></p>
        <p>Monero (upstream author):</p>
        <p class="donation-address">4ArntPzKpu32s4z2XqYhyaY1eUeUBKtCzJqEqxWtF5mCi5vR6sdhh32Hd2fk9FjeUxYDtaaUexUqoRNxrgfrtuXs4XpgMNJ</p>
        <p class="muted">External links take you away from this instance.</p>
      </section>
      <?php bt_render_preferences($preferences); ?>
    </main>
    <?php require __DIR__ . '/misc/footer.php'; ?>
