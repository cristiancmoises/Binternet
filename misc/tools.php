<?php
    function get_root_domain($url) {
      return parse_url($url, PHP_URL_HOST);
    }

    function get_url_scheme($url) {
      $scheme = parse_url($url, PHP_URL_SCHEME);
      return $scheme === null ? null : strtolower($scheme);
    }

    function request($url)
    {
      $ch = curl_init($url);
      curl_setopt($ch, CURLOPT_HEADER, false);
      curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

      // SSRF hardening: never follow redirects (an open redirect on an
      // allow-listed host must not be able to bounce us to an internal
      // address), and only ever speak HTTP(S) so schemes like file://,
      // gopher:// or dict:// can't be smuggled through even to an
      // allow-listed host.
      curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);
      if (defined('CURLOPT_PROTOCOLS_STR')) {
        curl_setopt($ch, CURLOPT_PROTOCOLS_STR, "http,https");
        curl_setopt($ch, CURLOPT_REDIR_PROTOCOLS_STR, "http,https");
      } else {
        curl_setopt($ch, CURLOPT_PROTOCOLS, CURLPROTO_HTTP | CURLPROTO_HTTPS);
        curl_setopt($ch, CURLOPT_REDIR_PROTOCOLS, CURLPROTO_HTTP | CURLPROTO_HTTPS);
      }

      // Resource-exhaustion hardening: bound connect/total time and the
      // maximum response size we are willing to buffer and echo back.
      curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
      curl_setopt($ch, CURLOPT_TIMEOUT, 15);
      curl_setopt($ch, CURLOPT_MAXFILESIZE, 20 * 1024 * 1024);

      $body = curl_exec($ch);
      $content_type = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
      curl_close($ch);

      return array(
        "body" => $body === false ? null : $body,
        "content_type" => $content_type,
      );
    }
?>
