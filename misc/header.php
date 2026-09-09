<?php
require_once __DIR__ . '/../lib/bootstrap.php';
bt_security_headers();
header('Content-Type: text/html; charset=utf-8');
?>
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Explore Pinterest images with Binternet. Five gallery layouts, five themes, and image previews served through this instance. No account needed. Manual pages work without JavaScript; infinite scrolling is optional.">
    <meta name="referrer" content="no-referrer">
    <meta name="color-scheme" content="dark light">
    <link rel="stylesheet" href="static/app.css?v=<?= bt_escape(BT_VERSION) ?>">
