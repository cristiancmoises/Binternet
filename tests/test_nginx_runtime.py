#!/usr/bin/env python3
"""Regression for nginx writable paths and startup with the shipped server config.

Run: python3 tests/test_nginx_runtime.py
Set NGINX_BIN when nginx is outside PATH. Live checks skip if nginx is absent.
The live check translates container paths into a temporary directory and runs
one nginx process. It exercises nginx, not Docker isolation or PHP-FPM.
"""

import ast
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
TEMP_DIRECTIVES = (
    "client_body_temp_path", "fastcgi_temp_path", "proxy_temp_path",
    "scgi_temp_path", "uwsgi_temp_path",
)


def temp_paths(config):
    paths = {}
    for name in TEMP_DIRECTIVES:
        values = re.findall(r"^\s*" + name + r"\s+([^;\s]+)\s*;", config, re.M)
        if len(values) != 1:
            raise AssertionError("Configure exactly one explicit " + name +
                                 "; packaged nginx defaults may be read-only")
        paths[name] = PurePosixPath(values[0])
    return paths


def deployment_tmpfs():
    module = ast.parse((ROOT / "deploy/upgrade.py").read_text())
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TMPFS"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Deployment TMPFS configuration is missing")


class RuntimeConfiguration(unittest.TestCase):
    def test_all_module_temp_paths_are_on_writable_deployment_mounts(self):
        mounts = deployment_tmpfs()
        for name, path in temp_paths((ROOT / "deploy/nginx-main.conf").read_text()).items():
            with self.subTest(directive=name):
                self.assertTrue(path.is_absolute())
                self.assertNotIn("..", path.parts)
                matching = [options for mount, options in mounts.items()
                            if PurePosixPath(mount) in path.parents]
                self.assertTrue(matching, str(path) + " is outside the tmpfs mounts")
                self.assertTrue(any("rw" in options.split(",") for options in matching))

    def test_entrypoint_uses_stderr_before_config_parsing_and_preflights(self):
        commands = []
        for line in (ROOT / "deploy/entrypoint.sh").read_text().splitlines():
            if not line.lstrip().startswith("/usr/sbin/nginx "):
                continue
            tokens = shlex.split(line, comments=True)
            if tokens and tokens[0] == "/usr/sbin/nginx":
                commands.append(tokens)
        self.assertGreaterEqual(len(commands), 2, "Expect preflight and foreground nginx")
        self.assertIn("-t", commands[0], "Validate nginx before starting services")
        self.assertTrue(any("daemon off;" in command for command in commands))
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("-e", command, "Avoid opening Alpine's default error log")
                self.assertEqual(command[command.index("-e") + 1], "stderr")


class LiveNginx(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nginx = os.environ.get("NGINX_BIN") or shutil.which("nginx")
        if not nginx:
            raise unittest.SkipTest("nginx is not installed; set NGINX_BIN to run live checks")
        main = (ROOT / "deploy/nginx-main.conf").read_text()
        # Check before launching: a missing directive must never touch host defaults.
        paths = temp_paths(main)
        cls.directory = tempfile.TemporaryDirectory(prefix="binternet-nginx-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        work = Path(cls.directory.name)
        cache = work / "cache"
        cache.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base_url = "http://127.0.0.1:" + str(port)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        # This test serves static content only; PHP is covered by integration.py.
        (work / "mime.types").write_text("types { text/css css; image/svg+xml svg; }\n")
        (work / "fastcgi_params").write_text("fastcgi_param QUERY_STRING $query_string;\n")
        server = (ROOT / "nginx.conf").read_text()
        server = server.replace("listen 8080 default_server;",
                                "listen 127.0.0.1:" + str(port) + " default_server;")
        server = server.replace("root /var/www/binternet;", 'root "' + str(ROOT) + '";')
        server = server.replace("include fastcgi_params;",
                                'include "' + str(work / "fastcgi_params") + '";')
        (work / "server.conf").write_text(server)
        main = main.replace("pid /run/nginx.pid;", 'pid "' + str(work / "nginx.pid") + '";')
        main = main.replace("include /etc/nginx/mime.types;",
                            'include "' + str(work / "mime.types") + '";')
        main = main.replace("include /etc/nginx/http.d/*.conf;",
                            'include "' + str(work / "server.conf") + '";')
        if os.geteuid() == 0:
            # Some test containers map only uid 0. Keep the invoking identity
            # and use one process instead of trying to switch to nginx's uid.
            main = "user root root;\n" + main
        cls.expected_directories = []
        for name, path in paths.items():
            translated = cache / name
            main = main.replace(str(path) + ";", '"' + str(translated) + '";')
            cls.expected_directories.append(translated)
        config = work / "nginx.conf"
        config.write_text(main)
        cls.command = [nginx, "-e", "stderr", "-p", str(work) + "/", "-c", str(config)]
        preflight = subprocess.run(cls.command + ["-T"], capture_output=True,
                                   text=True, timeout=10)
        if preflight.returncode:
            raise AssertionError("nginx config preflight failed:\n" + preflight.stderr)
        cls.config_dump = preflight.stdout
        cls.log = open(work / "runtime.log", "w+")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen(cls.command + ["-g", "daemon off; master_process off;"],
                                       stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_nginx)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise AssertionError("nginx exited during startup:\n" + cls.log.read())
            try:
                with cls.opener.open(cls.base_url + "/static/app.css", timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        cls.log.seek(0)
        raise AssertionError("nginx did not become ready:\n" + cls.log.read())

    @classmethod
    def stop_nginx(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)

    def test_nginx_initializes_all_five_explicit_temp_paths(self):
        for path in self.expected_directories:
            with self.subTest(path=path.name):
                self.assertIn(str(path), self.config_dump)
                self.assertTrue(path.is_dir(), "nginx must initialize the module temp directory")

    def test_static_css_is_served_with_security_headers(self):
        with self.opener.open(self.base_url + "/static/app.css", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), (ROOT / "static/app.css").read_bytes())
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("Content-Type"), "text/css")

    def test_private_source_paths_are_denied(self):
        for path in ("/lib/bootstrap.php", "/deploy/nginx-main.conf", "/Dockerfile", "/.env", "/tests/infinite-scroll.test.js"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.opener.open(self.base_url + path, timeout=2)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()

    def test_optional_scroll_script_has_correct_mime_and_csp(self):
        with self.opener.open(self.base_url + "/static/infinite-scroll.js", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), (ROOT / "static/infinite-scroll.js").read_bytes())
            self.assertEqual(response.headers.get("Content-Type"), "application/javascript")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            csp = response.headers.get("Content-Security-Policy", "")
            self.assertIn("script-src 'self'", csp)
            self.assertIn("connect-src 'self'", csp)
            self.assertNotIn("unsafe-inline", csp)

    def test_long_cursor_request_line_fits_but_over_limit_is_rejected(self):
        # Static response isolates nginx's URI budget from PHP/FPM availability.
        path = "/static/app.css?bookmark=" + "%2F" * 4096
        with self.opener.open(self.base_url + path, timeout=2) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.opener.open(self.base_url + "/static/app.css?bookmark=" + "a" * 17000, timeout=2)
        self.assertEqual(error.exception.code, 414)
        error.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
