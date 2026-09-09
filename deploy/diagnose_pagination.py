#!/usr/bin/env python3
"""Inspect release .4 pagination using one temporary, private candidate.

Run as root on the VPS. Requires the already extracted .4 release and the exact
Docker image built in the reported attempt. Does not build, pull, or cut over.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

VERSION = '2026.09.08.4'
RELEASE = Path('/opt/binternet-releases/binternet-securityops-' + VERSION)
IMAGE = 'binternet-securityops:' + VERSION
EXPECTED_IMAGE = 'sha256:5e763949b7a8d343e776e4e847d93dd53dc1b7cc90f055673572938ed8807985'
BACKUP_ROOT = Path('/opt/binternet-backups')
LOCK_PATH = Path('/run/lock/binternet-upgrade.lock')
MAX_PROBE_BYTES = 2 * 1024 * 1024
PHP_PROBE = '<?php\ndeclare(strict_types=1);\n// CLI-only metadata probe. Never prints cursor values, image URLs or responses.\nif (PHP_SAPI !== \'cli\') { exit(1); }\nini_set(\'display_errors\', \'0\');\nob_start();\n$warnings = 0;\nset_error_handler(static function () use (&$warnings): bool { $warnings++; return true; });\n\nfunction pd_at(array $payload, array $path): array\n{\n    $value = $payload;\n    foreach ($path as $key) {\n        if (!is_array($value) || !array_key_exists($key, $value)) { return [false, null]; }\n        $value = $value[$key];\n    }\n    return [true, $value];\n}\n\nfunction pd_token(mixed $value, bool $present = true): array\n{\n    $report = [\'present\' => $present, \'type\' => get_debug_type($value)];\n    if (!is_string($value)) { return $report + [\'reason\' => $present ? \'not_string\' : \'absent\']; }\n    $bytes = strlen($value);\n    $utf8 = preg_match(\'//u\', $value) === 1;\n    $space = $utf8 && preg_match(\'/[\\s\\p{Cc}\\p{Z}]/u\', $value) === 1;\n    $end = in_array($value, [\'-end-\', \'-end\'], true) || str_starts_with($value, \'Y2JOb25lO\');\n    $reason = $value === \'\' ? \'empty\' : (!$utf8 ? \'invalid_utf8\' : ($space ? \'whitespace_or_control\' :\n        ($end ? \'end_marker\' : ($bytes > 4096 ? \'over_4096\' : ($bytes > 2048 ? \'over_2048\' : \'valid\')))));\n    return $report + [\'bytes\' => $bytes, \'reason\' => $reason,\n        \'accepted_by_installed_parser\' => bt_search_bookmark_token($value) !== null,\n        \'valid_under_4096_limit\' => $bytes > 0 && $bytes <= 4096 && $utf8 && !$space && !$end];\n}\n\nfunction pd_summary(array $payload): array\n{\n    $report = [\'cursor_fields\' => []];\n    $paths = [\n        \'resource_options_bookmarks_first\' => [\'resource\', \'options\', \'bookmarks\', 0],\n        \'response_bookmark\' => [\'resource_response\', \'bookmark\'],\n        \'response_bookmarks_first\' => [\'resource_response\', \'bookmarks\', 0],\n        \'response_data_bookmark\' => [\'resource_response\', \'data\', \'bookmark\'],\n        \'response_data_bookmarks_first\' => [\'resource_response\', \'data\', \'bookmarks\', 0],\n        \'root_bookmark\' => [\'bookmark\'],\n        \'root_bookmarks_first\' => [\'bookmarks\', 0],\n        \'data_pagination_bookmark\' => [\'resource_response\', \'data\', \'pagination\', \'bookmark\'],\n        \'data_next_cursor\' => [\'resource_response\', \'data\', \'next_cursor\'],\n    ];\n    foreach ($paths as $name => $path) {\n        [$present, $value] = pd_at($payload, $path);\n        $report[\'cursor_fields\'][$name] = pd_token($value, $present);\n    }\n    foreach ([\'resource_options\' => [\'resource\', \'options\', \'bookmarks\'],\n              \'response\' => [\'resource_response\', \'bookmarks\']] as $name => $path) {\n        [$present, $value] = pd_at($payload, $path);\n        $report[\'cursor_containers\'][$name] = [\'present\' => $present, \'type\' => get_debug_type($value),\n            \'count\' => is_array($value) ? count($value) : null,\n            \'is_list\' => is_array($value) ? array_is_list($value) : null];\n    }\n    [$cp, $cv] = pd_at($payload, $paths[\'resource_options_bookmarks_first\']);\n    [$lp, $lv] = pd_at($payload, $paths[\'response_bookmark\']);\n    $report[\'canonical_equals_legacy\'] = $cp && $lp && is_string($cv) && $cv === $lv;\n    try {\n        $parsed = bt_parse_results($payload);\n        $report[\'parser\'] = [\'ok\' => true, \'images\' => count($parsed[\'results\']),\n            \'bookmark\' => pd_token($parsed[\'bookmark\'])];\n    } catch (Throwable $failure) {\n        $report[\'parser\'] = [\'ok\' => false];\n    }\n    return $report;\n}\n\nfunction pd_request(?string $bookmark = null): array\n{\n    $options = [\'query\' => \'architecture\', \'scope\' => \'pins\', \'page_size\' => 25, \'rs\' => \'typed\'];\n    if ($bookmark !== null) { $options[\'bookmarks\'] = [$bookmark]; }\n    // Match .4\'s first request exactly. This diagnostic does not change headers.\n    $params = [\'source_url\' => \'/search/pins/?q=architecture\',\n        \'data\' => json_encode([\'options\' => $options, \'context\' => new stdClass()], JSON_THROW_ON_ERROR)];\n    $url = \'https://www.pinterest.com/resource/BaseSearchResource/get/?\'\n        . http_build_query($params, \'\', \'&\', PHP_QUERY_RFC3986);\n    $response = bt_http_get($url);\n    $payload = json_decode($response[\'body\'], true, 64, JSON_THROW_ON_ERROR);\n    if (!is_array($payload)) { throw new RuntimeException(); }\n    return $payload;\n}\n\nfunction pd_error(Throwable $failure): array\n{\n    if ($failure instanceof BtUpstreamException) {\n        return [\'kind\' => \'upstream\', \'reason\' => $failure->reason,\n            \'status\' => $failure->upstreamStatus, \'curl_errno\' => $failure->curlErrno];\n    }\n    return [\'kind\' => $failure instanceof JsonException ? \'invalid_json\' : \'local_or_response_error\'];\n}\n\nfunction pd_run(): array\n{\n    $report = [\'probe_version\' => 2, \'release\' => BT_VERSION, \'query\' => \'architecture\'];\n    try {\n        $payload = pd_request();\n        $report[\'first_page\'] = pd_summary($payload);\n        // Follow one safe raw cursor without changing .4 or its production cache.\n        // This distinguishes provider pagination from the old parser\'s length cap.\n        $response = $payload[\'resource_response\'] ?? [];\n        $candidate = bt_search_response_bookmark($payload, is_array($response) ? $response : []);\n        $origin = \'installed_parser\';\n        if ($candidate === null) {\n            [$present, $value] = pd_at($payload, [\'resource\', \'options\', \'bookmarks\', 0]);\n            if (!$present) { [$present, $value] = pd_at($payload, [\'resource_response\', \'bookmark\']); }\n            $meta = pd_token($value, $present);\n            if ($meta[\'valid_under_4096_limit\'] ?? false) { $candidate = $value; $origin = \'safe_raw_cursor\'; }\n        }\n        if ($candidate === null) { return $report + [\'second_page\' => [\'attempted\' => false]]; }\n        $first = bt_parse_results($payload);\n        $report[\'second_page\'] = [\'attempted\' => true, \'cursor_origin\' => $origin,\n            \'cursor_bytes\' => strlen($candidate)];\n        try {\n            $secondPayload = pd_request($candidate);\n            $second = bt_parse_results($secondPayload);\n            $report[\'second_page\'] += pd_summary($secondPayload);\n            $report[\'second_page\'][\'new_images\'] = count(array_diff(array_column($second[\'results\'], \'url\'),\n                array_column($first[\'results\'], \'url\')));\n        } catch (Throwable $failure) { $report[\'second_page\'][\'error\'] = pd_error($failure); }\n    } catch (Throwable $failure) { $report[\'error\'] = pd_error($failure); }\n    return $report;\n}\n\nif (!defined(\'PD_TEST_MODE\')) {\n    try {\n        require_once \'/var/www/binternet/lib/bootstrap.php\';\n        $report = pd_run();\n    } catch (Throwable $failure) { $report = [\'probe_version\' => 2, \'error\' => [\'kind\' => \'probe_bootstrap_error\']]; }\n    $report[\'suppressed_php_warnings\'] = $warnings;\n    ob_end_clean();\n    echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR), "\\n";\n}\n'


def check_page(base, path):
    """Never retain HTML, query cursors, response headers, or image URLs."""
    request = urllib.request.Request(base + path, headers={
        'User-Agent': 'Binternet-pagination-diagnostic/1'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), app.NoRedirect())
    try:
        reply = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        reply = error
    with reply:
        body = reply.read(MAX_PROBE_BYTES + 1)
        too_large = len(body) > MAX_PROBE_BYTES
        result = {'status': reply.status,
                  'content_type': reply.headers.get_content_type(),
                  'sample_bytes': min(len(body), MAX_PROBE_BYTES),
                  'body_limit_exceeded': too_large,
                  'images_count': 0, 'next_link_count': 0,
                  'next_link_valid': False, 'pagination': 'not_search'}
        if path == '/search.php?q=architecture':
            if too_large:
                result['pagination'] = 'response_too_large'
                return result
            page = app.SearchPage(body.decode('utf-8', errors='replace'))
            result['images_count'] = len(page.images)
            result['next_link_count'] = len(page.next_links)
            if reply.status != 200:
                result['pagination'] = 'http_error'
            elif not page.next_links:
                result['pagination'] = 'missing_next_link'
            elif len(page.next_links) != 1:
                result['pagination'] = 'multiple_next_links'
            else:
                try:
                    app.next_search_path(page)
                except (app.DeployError, ValueError, UnicodeError):
                    result['pagination'] = 'invalid_next_link'
                else:
                    result['pagination'] = 'valid_next_link'
                    result['next_link_valid'] = True
        return result


def load_upgrader():
    path = RELEASE / 'deploy' / 'upgrade.py'
    if not path.is_file():
        raise RuntimeError('Expected extracted .4 release was not found.')
    spec = importlib.util.spec_from_file_location('binternet_upgrade', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VERSION != VERSION:
        raise RuntimeError('The extracted updater is not release .4.')
    return module


def run_probe(candidate):
    """Bound elapsed time and captured stdout; do not capture stderr."""
    command = ['docker', 'exec', '-i', candidate, 'php84']
    with tempfile.TemporaryFile() as source:
        source.write(PHP_PROBE.encode('utf-8'))
        source.seek(0)
        process = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 90
            output = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, 90)
                    for key, _ in selector.select(min(remaining, 1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if len(output) + len(chunk) > MAX_PROBE_BYTES:
                            raise ValueError('Probe output exceeded its byte limit.')
                        output.extend(chunk)
            returncode = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            try:
                value = json.loads(output)
            except (ValueError, UnicodeError):
                return returncode, {'error': 'Probe did not produce valid JSON.',
                                    'stdout_bytes': len(output)}
            if not isinstance(value, dict):
                return returncode, {'error': 'Probe did not produce a JSON object.'}
            return returncode, value
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            process.stdout.close()


def collect(backup_root):
    """Caller holds the upgrade lock through creation, observation, and cleanup."""
    old = app.inspect('binternet')
    app.validate(old)
    tested_image = app.docker('image', 'inspect', '--format', '{{.Id}}', IMAGE)
    if tested_image != EXPECTED_IMAGE:
        raise RuntimeError('The .4 tag does not identify the image from the reported build.')
    run_id = 'pagination-diagnostic-' + secrets.token_hex(8)
    candidate = 'binternet-' + run_id
    output = backup_root / (run_id + '.json')
    report = {'diagnostic_version': 1, 'release': VERSION,
              'production_running_before': bool(old['State']['Running']),
              'candidate_image': tested_image, 'checks': {}}
    complete = False
    try:
        with tempfile.TemporaryDirectory(prefix='binternet-pagination-') as directory:
            environment = Path(directory) / 'environment'
            descriptor = os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                stream.write('\n'.join(old['Config'].get('Env') or []) + '\n')
            app.create(old, candidate, tested_image, environment, run_id, candidate=True)
            app.healthy(candidate)
            report['candidate_health'] = 'healthy'
            ports = app.inspect(candidate)['NetworkSettings']['Ports']['8080/tcp']
            port = next(p['HostPort'] for p in ports if p['HostIp'] == '127.0.0.1')
            if not str(port).isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError('Invalid candidate loopback port.')
            base = 'http://127.0.0.1:' + str(port)
            for path in ['/health.php', '/', '/static/app.css',
                         '/static/infinite-scroll.js', '/search.php?q=architecture']:
                try:
                    report['checks'][path] = check_page(base, path)
                except Exception as error:
                    report['checks'][path] = {'check_error': type(error).__name__}
            code, probe = run_probe(candidate)
            report['probe_exit_code'] = code
            report['probe'] = probe
            complete = code == 0 and 'error' not in probe
    except Exception as error:
        # Exception text can contain commands, environment values, or URLs.
        report['diagnostic_error'] = ('Probe exceeded its time limit.'
                                      if isinstance(error, subprocess.TimeoutExpired)
                                      else type(error).__name__)
    finally:
        try:
            found = app.maybe_inspect(candidate)
            owned = bool(found and (found['Config'].get('Labels') or {}).get(app.OWNER) == run_id)
            if owned:
                runtime = found['State']
                report['candidate_state'] = {
                    'running': bool(runtime.get('Running')),
                    'exit_code': runtime.get('ExitCode'),
                    'oom_killed': bool(runtime.get('OOMKilled')),
                    'health': (runtime.get('Health') or {}).get('Status')}
                app.remove_owned(candidate, run_id)
                report['temporary_container_removed'] = app.maybe_inspect(candidate) is None
            else:
                report['temporary_container_removed'] = found is None
                if found:
                    report['cleanup_error'] = 'Candidate ownership did not match; nothing was removed.'
        except Exception:
            report['temporary_container_removed'] = False
        if not report.get('temporary_container_removed'):
            report['temporary_container_name'] = candidate
        try:
            current = app.inspect('binternet')
            report['production_same_container'] = current['Id'] == old['Id']
            report['production_running_after'] = bool(current['State']['Running'])
        except Exception:
            report['production_status_check'] = 'Could not inspect production.'
        app.private_json(output, report)
        print(json.dumps(report, indent=2, ensure_ascii=True), flush=True)
        print('Diagnostic saved: ' + str(output), flush=True)
    unchanged = report.get('production_same_container') and report.get('production_running_after')
    return 0 if complete and unchanged and report.get('temporary_container_removed') else 1


def main():
    global app
    if os.geteuid() != 0:
        raise RuntimeError('Run this diagnostic as root on the VPS.')
    app = load_upgrader()
    os.umask(0o077)
    # Same lock as upgrade.py: prevent overlap with cutover or rollback.
    with open(LOCK_PATH, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another Binternet upgrade, rollback, or diagnostic is running.', file=sys.stderr)
            return 1
        BACKUP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(BACKUP_ROOT, 0o700)
        return collect(BACKUP_ROOT)


if __name__ == '__main__':
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    for stop_signal in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(stop_signal, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        print('Diagnostic could not start (' + type(error).__name__ + '). '
              'Confirm extracted release .4, its exact built image, and Docker are present.',
              file=sys.stderr)
        sys.exit(1)
