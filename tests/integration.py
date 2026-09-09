#!/usr/bin/env python3
"""HTTP regression checks; starts PHP locally or accepts --base-url for Docker.

Uses only the Python standard library. The default run makes no upstream calls.
The built-in PHP server checks application behavior, not nginx access controls.
"""

import argparse
import contextlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import tarfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = ""
EXTERNAL_SERVER = False
FIXTURE_QUERY = 'art & "design" <script>alert(1)</script>'
FIXTURE_BOOKMARK = 'opaque/next+page==&x="quoted"'
FIXTURE_IMAGE = "https://i.pinimg.com/originals/http-fixture.gif"
CANONICAL_QUERY = "canonical pagination"
CANONICAL_BOOKMARK = "a" * 2064
SECOND_IMAGE = "https://i.pinimg.com/originals/second-page.gif"


def request(path, method="GET", headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(urllib.request.Request(BASE_URL + path, method=method, headers=headers or {}), timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read()


class Page(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.forms = []
        self.current_form = None
        self.current_select = None
        self.feed(body.decode("utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "form":
            self.current_form = {"attrs": attrs, "controls": {}}
            self.forms.append(self.current_form)
        elif self.current_form is not None:
            controls = self.current_form["controls"]
            if tag == "input" and attrs.get("name"):
                if attrs.get("type") not in ("radio", "checkbox") or "checked" in attrs:
                    controls[attrs["name"]] = attrs.get("value", "")
            elif tag == "select":
                self.current_select = attrs.get("name")
            elif tag == "option" and self.current_select:
                if self.current_select not in controls or "selected" in attrs:
                    controls[self.current_select] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None
        elif tag == "select":
            self.current_select = None

    def attrs(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]


def seed_cache(env):
    """Write only this test's temporary cache through the real cache API."""
    pin = {
        "id": "123456789", "title": '<img src=x onerror="alert(1)"> Art & "design"',
        "url": FIXTURE_IMAGE, "width": 1800, "height": 1200,
        "variants": [
            {"url": "https://i.pinimg.com/236x/http-fixture.gif", "width": 236, "height": 157},
            {"url": "https://i.pinimg.com/736x/http-fixture.gif", "width": 736, "height": 490},
            {"url": FIXTURE_IMAGE, "width": 1800, "height": 1200},
        ],
    }
    payload = {"results": [pin], "bookmark": FIXTURE_BOOKMARK}
    raw_pin = {"id": pin["id"], "title": pin["title"], "images": {
        "small": pin["variants"][0], "medium": pin["variants"][1], "orig": pin["variants"][2],
    }}
    raw_second = {"id": "987654321", "title": "Second page", "images": {
        "orig": {"url": SECOND_IMAGE, "width": 1200, "height": 800},
    }}
    fixtures = [
        {"query": CANONICAL_QUERY, "cursor": "", "payload": {
            "resource_response": {"status": "success", "data": [raw_pin]},
            "resource": {"options": {"bookmarks": [CANONICAL_BOOKMARK]}},
        }},
        {"query": CANONICAL_QUERY, "cursor": CANONICAL_BOOKMARK, "payload": {
            "resource_response": {"status": "success", "data": [raw_second]},
            "resource": {"options": {"bookmarks": ["-end-"]}},
        }},
    ]
    program = r'''
require $argv[1] . '/lib/bootstrap.php';
$input = json_decode(file_get_contents('php://stdin'), true, 64, JSON_THROW_ON_ERROR);
$data = json_encode($input['parsed'], JSON_THROW_ON_ERROR);
bt_cache_put('search', bt_search_cache_key($argv[2]), $data);
bt_cache_put('search', bt_search_cache_key($argv[2], $argv[3]), $data);
foreach ($input['raw'] as $fixture) {
    bt_cache_put('search', bt_search_cache_key($fixture['query'], $fixture['cursor']),
        json_encode(bt_parse_results($fixture['payload']), JSON_THROW_ON_ERROR));
}
bt_cache_put('image', $argv[4], base64_decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'));
'''
    subprocess.run(
        ["php", "-r", program, str(ROOT), FIXTURE_QUERY, FIXTURE_BOOKMARK, FIXTURE_IMAGE],
        input=json.dumps({"parsed": payload, "raw": fixtures}), text=True, env=env, check=True, capture_output=True,
    )


class HttpRegressionTests(unittest.TestCase):
    def test_home_is_complete_html(self):
        status, headers, body = request("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("Binternet", text)
        self.assertIn("</html>", text.lower())
        self.assertIn("<form", text.lower())
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertNotIn("Fatal error", text)

    def test_proxy_blocks_arbitrary_destinations(self):
        urls = [
            "http://127.0.0.1/", "https://127.0.0.1/", "http://169.254.169.254/",
            "file:///etc/passwd", "gopher://127.0.0.1/", "https://example.com/a.jpg",
            "https://i.pinimg.com.evil.example/a.jpg", "https://i.pinimg.com@127.0.0.1/a.jpg",
            "https://i.pinimg.com:8443/a.jpg",
            "https://i.pinimg.com/a.jpg\r\nHost: localhost", "//i.pinimg.com/a.jpg",
        ]
        for url in urls:
            with self.subTest(url=url):
                status, _, body = request("/image_proxy.php?" + urllib.parse.urlencode({"url": url}))
                self.assertIn(status, (400, 403))
                self.assertNotIn(b"root:", body)
                self.assertNotIn(b"Fatal error", body)

    def test_array_parameters_do_not_crash(self):
        for path in ["/?theme[]=black&view[]=grid", "/search.php?q[]=test", "/image_proxy.php?url[]=test"]:
            with self.subTest(path=path):
                status, _, body = request(path)
                self.assertLess(status, 500)
                self.assertNotIn(b"Fatal error", body)
                self.assertNotIn(b"TypeError", body)

    def test_invalid_preferences_are_not_reflected(self):
        attack = '\"><script>alert(1)</script>'
        path = "/?" + urllib.parse.urlencode({"theme": attack, "view": attack, "quality": attack, "scroll": attack})
        status, _, body = request(path)
        self.assertEqual(status, 200)
        self.assertNotIn(attack.encode(), body)
        self.assertNotIn(b"<script", body.lower())

    def test_security_headers(self):
        status, headers, _ = request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn("frame-ancestors 'none'", headers.get("Content-Security-Policy", ""))
        self.assertIn("script-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertIn("connect-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertNotIn("unsafe-inline", headers.get("Content-Security-Policy", ""))
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_linked_stylesheet_is_served_with_all_themes_and_galleries(self):
        status, _, body = request("/")
        self.assertEqual(status, 200)
        sheets = [link for link in Page(body).attrs("link") if link.get("rel") == "stylesheet"]
        self.assertTrue(sheets, "Home page has no stylesheet")
        css_parts = []
        for link in sheets:
            parsed = urllib.parse.urlsplit(link["href"])
            self.assertFalse(parsed.netloc, "Stylesheet must be served by this instance")
            path = "/" + parsed.path.lstrip("/") + ("?" + parsed.query if parsed.query else "")
            status, headers, stylesheet = request(path)
            self.assertEqual(status, 200, path)
            self.assertIn("text/css", headers.get("Content-Type", ""), path)
            css_parts.append(stylesheet.decode("utf-8"))
        css = "\n".join(css_parts)
        self.assertGreater(len(css), 1000)
        for theme in ["black", "charcoal", "midnight", "paper", "forest"]:
            self.assertRegex(css, r'data-theme\s*=\s*[\"\x27]?' + theme + r'[\"\x27]?\s*\]')
        for gallery in ["masonry", "grid", "compact", "justified", "focus"]:
            self.assertIn(".gallery-" + gallery, css)

    def test_health_is_dependency_checked(self):
        status, _, body = request("/health.php")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_cached_search_escapes_content_and_preserves_pagination(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        status, headers, body = request("/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY, "theme": "paper", "view": "grid", "quality": "high"}))
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Binternet-Cache"), "HIT")
        self.assertNotIn(b"<script", body.lower())
        page = Page(body)
        query_inputs = [item for item in page.attrs("input") if item.get("name") == "q"]
        self.assertTrue(query_inputs)
        self.assertEqual(query_inputs[0].get("value"), FIXTURE_QUERY)
        pagination = []
        for link in page.attrs("a"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(link.get("href", "")).query)
            if "bookmark" in params:
                pagination.append(params)
        self.assertTrue(pagination, "Missing continuation link")
        for params in pagination:
            self.assertEqual(params["q"], [FIXTURE_QUERY])
            self.assertEqual(params["bookmark"], [FIXTURE_BOOKMARK])
            self.assertEqual(params["theme"], ["paper"])
            self.assertEqual(params["view"], ["grid"])
            self.assertEqual(params["quality"], ["high"])
        for tag, attrs in page.tags:
            self.assertFalse(any(name.lower().startswith("on") for name in attrs), tag)
        for image in page.attrs("img"):
            self.assertFalse(image.get("src", "").startswith("https://i.pinimg.com"))

    def test_all_galleries_and_quality_modes_render_from_cache(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        for view in ["masonry", "grid", "compact", "justified", "focus"]:
            for quality in ["auto", "high", "original", "saver"]:
                with self.subTest(view=view, quality=quality):
                    path = "/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY, "view": view, "quality": quality})
                    status, headers, body = request(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get("X-Binternet-Cache"), "HIT")
                    self.assertTrue(Page(body).attrs("img"))
                    self.assertNotIn(b"Warning:", body)
                    self.assertNotIn(b"Fatal error", body)

    def test_theme_form_submissions_preserve_the_search(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        status, _, body = request("/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY}))
        self.assertEqual(status, 200)
        forms = [form for form in Page(body).forms if {"theme", "view", "quality", "q"} <= set(form["controls"])]
        self.assertTrue(forms, "No complete appearance form found")
        form = forms[-1]
        self.assertEqual(form["attrs"].get("method", "get").lower(), "get")
        for theme in ["black", "charcoal", "midnight", "paper", "forest"]:
            with self.subTest(theme=theme):
                controls = dict(form["controls"], theme=theme)
                self.assertEqual(controls["q"], FIXTURE_QUERY)
                path = "/" + form["attrs"].get("action", "search.php").lstrip("/") + "?" + urllib.parse.urlencode(controls)
                status, headers, result = request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("X-Binternet-Cache"), "HIT")
                rendered = Page(result)
                self.assertEqual(rendered.attrs("body")[0].get("data-theme"), theme)
                queries = [item for item in rendered.attrs("input") if item.get("name") == "q"]
                self.assertTrue(queries)
                self.assertTrue(all(item.get("value") == FIXTURE_QUERY for item in queries))

    def test_data_saver_uses_small_variant_and_keeps_original_link(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        path = "/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY, "quality": "saver"})
        status, _, body = request(path)
        self.assertEqual(status, 200)
        page = Page(body)
        images = page.attrs("img")
        self.assertTrue(images)
        source = urllib.parse.parse_qs(urllib.parse.urlsplit(images[0]["src"]).query)
        self.assertEqual(source.get("url"), ["https://i.pinimg.com/236x/http-fixture.gif"])
        self.assertNotIn("srcset", images[0], "Data saver must not allow a larger responsive download")
        original_links = [link for link in page.attrs("a") if "image-link" in link.get("class", "").split()]
        self.assertTrue(original_links)
        original = urllib.parse.parse_qs(urllib.parse.urlsplit(original_links[0]["href"]).query)
        self.assertEqual(original.get("url"), [FIXTURE_IMAGE])

    def test_repeated_bookmark_does_not_create_pagination_loop(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        path = "/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY, "bookmark": FIXTURE_BOOKMARK})
        status, _, body = request(path)
        self.assertEqual(status, 200)
        for link in Page(body).attrs("a"):
            self.assertNotIn("next", link.get("rel", "").split())

    def test_canonical_cursor_renders_next_page_and_reaches_distinct_final_page(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses raw provider fixtures in the isolated local cache")
        for scroll in ("manual", "infinite"):
            with self.subTest(scroll=scroll):
                params = {"q": CANONICAL_QUERY, "theme": "forest", "view": "focus", "quality": "saver", "scroll": scroll}
                status, _, body = request("/search.php?" + urllib.parse.urlencode(params))
                self.assertEqual(status, 200)
                page = Page(body)
                links = [a for a in page.attrs("a") if a.get("id") == "next-page"]
                self.assertEqual(len(links), 1)
                self.assertIn("next", links[0].get("rel", "").split())
                self.assertIn(b"Next page", body)
                target = urllib.parse.urlsplit(links[0]["href"])
                self.assertFalse(target.scheme or target.netloc)
                actual = urllib.parse.parse_qs(target.query)
                self.assertEqual(actual, {key: [value] for key, value in dict(params, bookmark=CANONICAL_BOOKMARK).items()})
                scripts = page.attrs("script")
                self.assertEqual(len(scripts), 1 if scroll == "infinite" else 0)
                if scripts:
                    self.assertEqual(urllib.parse.urlsplit(scripts[0]["src"]).path, "static/infinite-scroll.js")
                    self.assertIn("defer", scripts[0])
                    self.assertTrue(any(a.get("id") == "scroll-status" and a.get("aria-live") == "polite" for _, a in page.tags))
                for tag, attrs in page.tags:
                    self.assertFalse(any(name.lower().startswith("on") for name in attrs), tag)
                status, _, second_body = request("/" + links[0]["href"].lstrip("/"))
                self.assertEqual(status, 200)
                second = Page(second_body)
                self.assertFalse(any("next" in a.get("rel", "").split() for a in second.attrs("a")))
                originals = [urllib.parse.parse_qs(urllib.parse.urlsplit(a.get("href", "")).query).get("url")
                             for a in second.attrs("a") if "image-link" in a.get("class", "").split()]
                self.assertEqual(originals, [[SECOND_IMAGE]])
                self.assertEqual(second.attrs("script"), [], "Final page needs no infinite-scroll script")

    def test_infinite_preference_survives_forms_and_layout_links(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        status, _, body = request("/search.php?" + urllib.parse.urlencode({"q": FIXTURE_QUERY, "scroll": "infinite"}))
        self.assertEqual(status, 200)
        page = Page(body)
        self.assertTrue(page.forms)
        for form in page.forms:
            self.assertEqual(form["controls"].get("scroll"), "infinite")
        for link in page.attrs("a"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(link.get("href", "")).query)
            if "view" in params:
                self.assertEqual(params.get("scroll"), ["infinite"])

    def test_infinite_scroll_asset_is_served(self):
        status, headers, body = request("/static/infinite-scroll.js")
        self.assertEqual(status, 200)
        self.assertIn(headers.get("Content-Type", "").split(";")[0], ("application/javascript", "text/javascript"))
        self.assertGreater(len(body), 1024)
        self.assertIn(b"IntersectionObserver", body)

    def test_cached_image_conditional_and_head_requests(self):
        if EXTERNAL_SERVER:
            self.skipTest("uses the isolated local fixture cache")
        path = "/image_proxy.php?" + urllib.parse.urlencode({"url": FIXTURE_IMAGE})
        status, headers, body = request(path)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/gif")
        self.assertTrue(body.startswith(b"GIF89a"))
        self.assertEqual(headers.get("X-Binternet-Cache"), "HIT")
        etag = headers.get("ETag")
        self.assertTrue(etag)
        status, _, conditional_body = request(path, headers={"If-None-Match": etag})
        self.assertEqual(status, 304)
        self.assertEqual(conditional_body, b"")
        status, head_headers, head_body = request(path, method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers.get("Content-Length"), str(len(body)))
        status, headers, _ = request(path, method="POST")
        self.assertEqual(status, 405)
        self.assertIn("GET", headers.get("Allow", ""))

    def test_nginx_blocks_nonpublic_files(self):
        if not EXTERNAL_SERVER:
            self.skipTest("nginx protection checks require --base-url against Docker/nginx")
        for path in ["/.git/config", "/lib/bootstrap.php", "/tests/security.php", "/README.md", "/Dockerfile", "/misc/tools.php"]:
            with self.subTest(path=path):
                status, _, body = request(path)
                self.assertIn(status, (403, 404))
                self.assertNotIn(b"<?php", body)

    def test_container_exposes_complete_filtered_corresponding_source(self):
        if not EXTERNAL_SERVER:
            self.skipTest("source archive is assembled by the Docker build")
        status, _, body = request("/source.tar.gz")
        self.assertEqual(status, 200)
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
            members = archive.getmembers()
            names = {item.name.removeprefix("./") for item in members}
            for expected in ["LICENSE", "Dockerfile", "README.md", "lib/bootstrap.php", "deploy/upgrade.py", "tests/security.php", ".github/workflows/php-lint.yml"]:
                self.assertIn(expected, names)
            for item in members:
                name = item.name.removeprefix("./")
                parts = Path(name).parts
                self.assertFalse(item.name.startswith("/") or ".." in parts)
                self.assertNotIn(".git", parts)
                self.assertNotIn("__pycache__", parts)
                self.assertFalse(Path(name).name == ".env" or (Path(name).name.startswith(".env.") and Path(name).name != ".env.example"))


@contextlib.contextmanager
def php_server():
    if not shutil.which("php"):
        raise RuntimeError("PHP CLI is required (with curl and fileinfo extensions).")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="binternet-http-tests-") as temp:
        env = dict(os.environ)
        env["BINTERNET_CACHE_DIR"] = str(Path(temp) / "cache")
        seed_cache(env)
        with open(Path(temp) / "server.log", "w+") as log:
            process = subprocess.Popen(
                ["php", "-d", "display_errors=1", "-S", f"127.0.0.1:{port}", "-t", str(ROOT)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError("PHP server exited: " + log.read())
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.05)
                else:
                    raise RuntimeError("PHP server did not become ready")
                yield f"http://127.0.0.1:{port}"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    global BASE_URL, EXTERNAL_SERVER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Existing local Docker/nginx origin to test")
    args = parser.parse_args()
    EXTERNAL_SERVER = bool(args.base_url)
    server_context = contextlib.nullcontext(args.base_url) if args.base_url else php_server()
    with server_context as url:
        BASE_URL = url.rstrip("/")
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(HttpRegressionTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
