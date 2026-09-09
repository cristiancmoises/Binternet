#!/usr/bin/env python3
"""Local Docker upgrade: candidate first, private snapshots, retained-container rollback."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '2026.09.08.4'
IMAGE = 'binternet-securityops:' + VERSION
ROOT = Path(__file__).resolve().parent.parent
OWNER = 'io.securityops.binternet.deployment'
TMPFS = {
    '/tmp': 'rw,noexec,nosuid,size=268435456,mode=1777',
    '/run': 'rw,noexec,nosuid,size=8388608,mode=1777',
    '/var/cache/nginx': 'rw,noexec,nosuid,size=16777216,mode=1777',
}


class DeployError(RuntimeError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics


class HTTPCheckError(DeployError):
    """Only fixed endpoint names, numeric status and allowlisted reasons escape."""
    def __init__(self, path, status, headers):
        endpoint = path.split('?', 1)[0]
        if endpoint not in ('/health.php', '/', '/static/app.css', '/static/infinite-scroll.js', '/search.php'):
            endpoint = '[candidate endpoint]'
        upstream = headers.get('X-Binternet-Upstream-Status', '')
        upstream = int(upstream) if re.fullmatch(r'[1-5][0-9]{2}', upstream) else None
        reason = headers.get('X-Binternet-Upstream-Error', '')
        reason = reason if reason in ('dns', 'dns_blocked', 'curl', 'http_status', 'empty_body') else None
        message = 'Candidate ' + endpoint + ' returned HTTP ' + str(status)
        details = []
        if upstream:
            details.append('Pinterest HTTP ' + str(upstream))
        if reason:
            details.append(reason)
        if details:
            message += ' (' + '; '.join(details) + ')'
        super().__init__(message + '. Candidate validation failed; cutover has not started.')
        self.http_diagnostics = {'endpoint': endpoint, 'status': status,
                                 'upstream_status': upstream, 'upstream_error': reason}


def docker(*args, check=True):
    # Do not echo commands or inspect output: either can contain credentials.
    proc = subprocess.run(['docker', *map(str, args)], capture_output=True, text=True)
    if check and proc.returncode:
        raise DeployError('Docker ' + str(args[0]) + ' failed (exit ' + str(proc.returncode) + ').',
                          {'operation': str(args[0]), 'exit_code': proc.returncode,
                           'stdout': proc.stdout, 'stderr': proc.stderr})
    return proc.stdout.strip() if proc.returncode == 0 else None


def inspect(name):
    return json.loads(docker('inspect', name))[0]


def maybe_inspect(name):
    raw = docker('inspect', name, check=False)
    return json.loads(raw)[0] if raw else None


def private_json(path, value):
    with open(path, 'w', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n')


def private_text(path, value):
    with open(path, 'w', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(value)


def capture_failure(backup, state, name, failure):
    """Keep sensitive runtime evidence before cleanup or rollback removes it."""
    evidence = backup / 'failure-diagnostics'
    evidence.mkdir(mode=0o700, exist_ok=True)
    os.chmod(evidence, 0o700)
    report = {'phase': state['phase'], 'container': name, 'error': str(failure)}
    if isinstance(failure, HTTPCheckError):
        report['http_error'] = failure.http_diagnostics
    if isinstance(failure, DeployError) and failure.diagnostics:
        report['docker_error'] = failure.diagnostics
    private_json(evidence / 'failure.json', report)
    print('Private failure diagnostics: ' + str(evidence), file=sys.stderr, flush=True)
    try:
        found = maybe_inspect(name)
        if not found or (found['Config'].get('Labels') or {}).get(OWNER) != state['run_id']:
            return
        private_json(evidence / 'container-inspect.json', found)
        runtime = found['State']
        private_json(evidence / 'container-state.json', runtime)
        # Only structured status is printed. Logs, inspect and daemon errors can
        # contain credentials and must stay in the root-only diagnostic folder.
        status = 'running' if runtime.get('Running') else 'stopped'
        code = runtime.get('ExitCode')
        if isinstance(code, int):
            status += '; exit code ' + str(code)
        status += '; OOM killed ' + ('yes' if runtime.get('OOMKilled') else 'no')
        health = (runtime.get('Health') or {}).get('Status')
        if health in ('starting', 'healthy', 'unhealthy'):
            status += '; health ' + health
        print('Failed container status: ' + status + '.', file=sys.stderr, flush=True)
        logs = subprocess.run(['docker', 'logs', '--timestamps', '--tail', '200', found['Id']],
                              capture_output=True, text=True, timeout=15)
        private_text(evidence / 'container.log', logs.stdout + logs.stderr)
        private_json(evidence / 'log-capture.json', {'exit_code': logs.returncode})
    except Exception as error:
        # Log-driver failures must not hide the deployment failure or prevent
        # restoration. Preserve any partial evidence for manual diagnosis.
        private_json(evidence / 'capture-error.json', {'error': str(error)})
        print('Some diagnostics could not be collected; see the private diagnostics folder.',
              file=sys.stderr, flush=True)


def validate(old):
    host = old['HostConfig']
    if not old['State']['Running']:
        raise DeployError('The existing binternet container must be running before an upgrade.')
    if old.get('Mounts') or host.get('Binds') or host.get('Mounts') or host.get('VolumesFrom'):
        raise DeployError('Custom mounts/volumes detected. Map and migrate them explicitly before using this updater; nothing was stopped.')
    if host.get('NetworkMode') in ('host', 'none') or str(host.get('NetworkMode', '')).startswith('container:'):
        raise DeployError('Custom network mode requires an explicit migration; nothing was stopped.')
    for field in ('Privileged', 'CapAdd', 'Devices', 'DeviceRequests', 'Links', 'Sysctls', 'AutoRemove'):
        if host.get(field):
            raise DeployError('Unsupported Docker setting ' + field + '; review it before migration. Nothing was stopped.')
    if host.get('PidMode') or host.get('IpcMode') not in (None, '', 'private'):
        raise DeployError('Shared PID/IPC namespaces require an explicit migration; nothing was stopped.')
    networks = old['NetworkSettings']['Networks']
    if not networks:
        raise DeployError('No attached Docker network found.')
    for endpoint in networks.values():
        ipam = endpoint.get('IPAMConfig') or {}
        if any(ipam.values()):
            raise DeployError('Static container IP configuration detected. Review NPM/upstream migration before upgrading; nothing was stopped.')
    for key, bindings in (host.get('PortBindings') or {}).items():
        if key != '8080/tcp' or not bindings:
            raise DeployError('Only published TCP container port 8080 is supported; nothing was stopped.')
        if any(not binding.get('HostPort') for binding in bindings):
            raise DeployError('An original published port was dynamically assigned; explicitly configure it first. Nothing was stopped.')
    for entry in old['Config'].get('Env') or []:
        if '\n' in entry or '\r' in entry or '\x00' in entry:
            raise DeployError('Multiline environment values require an explicit migration; nothing was stopped.')
        key = entry.split('=', 1)[0]
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise DeployError('An environment key cannot be represented safely by an env file.')
        if key == 'BINTERNET_CACHE_DIR' and not entry.startswith('BINTERNET_CACHE_DIR=/tmp/'):
            raise DeployError('The custom cache path is outside /tmp. Review its migration first; nothing was stopped.')


def network_aliases(old, network):
    aliases = old['NetworkSettings']['Networks'][network].get('Aliases') or []
    return list(dict.fromkeys(a for a in aliases if a and a not in (old['Id'], old['Id'][:12])))


def restart_policy(old):
    policy = old['HostConfig'].get('RestartPolicy') or {}
    restart = policy.get('Name') or 'no'
    if restart == 'on-failure' and policy.get('MaximumRetryCount'):
        restart += ':' + str(policy['MaximumRetryCount'])
    return restart


def create_args(old, name, image, env_file, run_id, candidate=False):
    host = old['HostConfig']
    networks = list(old['NetworkSettings']['Networks'])
    args = ['create', '--name', name, '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '128',
            '--env-file', str(env_file), '--label', OWNER + '=' + run_id]
    for mount, options in TMPFS.items():
        args += ['--tmpfs', mount + ':' + options]
    memory = host.get('Memory') or 1610612736
    args += ['--memory', str(memory)]
    for key, flag in [('MemorySwap', '--memory-swap'), ('NanoCpus', '--cpus'), ('CpuShares', '--cpu-shares'),
                      ('CpuPeriod', '--cpu-period'), ('CpuQuota', '--cpu-quota'), ('CpusetCpus', '--cpuset-cpus')]:
        value = host.get(key)
        if value:
            args += [flag, str(value / 1e9 if key == 'NanoCpus' else value)]
    args += ['--restart', 'no' if candidate else restart_policy(old)]
    log = host.get('LogConfig') or {}
    driver = log.get('Type') or 'json-file'
    args += ['--log-driver', driver]
    options = dict(log.get('Config') or {})
    if driver == 'json-file':
        options.setdefault('max-size', '10m')
        options.setdefault('max-file', '3')
    for key, value in options.items():
        args += ['--log-opt', key + '=' + value]
    for key, flag in [('Dns', '--dns'), ('DnsSearch', '--dns-search'), ('DnsOptions', '--dns-option'), ('ExtraHosts', '--add-host')]:
        for value in host.get(key) or []:
            args += [flag, value]
    # Compose ownership is intentionally not transferred to a manually managed replacement.
    for key, value in ({} if candidate else old['Config'].get('Labels') or {}).items():
        if not key.startswith('com.docker.compose.') and key != OWNER:
            args += ['--label', key + '=' + str(value)]
    args += ['--network', networks[0]]
    if not candidate and networks[0] != 'bridge':
        for alias in network_aliases(old, networks[0]):
            args += ['--network-alias', alias]
    if candidate:
        args += ['--publish', '127.0.0.1::8080']
    else:
        for port, bindings in (host.get('PortBindings') or {}).items():
            for binding in bindings:
                addr, number = binding.get('HostIp') or '', binding.get('HostPort') or ''
                if not number:
                    raise DeployError('An original published port was dynamically assigned; explicitly configure it first.')
                addr = '[' + addr + ']' if ':' in addr else addr
                args += ['--publish', (addr + ':' if addr else '') + number + ':' + port]
    args += [image]
    return args


def connect_network(container, old, network, candidate=False):
    args = ['network', 'connect']
    if not candidate and network != 'bridge':
        for alias in network_aliases(old, network):
            args += ['--alias', alias]
    docker(*args, network, container)


def create(old, name, image, env_file, run_id, candidate=False):
    ident = docker(*create_args(old, name, image, env_file, run_id, candidate))
    for network in list(old['NetworkSettings']['Networks'])[1:]:
        connect_network(ident, old, network, candidate)
    docker('start', ident)
    return ident


def healthy(container, timeout=75):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = inspect(container)['State']
        if not state.get('Running'):
            raise DeployError('The replacement container exited before its health check passed.')
        status = (state.get('Health') or {}).get('Status')
        if status == 'healthy':
            return
        if status == 'unhealthy':
            raise DeployError('The replacement container failed its health check.')
        time.sleep(2)
    raise DeployError('The replacement container did not become healthy within 75 seconds.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Checks must remain on the selected loopback container. A broken or
        # unexpected redirect must not turn deployment into an arbitrary fetch.
        return None


def request(base, path):
    req = urllib.request.Request(base + path, headers={'User-Agent': 'Binternet-deployment-check/' + VERSION})
    # Host proxy variables must not divert mandatory loopback checks.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        reply = opener.open(req, timeout=30)
    except urllib.error.HTTPError as error:
        # Never persist an HTML error body, cookies, full URLs or query terms.
        try:
            raise HTTPCheckError(path, error.code, error.headers) from None
        finally:
            error.close()
    with reply:
        return reply.status, reply.read(4 * 1024 * 1024).decode('utf-8', errors='replace')


class SearchPage(HTMLParser):
    """Read rendered gallery images and the progressive-enhancement next link."""
    VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                      'link', 'meta', 'param', 'source', 'track', 'wbr'))

    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.images = set()
        self.next_links = []
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        in_gallery = (self.stack[-1][1] if self.stack else False) or attrs.get('id') == 'image-gallery'
        # Duplicate attributes have differing browser/parser interpretations.
        unambiguous = len(attrs) == len(pairs)
        if tag == 'a' and attrs.get('id') == 'next-page' and unambiguous:
            if 'next' in (attrs.get('rel') or '').lower().split():
                self.next_links.append(attrs.get('href') or '')
        if tag == 'img' and in_gallery and unambiguous:
            source = attrs.get('src') or ''
            if not re.search(r'[\x00-\x20\x7f\\]', source):
                try:
                    parsed = urllib.parse.urlsplit(source)
                    query = urllib.parse.parse_qs(parsed.query, max_num_fields=8)
                    if (not parsed.scheme and not parsed.netloc and not parsed.fragment
                            and parsed.path in ('image_proxy.php', '/image_proxy.php')
                            and len(query.get('url', [])) == 1):
                        provider = urllib.parse.urlsplit(query['url'][0])
                        if (provider.scheme == 'https' and provider.hostname == 'i.pinimg.com'
                                and provider.port in (None, 443) and not provider.username
                                and not provider.password and provider.path and not provider.fragment
                                and not re.search(r'[\x00-\x20\x7f\\]', query['url'][0])):
                            # Compare decoded provider URLs, so query order and
                            # escaping cannot make a repeated first page pass.
                            self.images.add(query['url'][0])
                except ValueError:
                    pass
        if tag not in self.VOID:
            self.stack.append((tag, in_gallery))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def next_search_path(page):
    failure = 'Candidate pagination is missing a valid Next page link. Production was not replaced.'
    if len(page.next_links) != 1:
        raise DeployError(failure)
    href = page.next_links[0]
    if len(href) > 16384 or re.search(r'[\x00-\x20\x7f\\]', href):
        raise DeployError(failure)
    try:
        parsed = urllib.parse.urlsplit(href)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
        bookmark = query.get('bookmark', [])
        if (parsed.scheme or parsed.netloc or parsed.fragment
                or parsed.path not in ('search.php', '/search.php')
                or query.get('q') != ['architecture'] or len(bookmark) != 1
                or not bookmark[0] or bookmark[0] == '-end-' or len(bookmark[0].encode('utf-8')) > 4096
                or re.search(r'[\x00-\x1f\x7f]', bookmark[0])):
            raise ValueError('invalid pagination target')
    except (ValueError, UnicodeError):
        raise DeployError(failure) from None
    return '/search.php?' + parsed.query


def candidate_checks(container, skip_upstream=False):
    ports = inspect(container)['NetworkSettings']['Ports']['8080/tcp']
    port = next(p['HostPort'] for p in ports if p['HostIp'] == '127.0.0.1')
    base = 'http://127.0.0.1:' + port
    status, body = request(base, '/health.php')
    health = json.loads(body)
    if status != 200 or health.get('status') != 'ok' or health.get('version') != VERSION:
        raise DeployError('Candidate health JSON is invalid.')
    _, body = request(base, '/')
    if '<form' not in body or 'search.php' not in body:
        raise DeployError('Candidate home page is missing the search form.')
    status, stylesheet = request(base, '/static/app.css')
    if status != 200 or len(stylesheet) < 512 or '.gallery' not in stylesheet:
        raise DeployError('Candidate gallery stylesheet is missing or incomplete.')
    status, script = request(base, '/static/infinite-scroll.js')
    if status != 200 or len(script) < 1024 or 'IntersectionObserver' not in script:
        raise DeployError('Candidate infinite-scroll script is missing or incomplete.')
    if not skip_upstream:
        status, body = request(base, '/search.php?q=architecture')
        first = SearchPage(body)
        if status != 200 or not first.images:
            raise DeployError('Pinterest did not return gallery image results in the candidate. Production was not replaced.')
        status, body = request(base, next_search_path(first))
        second = SearchPage(body)
        if status != 200 or not second.images:
            raise DeployError('Candidate Next page did not return gallery image results. Production was not replaced.')
        if not second.images.difference(first.images):
            raise DeployError('Candidate Next page repeated the first page without new images. Production was not replaced.')
    print('Candidate checks passed (loopback port ' + port + ').', flush=True)


def remove_owned(name, run_id):
    found = maybe_inspect(name)
    if found and found['Config'].get('Labels', {}).get(OWNER) == run_id:
        docker('rm', '-f', found['Id'])


def restore(state):
    old = state['original']
    # Confirm that the retained original still exists before removing anything.
    saved = inspect(old['Id'])
    current = maybe_inspect(state['name'])
    if current and current['Id'] != old['Id']:
        if (current['Config'].get('Labels') or {}).get(OWNER) != state['run_id']:
            raise DeployError('Rollback stopped: another container now owns the production name.')
        docker('rm', '-f', current['Id'])
    for network in old['NetworkSettings']['Networks']:
        if network not in saved['NetworkSettings']['Networks']:
            connect_network(old['Id'], old, network)
    if saved['Name'].lstrip('/') != state['name']:
        docker('rename', old['Id'], state['name'])
    docker('update', '--restart', restart_policy(old), old['Id'])
    docker('start', old['Id'])
    if not inspect(old['Id'])['State']['Running']:
        raise DeployError('The retained original container could not be restarted.')
    if (old['State'].get('Health') or {}).get('Status') == 'healthy':
        healthy(old['Id'])
    print('Original container restored: ' + state['name'], flush=True)


def perform(args):
    old = inspect(args.container)
    validate(old)
    run_id = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + secrets.token_hex(3)
    backup = Path(args.backup_dir).resolve() / run_id
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    state_file = backup / 'deployment.json'
    state = {'name': args.container, 'run_id': run_id, 'original': old, 'image': IMAGE,
             'backup_name': args.container + '-rollback-' + run_id, 'phase': 'prepared'}
    private_json(state_file, state)
    env_file = backup / 'environment'
    with open(env_file, 'w', encoding='utf-8') as stream:
        os.chmod(env_file, 0o600)
        stream.write('\n'.join(old['Config'].get('Env') or []) + '\n')
    shutil.copy2(Path(__file__), backup / 'upgrade.py')
    os.chmod(backup / 'upgrade.py', 0o700)
    candidate = args.container + '-check-' + run_id
    cutover = False
    try:
        print('Building ' + IMAGE + '; production remains running.', flush=True)
        build = subprocess.run(['docker', 'build', '--pull', '-t', IMAGE, str(ROOT)])
        if build.returncode:
            raise DeployError('Image build failed. Production was not stopped.')
        tested_image = docker('image', 'inspect', '--format', '{{.Id}}', IMAGE)
        state['tested_image'] = tested_image
        private_json(state_file, state)
        create(old, candidate, tested_image, env_file, run_id, candidate=True)
        healthy(candidate)
        candidate_checks(candidate, args.skip_upstream_check)
        remove_owned(candidate, run_id)
        # Recheck identity and state immediately before cutover.
        if inspect(args.container)['Id'] != old['Id']:
            raise DeployError('Production changed during the build; nothing was stopped.')
        cutover = True
        state['phase'] = 'cutover'
        private_json(state_file, state)
        docker('stop', '--time', '20', old['Id'])
        # Retained rollback containers must not restart and reclaim ports after
        # a daemon/host reboot. Their original policy is restored on rollback.
        docker('update', '--restart', 'no', old['Id'])
        docker('rename', old['Id'], state['backup_name'])
        # A stopped container retaining aliases can shadow NPM DNS resolution.
        for network in old['NetworkSettings']['Networks']:
            if network != 'bridge':
                docker('network', 'disconnect', network, old['Id'])
        state['new_id'] = create(old, args.container, tested_image, env_file, run_id)
        private_json(state_file, state)
        healthy(state['new_id'])
        state['phase'] = 'complete'
        private_json(state_file, state)
        print('Upgrade complete: ' + args.container + ' uses ' + IMAGE, flush=True)
        print('Rollback: python3 ' + str(backup / 'upgrade.py') + ' rollback ' + str(state_file), flush=True)
    except BaseException as failure:
        try:
            capture_failure(backup, state, args.container if cutover else candidate, failure)
        except Exception:
            print('Could not save failure diagnostics in ' + str(backup) + '.', file=sys.stderr, flush=True)
        if cutover:
            print('Cutover failed; restoring the retained original container.', file=sys.stderr, flush=True)
            try:
                restore(state)
                state['phase'] = 'rolled_back'
                private_json(state_file, state)
            except Exception as failure:
                print('Automatic restoration needs attention: ' + str(failure), file=sys.stderr)
                print('Recovery snapshot: ' + str(state_file), file=sys.stderr)
        raise
    finally:
        with contextlib.suppress(Exception):
            remove_owned(candidate, run_id)
        # Docker has copied the environment; the private inspect snapshot retains recovery data.
        env_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    upgrade = sub.add_parser('upgrade')
    upgrade.add_argument('--container', default='binternet')
    upgrade.add_argument('--backup-dir', default='/opt/binternet-backups')
    upgrade.add_argument('--skip-upstream-check', action='store_true', help='Skip live Pinterest search and pagination checks; local health, home, CSS and JavaScript checks still apply.')
    rollback = sub.add_parser('rollback')
    rollback.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run this deployment on the VPS as root.')
    if not shutil.which('docker'):
        parser.error('Docker is required; install Docker before using this deployment.')
    os.umask(0o077)
    # One lock covers upgrades and rollbacks, including interrupted SSH sessions.
    with open('/run/lock/binternet-upgrade.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another Binternet upgrade/rollback is running.')
        def interrupted(_signum, _frame):
            raise DeployError('Deployment interrupted.')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        try:
            if args.action == 'rollback':
                with open(args.snapshot, encoding='utf-8') as source:
                    restore(json.load(source))
            else:
                perform(args)
        except (DeployError, OSError, ValueError, KeyError, KeyboardInterrupt) as error:
            print('ERROR: ' + str(error), file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
