#!/usr/bin/env python3
"""Deployment unit/state-machine tests. Does not claim to run a Docker daemon."""
import argparse
import copy
import html
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import patch

import upgrade as app


def original():
    return {
        'Id': 'a' * 64, 'Name': '/binternet', 'Mounts': [],
        'Config': {'Env': ['PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'SECRET=do-not-print'],
                   'Labels': {'custom.label': 'kept', 'com.docker.compose.project': 'legacy'}},
        'State': {'Running': True, 'Health': {'Status': 'healthy'}},
        'HostConfig': {'NetworkMode': 'npm-bridge', 'Memory': 536870912, 'RestartPolicy': {'Name': 'unless-stopped'},
                       'PortBindings': {'8080/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '5134'}, {'HostIp': '::', 'HostPort': '5134'}]},
                       'LogConfig': {'Type': 'json-file', 'Config': {}}},
        'NetworkSettings': {'Networks': {'npm-bridge': {'Aliases': ['binternet', 'images', 'a' * 12], 'IPAMConfig': None},
                                          'extra': {'Aliases': ['binternet-extra'], 'IPAMConfig': None}}},
    }


class FakeDocker:
    def __init__(self, fail_new_start=False, candidate_exit=None):
        self.containers = {'a' * 64: original()}
        other = copy.deepcopy(original())
        other.update(Id='c' * 64, Name='/binternet-candidate-20260907')
        self.containers[other['Id']] = other
        self.calls = []
        self.count = 0
        self.fail_new_start = fail_new_start
        self.candidate_exit = candidate_exit

    def find(self, value):
        return next((obj for obj in self.containers.values() if obj['Id'] == value or obj['Name'].lstrip('/') == value), None)

    def __call__(self, *args, check=True):
        self.calls.append(args)
        action = args[0]
        if action == 'inspect':
            obj = self.find(args[1])
            if obj:
                return json.dumps([obj])
            if not check:
                return None
            raise app.DeployError('Missing container')
        if action == 'image':
            return 'sha256:testedimage'
        if action == 'update':
            obj = self.find(args[-1])
            obj['HostConfig']['RestartPolicy'] = {'Name': args[args.index('--restart') + 1]}
            return obj['Id']
        if action == 'create':
            self.count += 1
            ident = str(self.count) * 64
            name = args[args.index('--name') + 1]
            owner = args[args.index('--label') + 1].split('=', 1)[1]
            network = args[args.index('--network') + 1]
            obj = original()
            obj.update(Id=ident, Name='/' + name)
            obj['Config']['Labels'] = {app.OWNER: owner}
            obj['State']['Running'] = False
            obj['NetworkSettings']['Networks'] = {network: {'Aliases': [], 'IPAMConfig': None}}
            obj['NetworkSettings']['Ports'] = {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '49177'}]}
            self.containers[ident] = obj
            return ident
        if action in ('start', 'stop', 'rename', 'rm'):
            ident = args[-1] if action in ('stop', 'rm') else args[1]
            obj = self.find(ident)
            if action == 'start':
                if self.fail_new_start and obj['Name'] == '/binternet' and obj['Id'] != 'a' * 64:
                    raise app.DeployError('Simulated replacement start failure')
                obj['State']['Running'] = True
                if self.candidate_exit is not None and '-check-' in obj['Name']:
                    obj['State'].update(Running=False, ExitCode=self.candidate_exit, OOMKilled=False,
                                        Health={'Status': 'starting', 'Log': [{'Output': 'private health details'}]})
            elif action == 'stop':
                obj['State']['Running'] = False
            elif action == 'rename':
                obj['Name'] = '/' + args[2]
            else:
                del self.containers[obj['Id']]
            return obj['Id']
        if action == 'network':
            obj = self.find(args[-1])
            network = args[-2]
            if args[1] == 'disconnect':
                obj['NetworkSettings']['Networks'].pop(network)
            else:
                aliases = [args[i + 1] for i, arg in enumerate(args) if arg == '--alias']
                obj['NetworkSettings']['Networks'][network] = {'Aliases': aliases, 'IPAMConfig': None}
            return ''
        raise AssertionError(args)


class ConfigTests(unittest.TestCase):
    def test_published_ipv4_ipv6_restart_resources_and_aliases_preserved(self):
        args = app.create_args(original(), 'binternet', app.IMAGE, '/private/env', 'run')
        self.assertIn('0.0.0.0:5134:8080/tcp', args)
        self.assertIn('[::]:5134:8080/tcp', args)
        self.assertIn('unless-stopped', args)
        self.assertIn('536870912', args)
        self.assertIn('images', args)
        self.assertNotIn('a' * 12, args)
        self.assertIn('custom.label=kept', args)
        self.assertNotIn('com.docker.compose.project=legacy', args)
        self.assertNotIn('SECRET=do-not-print', args)

    def test_candidate_uses_dynamic_loopback_and_does_not_claim_production_aliases(self):
        args = app.create_args(original(), 'unique-check', app.IMAGE, '/private/env', 'run', True)
        self.assertIn('127.0.0.1::8080', args)
        self.assertNotIn('--network-alias', args)
        self.assertNotIn('custom.label=kept', args)
        self.assertNotIn('15134', args)

    def test_custom_mounts_refused(self):
        old = original()
        old['Mounts'] = [{'Source': '/secrets', 'Destination': '/app'}]
        with self.assertRaisesRegex(app.DeployError, 'mounts'):
            app.validate(old)

    def test_static_container_ip_refused(self):
        old = original()
        old['NetworkSettings']['Networks']['extra']['IPAMConfig'] = {'IPv4Address': '172.18.0.5'}
        with self.assertRaisesRegex(app.DeployError, 'Static'):
            app.validate(old)

    def test_multiline_environment_refused(self):
        old = original()
        old['Config']['Env'].append('TOKEN=line1\nline2')
        with self.assertRaisesRegex(app.DeployError, 'Multiline'):
            app.validate(old)

    def test_dynamic_old_port_refused_before_cutover(self):
        old = original()
        old['HostConfig']['PortBindings']['8080/tcp'][0]['HostPort'] = ''
        with self.assertRaisesRegex(app.DeployError, 'dynamically'):
            app.validate(old)

    def test_snapshot_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot'
            app.private_json(path, original())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_restart_failure_retry_count_preserved(self):
        old = original()
        old['HostConfig']['RestartPolicy'] = {'Name': 'on-failure', 'MaximumRetryCount': 7}
        args = app.create_args(old, 'binternet', app.IMAGE, '/private/env', 'run')
        self.assertEqual(args[args.index('--restart') + 1], 'on-failure:7')

    def test_docker_error_keeps_daemon_output_private(self):
        result = argparse.Namespace(returncode=125, stdout='', stderr='sensitive daemon details')
        with patch.object(app.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(app.DeployError, r'Docker start failed \(exit 125\)') as caught:
                app.docker('start', 'candidate')
        self.assertNotIn('sensitive', str(caught.exception))
        self.assertEqual(caught.exception.diagnostics['stderr'], 'sensitive daemon details')


class TransitionTests(unittest.TestCase):
    def perform(self, fake, directory, check_side_effect=None):
        args = argparse.Namespace(container='binternet', backup_dir=directory, skip_upstream_check=False)
        with patch.object(app, 'docker', side_effect=fake), \
             patch.object(app.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout='', stderr='')), \
             patch.object(app, 'candidate_checks', side_effect=check_side_effect):
            app.perform(args)

    def test_candidate_failure_keeps_original_running(self):
        fake = FakeDocker()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(app.DeployError, 'upstream'):
                self.perform(fake, directory, app.DeployError('upstream unavailable'))
        self.assertTrue(fake.find('binternet')['State']['Running'])
        self.assertFalse(any(call[0] == 'stop' for call in fake.calls))
        self.assertEqual(len(fake.containers), 2)

    def test_http_502_preserves_upstream_403_and_never_stops_production(self):
        fake = FakeDocker()
        failure = app.HTTPCheckError('/search.php?q=private-query', 502, {
            'X-Binternet-Upstream-Status': '403', 'X-Binternet-Upstream-Error': 'http_status'})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(app.HTTPCheckError):
                self.perform(fake, directory, failure)
            path = next(Path(directory).glob('*/failure-diagnostics/failure.json'))
            report = json.loads(path.read_text())
            self.assertEqual(report['http_error']['upstream_status'], 403)
            self.assertEqual(report['http_error']['endpoint'], '/search.php')
            self.assertNotIn('private-query', path.read_text())
        self.assertTrue(fake.find('binternet')['State']['Running'])
        self.assertFalse(any(call[0] == 'stop' for call in fake.calls))
        self.assertEqual(len(fake.containers), 2)

    def test_exited_candidate_evidence_saved_privately_before_cleanup(self):
        fake = FakeDocker(candidate_exit=78)
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(container='binternet', backup_dir=directory, skip_upstream_check=False)
            cleaned = []

            def command(*command_args, **kwargs):
                if command_args[0] == 'rm':
                    # Evidence must exist while the failed candidate still exists
                    # and before any production disruption, not after cleanup.
                    self.assertTrue(fake.find('binternet')['State']['Running'])
                    self.assertIsNotNone(fake.find(command_args[-1]))
                    evidence = next(Path(directory).glob('*/failure-diagnostics'))
                    self.assertIn('startup failed', (evidence / 'container.log').read_text())
                    self.assertTrue((evidence / 'container-inspect.json').exists())
                    cleaned.append(command_args[-1])
                return fake(*command_args, **kwargs)

            def process(command_args, **kwargs):
                if command_args[1] == 'logs':
                    self.assertTrue(fake.find('binternet')['State']['Running'])
                    return argparse.Namespace(returncode=0, stdout='starting\n',
                                              stderr='startup failed: SECRET=do-not-print\n')
                return argparse.Namespace(returncode=0, stdout='', stderr='')

            with patch.object(app, 'docker', side_effect=command), \
                 patch.object(app.subprocess, 'run', side_effect=process), \
                 patch.object(app.sys, 'stderr', stderr):
                with self.assertRaisesRegex(app.DeployError, 'exited'):
                    app.perform(args)
            evidence = next(Path(directory).glob('*/failure-diagnostics'))
            runtime = json.loads((evidence / 'container-state.json').read_text())
            self.assertEqual(runtime['ExitCode'], 78)
            self.assertEqual(runtime['Health']['Log'][0]['Output'], 'private health details')
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o700)
            for path in evidence.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn(str(evidence), stderr.getvalue())
        self.assertEqual(len(cleaned), 1)
        self.assertNotIn('do-not-print', stderr.getvalue())
        self.assertNotIn('private health details', stderr.getvalue())
        self.assertIn('exit code 78', stderr.getvalue())
        self.assertTrue(fake.find('binternet')['State']['Running'])
        self.assertFalse(any(call[0] == 'stop' for call in fake.calls))
        self.assertEqual(len(fake.containers), 2)

    def test_unavailable_logs_do_not_mask_candidate_failure_or_prevent_cleanup(self):
        fake = FakeDocker(candidate_exit=78)
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(container='binternet', backup_dir=directory, skip_upstream_check=False)

            def process(command_args, **kwargs):
                if command_args[1] == 'logs':
                    raise OSError('log driver unavailable')
                return argparse.Namespace(returncode=0, stdout='', stderr='')

            with patch.object(app, 'docker', side_effect=fake), \
                 patch.object(app.subprocess, 'run', side_effect=process):
                with self.assertRaisesRegex(app.DeployError, 'exited'):
                    app.perform(args)
            evidence = next(Path(directory).glob('*/failure-diagnostics'))
            self.assertTrue((evidence / 'container-state.json').exists())
            self.assertIn('log driver unavailable', (evidence / 'capture-error.json').read_text())
        self.assertTrue(fake.find('binternet')['State']['Running'])
        self.assertEqual(len(fake.containers), 2)

    def test_success_preserves_rollback_container_and_uses_tested_image_id(self):
        fake = FakeDocker()
        with tempfile.TemporaryDirectory() as directory:
            self.perform(fake, directory)
            state = json.loads(next(Path(directory).glob('*/deployment.json')).read_text())
            self.assertEqual(state['phase'], 'complete')
            self.assertFalse(next(Path(directory).glob('*')).joinpath('environment').exists())
        self.assertNotEqual(fake.find('binternet')['Id'], 'a' * 64)
        self.assertFalse(fake.find('a' * 64)['State']['Running'])
        self.assertEqual(fake.find('a' * 64)['HostConfig']['RestartPolicy']['Name'], 'no')
        self.assertTrue(fake.find('binternet-candidate-20260907')['State']['Running'])
        self.assertEqual([call[-1] for call in fake.calls if call[0] == 'create'], ['sha256:testedimage'] * 2)
        self.assertEqual(set(fake.find('binternet')['NetworkSettings']['Networks']), {'npm-bridge', 'extra'})

    def test_cutover_failure_restores_old_name_networks_aliases_and_running_state(self):
        fake = FakeDocker(fail_new_start=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(app.DeployError, 'Simulated'):
                self.perform(fake, directory)
            state = json.loads(next(Path(directory).glob('*/deployment.json')).read_text())
            self.assertEqual(state['phase'], 'rolled_back')
        old = fake.find('binternet')
        self.assertEqual(old['Id'], 'a' * 64)
        self.assertTrue(old['State']['Running'])
        self.assertEqual(old['HostConfig']['RestartPolicy']['Name'], 'unless-stopped')
        self.assertEqual(old['NetworkSettings']['Networks']['npm-bridge']['Aliases'], ['binternet', 'images'])
        self.assertEqual(len(fake.containers), 2)

    def test_rollback_refuses_unrelated_replacement(self):
        fake = FakeDocker()
        old = original()
        fake.containers[old['Id']]['Name'] = '/retained'
        unrelated = original()
        unrelated.update(Id='d' * 64, Name='/binternet')
        fake.containers[unrelated['Id']] = unrelated
        with patch.object(app, 'docker', side_effect=fake):
            with self.assertRaisesRegex(app.DeployError, 'another container'):
                app.restore({'original': old, 'name': 'binternet', 'run_id': 'ours'})
        self.assertFalse(any(call[0] == 'rm' for call in fake.calls))

    def test_retained_always_restart_disabled_and_manual_rollback_restores_it(self):
        fake = FakeDocker()
        fake.find('binternet')['HostConfig']['RestartPolicy'] = {'Name': 'always'}
        with tempfile.TemporaryDirectory() as directory:
            self.perform(fake, directory)
            state = json.loads(next(Path(directory).glob('*/deployment.json')).read_text())
            self.assertEqual(fake.find('a' * 64)['HostConfig']['RestartPolicy']['Name'], 'no')
            with patch.object(app, 'docker', side_effect=fake):
                app.restore(state)
        self.assertEqual(fake.find('binternet')['HostConfig']['RestartPolicy']['Name'], 'always')
        self.assertTrue(fake.find('binternet')['State']['Running'])


def search_page(images=('first.jpg',), next_href=None):
    pictures = ''.join('<img src="/image_proxy.php?' + urllib.parse.urlencode({
        'url': 'https://i.pinimg.com/originals/' + image}) + '" alt="Fixture">' for image in images)
    link = '' if next_href is None else '<a id="next-page" rel="next" href="' + html.escape(next_href, quote=True) + '">Next page</a>'
    return '<section id="image-gallery"><div class="gallery-page">' + pictures + '</div></section>' + link


def candidate_responses():
    return {
        '/health.php': (200, json.dumps({'status': 'ok', 'version': app.VERSION})),
        '/': (200, '<form action="search.php"></form>'),
        '/static/app.css': (200, '.gallery { display: grid; }' + '/* styles */' * 60),
        '/static/infinite-scroll.js': (200, '/* IntersectionObserver */' + '/* script */' * 100),
        '/search.php?q=architecture': (200, search_page(next_href='search.php?q=architecture&bookmark=opaque%2Fpage%2Btwo%3D%3D&theme=black&view=masonry&quality=auto&scroll=manual')),
        '/search.php?q=architecture&bookmark=opaque%2Fpage%2Btwo%3D%3D&theme=black&view=masonry&quality=auto&scroll=manual': (200, search_page(('second.jpg',))),
    }


class CandidateCheckTests(unittest.TestCase):
    def run_check(self, version=app.VERSION, css_status=200, css=None, overrides=None, skip_upstream=True):
        candidate = {'NetworkSettings': {'Ports': {'8080/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '49177'}]}}}
        responses = candidate_responses()
        responses['/health.php'] = (200, json.dumps({'status': 'ok', 'version': version}))
        responses['/static/app.css'] = (css_status, css if css is not None else responses['/static/app.css'][1])
        responses.update(overrides or {})
        with patch.object(app, 'inspect', return_value=candidate), \
             patch.object(app, 'request', side_effect=lambda base, path: responses[path]) as request:
            app.candidate_checks('candidate', skip_upstream=skip_upstream)
        return request.call_args_list

    def test_current_health_and_gallery_css_pass(self):
        self.run_check()

    def test_old_health_version_rejected(self):
        with self.assertRaisesRegex(app.DeployError, 'health JSON'):
            self.run_check(version='old-release')

    def test_missing_or_incomplete_gallery_css_rejected(self):
        for status, css in [(404, '.gallery{}' * 70), (200, '.gallery{}'), (200, 'body{}' * 100)]:
            with self.subTest(status=status, length=len(css)):
                with self.assertRaisesRegex(app.DeployError, 'stylesheet'):
                    self.run_check(css_status=status, css=css)

    def test_missing_or_incomplete_infinite_scroll_asset_rejected_even_when_upstream_skipped(self):
        for reply in [(404, 'IntersectionObserver' * 100), (200, 'IntersectionObserver'), (200, 'x' * 2048)]:
            with self.subTest(reply=reply[0], length=len(reply[1])):
                with self.assertRaisesRegex(app.DeployError, 'infinite-scroll script'):
                    self.run_check(overrides={'/static/infinite-scroll.js': reply})

    def test_two_pages_pass_and_propagate_opaque_bookmark_and_preferences(self):
        calls = self.run_check(skip_upstream=False)
        self.assertEqual(calls[-1].args, (
            'http://127.0.0.1:49177',
            '/search.php?q=architecture&bookmark=opaque%2Fpage%2Btwo%3D%3D&theme=black&view=masonry&quality=auto&scroll=manual'))
        self.assertEqual(len(calls), 6)

    def test_explicit_skip_only_omits_both_live_searches(self):
        calls = self.run_check(skip_upstream=True)
        self.assertEqual([call.args[1] for call in calls], [
            '/health.php', '/', '/static/app.css', '/static/infinite-scroll.js'])

    def test_missing_next_link_rejected(self):
        with self.assertRaisesRegex(app.DeployError, 'pagination.*Next page'):
            self.run_check(skip_upstream=False, overrides={
                '/search.php?q=architecture': (200, search_page())})

    def test_empty_second_page_rejected(self):
        second = next(path for path in candidate_responses() if 'bookmark=' in path)
        with self.assertRaisesRegex(app.DeployError, 'Next page did not return'):
            self.run_check(skip_upstream=False, overrides={second: (200, search_page(()))})

    def test_repeated_first_page_rejected_despite_different_proxy_query_encoding(self):
        second = next(path for path in candidate_responses() if 'bookmark=' in path)
        body = search_page().replace('https%3A%2F%2F', 'https://')
        with self.assertRaisesRegex(app.DeployError, 'repeated the first page'):
            self.run_check(skip_upstream=False, overrides={second: (200, body)})

    def test_provider_strings_outside_actual_gallery_images_do_not_pass(self):
        bodies = ['<!-- image_proxy.php?url=example -->',
                  '<a href="/image_proxy.php?url=example">image</a>',
                  search_page().replace('id="image-gallery"', 'id="not-the-gallery"'),
                  search_page().replace('i.pinimg.com', 'untrusted.example')]
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaisesRegex(app.DeployError, 'did not return gallery image'):
                    self.run_check(skip_upstream=False, overrides={
                        '/search.php?q=architecture': (200, body)})

    def test_unsafe_or_ambiguous_next_links_rejected_before_fetch(self):
        links = [
            'https://evil.example/search.php?q=architecture&bookmark=opaque',
            '//evil.example/search.php?q=architecture&bookmark=opaque',
            '/\\evil.example/search.php?q=architecture&bookmark=opaque',
            '/health.php?q=architecture&bookmark=opaque',
            '/search.php?q=architecture&bookmark=opaque#fragment',
            '/search.php?q=architecture&bookmark=',
            '/search.php?q=architecture&bookmark=-end-',
            '/search.php?q=architecture&bookmark=one&bookmark=two',
            '/search.php?q=another&bookmark=opaque',
            '/search.php?q=architecture&q=another&bookmark=opaque',
            '/search.php?q=architecture&bookmark=opaque%0Ainjected',
            '/search.php?q=architecture&bookmark=' + 'x' * 4097,
            '/search.php?q=architecture\n&bookmark=opaque',
        ]
        # The fixture mapping contains no target for any malicious link. An
        # attempted fetch therefore fails the test, even if later rejected.
        for link in links:
            with self.subTest(link=link[:100]):
                with self.assertRaisesRegex(app.DeployError, 'pagination.*Next page'):
                    self.run_check(skip_upstream=False, overrides={
                        '/search.php?q=architecture': (200, search_page(next_href=link))})

    def test_pagination_and_asset_failures_keep_production_running(self):
        second = next(path for path in candidate_responses() if 'bookmark=' in path)
        failures = [('/static/infinite-scroll.js', (404, 'missing')),
                    ('/search.php?q=architecture', (200, search_page())),
                    (second, (200, search_page())),
                    (second, (200, search_page(())))]
        for path, reply in failures:
            with self.subTest(path=path, reply=reply[0]), tempfile.TemporaryDirectory() as directory:
                fake = FakeDocker()
                responses = candidate_responses()
                responses[path] = reply
                args = argparse.Namespace(container='binternet', backup_dir=directory, skip_upstream_check=False)
                with patch.object(app, 'docker', side_effect=fake), \
                     patch.object(app.subprocess, 'run', return_value=argparse.Namespace(returncode=0, stdout='', stderr='')), \
                     patch.object(app, 'request', side_effect=lambda base, target: responses[target]):
                    with self.assertRaises(app.DeployError):
                        app.perform(args)
                self.assertEqual(fake.find('binternet')['Id'], 'a' * 64)
                self.assertTrue(fake.find('binternet')['State']['Running'])
                self.assertFalse(any(call[0] == 'stop' for call in fake.calls))
                self.assertEqual(len(fake.containers), 2)


class HTTPFailureTests(unittest.TestCase):
    def test_real_candidate_http_checks_follow_validated_second_page(self):
        routes = candidate_responses()
        calls = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                status, body = routes.get(self.path, (404, 'unexpected endpoint'))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body.encode('utf-8'))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        candidate = {'NetworkSettings': {'Ports': {'8080/tcp': [
            {'HostIp': '127.0.0.1', 'HostPort': str(server.server_port)}]}}}
        try:
            with patch.object(app, 'inspect', return_value=candidate):
                app.candidate_checks('candidate')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        self.assertEqual(calls, list(routes))

    def test_redirect_is_rejected_without_following_target(self):
        calls = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/must-not-be-fetched')
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        try:
            with self.assertRaises(app.HTTPCheckError) as caught:
                app.request('http://127.0.0.1:' + str(server.server_port), '/search.php?q=architecture')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        self.assertEqual(caught.exception.http_diagnostics['status'], 302)
        self.assertEqual(calls, ['/search.php?q=architecture'])

    def test_real_http_error_preserves_numeric_cause_without_body_cookie_or_query(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(502)
                self.send_header('X-Binternet-Upstream-Status', '403')
                self.send_header('X-Binternet-Upstream-Error', 'http_status')
                self.send_header('Set-Cookie', 'private-cookie=secret')
                self.end_headers()
                self.wfile.write(b'<html>private-provider-response</html>')

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        try:
            with self.assertRaises(app.HTTPCheckError) as caught:
                app.request('http://127.0.0.1:' + str(server.server_port), '/search.php?q=private-query')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
        failure = caught.exception
        self.assertIn('Pinterest HTTP 403', str(failure))
        self.assertEqual(failure.http_diagnostics['status'], 502)
        serialized = str(failure) + json.dumps(failure.http_diagnostics)
        for private in ('private-query', 'private-cookie', 'secret', 'private-provider-response'):
            self.assertNotIn(private, serialized)

    def test_untrusted_diagnostic_headers_are_not_reflected(self):
        failure = app.HTTPCheckError('/search.php?q=secret', 502, {
            'X-Binternet-Upstream-Status': '403 secret',
            'X-Binternet-Upstream-Error': 'secret\nforged log'})
        self.assertIsNone(failure.http_diagnostics['upstream_status'])
        self.assertIsNone(failure.http_diagnostics['upstream_error'])
        self.assertNotIn('secret', str(failure))

    def test_nginx_error_without_application_headers_is_identified(self):
        failure = app.HTTPCheckError('/health.php', 502, {})
        self.assertIn('/health.php returned HTTP 502', str(failure))
        self.assertIsNone(failure.http_diagnostics['upstream_status'])

    def test_script_error_names_fixed_asset_without_reflecting_query(self):
        failure = app.HTTPCheckError('/static/infinite-scroll.js?secret', 404, {})
        self.assertIn('/static/infinite-scroll.js returned HTTP 404', str(failure))
        self.assertNotIn('secret', str(failure))


if __name__ == '__main__':
    unittest.main()
