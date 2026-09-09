import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location('pagination_diagnostic', ROOT / 'diagnose_pagination.py')
module = importlib.util.module_from_spec(spec)
module.__dict__['__PHP_PROBE__'] = '<?php echo "{}";'
spec.loader.exec_module(module)
upgrade_spec = importlib.util.spec_from_file_location('pagination_upgrade', ROOT / 'upgrade.py')
upgrader = importlib.util.module_from_spec(upgrade_spec)
upgrade_spec.loader.exec_module(upgrader)


class DiagnosticTests(unittest.TestCase):
    def fake_app(self, fail=None):
        events = []
        old = {'Id': 'production-id', 'State': {'Running': True},
               'Config': {'Env': ['PRIVATE_TOKEN=do-not-print']}}
        fake = types.SimpleNamespace(VERSION=module.VERSION, OWNER='owner')
        state = {'present': False}
        def inspect(name):
            events.append(('inspect', name))
            if name == 'binternet':
                return old
            if not state['present']:
                return None
            return {'Id': 'diagnostic-id',
                    'State': {'Running': True, 'ExitCode': 0, 'Health': {'Status': 'healthy'}},
                    'Config': {'Labels': {'owner': 'someone-else' if fail == 'ownership' else state['run_id']}},
                    'NetworkSettings': {'Ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '54321'}]}}}
        fake.inspect = inspect
        fake.maybe_inspect = inspect
        fake.validate = lambda obj: events.append(('validate', obj['Id']))
        def docker(*args):
            self.assertEqual(args, ('image', 'inspect', '--format', '{{.Id}}', module.IMAGE))
            events.append(('image', module.IMAGE))
            return 'sha256:unexpected' if fail == 'image' else module.EXPECTED_IMAGE
        fake.docker = docker
        def create(obj, name, image, environment, run_id, candidate=False):
            self.assertTrue(candidate)
            self.assertNotIn(name, ['binternet', 'npm-attachment', 'binternet-candidate-20260907'])
            self.assertEqual(image, module.EXPECTED_IMAGE)
            self.assertEqual(environment.stat().st_mode & 0o777, 0o600)
            self.assertEqual(environment.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(environment.read_text(), 'PRIVATE_TOKEN=do-not-print\n')
            state.update(run_id=run_id, name=name, present=True, environment=environment)
            events.append(('create', name))
        fake.create = create
        def healthy(name):
            if fail == 'startup':
                raise RuntimeError('private startup details')
            events.append(('healthy', name))
        fake.healthy = healthy
        def remove(name, run_id):
            self.assertEqual((name, run_id), (state['name'], state['run_id']))
            state['present'] = False
            events.append(('removed', name, run_id))
        fake.remove_owned = remove
        def private_json(path, value):
            upgrader.private_json(path, value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            state.update(report=value)
        fake.private_json = private_json
        def forbidden(*args, **kwargs):
            self.fail('A production cutover helper was called.')
        fake.perform = fake.restore = forbidden
        return fake, state, events

    def run_case(self, fail=None):
        fake, state, events = self.fake_app(fail)
        def probe(candidate):
            self.assertEqual(candidate, state['name'])
            if fail == 'interrupt':
                raise KeyboardInterrupt()
            if fail == 'timeout':
                raise subprocess.TimeoutExpired(['private-command'], 90)
            return 0, {'probe_version': 1, 'cursor_bytes': 2064, 'accepted_by_release': False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            with patch.object(module, 'load_upgrader', return_value=fake), \
                 patch.object(module, 'BACKUP_ROOT', root / 'backups'), \
                 patch.object(module, 'LOCK_PATH', root / 'upgrade.lock'), \
                 patch.object(module.os, 'geteuid', return_value=0), \
                 patch.object(module, 'check_page', return_value={'status': 200, 'pagination': 'missing_next_link'}), \
                 patch.object(module, 'run_probe', side_effect=probe), contextlib.redirect_stdout(output):
                if fail == 'interrupt':
                    with self.assertRaises(KeyboardInterrupt):
                        module.main()
                else:
                    code = module.main()
                    self.assertEqual(code, 0 if fail is None else 1)
            self.assertEqual((root / 'backups').stat().st_mode & 0o777, 0o700)
        for sensitive in ('PRIVATE_TOKEN', 'do-not-print', 'private startup', 'private-command'):
            self.assertNotIn(sensitive, output.getvalue())
        self.assertTrue(state['report']['production_same_container'])
        self.assertTrue(state['report']['production_running_after'])
        self.assertFalse(state['environment'].exists())
        if fail == 'ownership':
            self.assertFalse(state['report']['temporary_container_removed'])
            self.assertFalse(any(e[0] == 'removed' for e in events))
        else:
            self.assertTrue(state['report']['temporary_container_removed'])
            self.assertIn(('removed', state['name'], state['run_id']), events)
        return state['report']

    def test_missing_next_link_diagnosed_without_cutover(self):
        report = self.run_case()
        self.assertEqual(len(report['checks']), 5)
        self.assertEqual(report['checks']['/search.php?q=architecture']['pagination'], 'missing_next_link')
        self.assertEqual(report['probe']['cursor_bytes'], 2064)

    def test_cleanup_after_startup_timeout_and_interruption(self):
        for fail in ['startup', 'timeout', 'interrupt']:
            with self.subTest(fail=fail):
                self.run_case(fail)

    def test_unowned_candidate_is_never_removed(self):
        self.run_case('ownership')

    def test_wrong_image_and_held_upgrade_lock_refuse_creation(self):
        for fail in ['image', 'lock']:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                fake, state, events = self.fake_app(fail)
                root = Path(directory)
                lock_path = root / 'upgrade.lock'
                with open(lock_path, 'a') as held, \
                     patch.object(module, 'load_upgrader', return_value=fake), \
                     patch.object(module, 'BACKUP_ROOT', root / 'backups'), \
                     patch.object(module, 'LOCK_PATH', lock_path), \
                     patch.object(module.os, 'geteuid', return_value=0), \
                     contextlib.redirect_stderr(io.StringIO()):
                    if fail == 'lock':
                        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self.assertEqual(module.main(), 1)
                        self.assertEqual(events, [])
                    else:
                        with self.assertRaises(RuntimeError):
                            module.main()
                self.assertFalse(state['present'])
                self.assertFalse(any(e[0] == 'create' for e in events))

    def test_real_http_counts_safe_links_and_does_not_follow_redirects(self):
        class Handler(BaseHTTPRequestHandler):
            mode = 'valid'
            paths = []
            def do_GET(self):
                type(self).paths.append(self.path)
                if self.mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/never-follow')
                    self.end_headers()
                    return
                next_link = ('<a id="next-page" rel="next" href="search.php?q=architecture&amp;bookmark=PRIVATE-CURSOR">Next page</a>'
                             if self.mode == 'valid' else '')
                if self.mode == 'invalid':
                    next_link = '<a id="next-page" rel="next" href="https://example.invalid/?token=PRIVATE-CURSOR">Next page</a>'
                body = ('<div id="image-gallery"><img src="image_proxy.php?url=https%3A%2F%2Fi.pinimg.com%2Foriginals%2Fprivate-image.jpg"></div>' + next_link).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            with patch.object(module, 'app', upgrader, create=True), \
                 patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1'}):
                for mode, expected in [('valid', 'valid_next_link'), ('missing', 'missing_next_link'),
                                       ('invalid', 'invalid_next_link'), ('redirect', 'http_error')]:
                    with self.subTest(mode=mode):
                        Handler.mode = mode
                        result = module.check_page(base, '/search.php?q=architecture')
                        self.assertEqual(result['pagination'], expected)
                        self.assertEqual(result['next_link_valid'], mode == 'valid')
                        self.assertEqual(result['images_count'], 0 if mode == 'redirect' else 1)
                        self.assertNotIn('PRIVATE-CURSOR', json.dumps(result))
                        self.assertNotIn('private-image', json.dumps(result))
            self.assertNotIn('/never-follow', Handler.paths)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_probe_output_bound_and_json_validation(self):
        real_popen = subprocess.Popen
        for script, expected in [('import sys; sys.stdout.write("x" * 200000)', 'oversize'),
                                 ('print("not JSON")', 'invalid'),
                                 ('print("{\\"probe_version\\":1}")', 'valid')]:
            with self.subTest(expected=expected):
                def popen(command, **kwargs):
                    self.assertEqual(command, ['docker', 'exec', '-i', 'temporary-candidate', 'php84'])
                    self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
                    return real_popen([sys.executable, '-c', script], **kwargs)
                with patch.object(module.subprocess, 'Popen', side_effect=popen), \
                     patch.object(module, 'MAX_PROBE_BYTES', 1024):
                    if expected == 'oversize':
                        with self.assertRaises(ValueError):
                            module.run_probe('temporary-candidate')
                    else:
                        code, result = module.run_probe('temporary-candidate')
                        self.assertEqual(code, 0)
                        self.assertEqual('error' in result, expected == 'invalid')


if __name__ == '__main__':
    unittest.main(verbosity=2)
