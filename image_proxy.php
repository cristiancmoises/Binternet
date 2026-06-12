<?php

require "misc/tools.php";

$url = isset($_GET["url"]) ? $_GET["url"] : "";

$scheme = get_url_scheme($url);
$host = get_root_domain($url);

$allowed_domains = array("pinimg.com", "i.pinimg.com", "pinterest.com");

// Only proxy http(s) requests whose host is exactly one of the Pinterest
// image hosts. Strict comparison avoids type-juggling surprises.
if (($scheme === "http" || $scheme === "https") && in_array($host, $allowed_domains, true))
{
  $result = request($url);
  $content_type = isset($result["content_type"]) ? (string) $result["content_type"] : "";

  // Only ever hand a real image back to the browser, so the proxy can't be
  // turned into a generic open proxy for arbitrary content types.
  if ($result["body"] !== null && strncmp($content_type, "image/", 6) === 0)
  {
    header("Content-Type: " . $content_type);
    header("X-Content-Type-Options: nosniff");
    header("Content-Security-Policy: default-src 'none'");
    echo $result["body"];
  }
  else
  {
    http_response_code(502);
  }
}
else
{
  http_response_code(403);
}

?>
