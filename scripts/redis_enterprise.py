#!/usr/bin/env python3
"""Create an isolated, local Redis Enterprise cluster for dbt integration tests."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.redis-enterprise'
CONTAINER = 'redis-dbt-enterprise'
IMAGE = 'redislabs/redis:8.2.0-78.18'
LABEL = 'redis-dbt-adapter.enterprise-fixture'
DB_PORT, API_PORT = 16380, 19444


def command(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


class APIError(RuntimeError):
    def __init__(self, method, path, code):
        super().__init__(f'Enterprise API {method} {path}: HTTP {code}')
        self.method, self.path, self.code = method, path, code


def wait(check, description, seconds=300):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except APIError as error:
            transient_read = error.method == 'GET' and error.code in {502, 503, 504}
            rejected_creation = (error.method == 'POST' and error.path == 'bdbs'
                                 and error.code in {406, 409})
            certificate_startup = (error.method == 'PUT' and error.path == 'cluster/certificates'
                                   # Bootstrap can complete before the generated admin
                                   # credentials and admin role reach the API workers.
                                   and error.code in {401, 403, 502, 503, 504})
            if not (transient_read or rejected_creation or certificate_startup):
                raise
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise RuntimeError('Timed out waiting for ' + description)


class API:
    def __init__(self, credentials, verified=True):
        self.credentials = credentials
        self.context = (ssl.create_default_context(cafile=str(STATE / 'ca.crt'))
                        if verified else ssl._create_unverified_context())

    def call(self, method, path, body=None):
        auth = base64.b64encode((self.credentials['admin_user'] + ':' +
                                 self.credentials['admin_password']).encode()).decode()
        req = urllib.request.Request(f'https://localhost:{API_PORT}/v1/{path}', method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=15) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise APIError(method, path, code) from None


def certificates():
    if (STATE / 'server.crt').exists():
        return
    quiet = {'stderr': subprocess.DEVNULL}
    command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '30',
            '-subj', '/CN=dbt Enterprise test CA', '-addext', 'basicConstraints=critical,CA:TRUE',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-keyout', str(STATE / 'ca.key'), '-out', str(STATE / 'ca.crt'), **quiet)
    command('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost',
            '-keyout', str(STATE / 'server.key'), '-out', str(STATE / 'server.csr'), **quiet)
    (STATE / 'server.ext').write_text('subjectAltName=DNS:localhost,IP:127.0.0.1\n'
        'extendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\n'
        'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n')
    command('openssl', 'x509', '-req', '-days', '30', '-in', str(STATE / 'server.csr'),
            '-CA', str(STATE / 'ca.crt'), '-CAkey', str(STATE / 'ca.key'), '-CAcreateserial',
            '-extfile', str(STATE / 'server.ext'), '-out', str(STATE / 'server.crt'), **quiet)


class Redis:
    def __init__(self, verified=True, tls=True):
        sock = socket.create_connection(('127.0.0.1', DB_PORT), timeout=5)
        try:
            if tls:
                ctx = (ssl.create_default_context(cafile=str(STATE / 'ca.crt'))
                       if verified else ssl.create_default_context())
                sock = ctx.wrap_socket(sock, server_hostname='localhost')
            self.sock = sock
            self.stream = sock.makefile('rb')
        except BaseException:
            sock.close()
            raise

    def call(self, *args):
        parts = [str(arg).encode() for arg in args]
        self.sock.sendall(b'*' + str(len(parts)).encode() + b'\r\n' + b''.join(
            b'$' + str(len(p)).encode() + b'\r\n' + p + b'\r\n' for p in parts))
        return self.read()

    def read(self):
        line = self.stream.readline()
        if not line:
            raise ConnectionError('Redis closed the connection')
        kind, value = line[:1], line[1:-2]
        if kind == b'-':
            raise RuntimeError(value.decode())
        if kind == b'+':
            return value.decode()
        if kind == b':':
            return int(value)
        if kind == b'$':
            length = int(value)
            if length == -1:
                return None
            result = self.stream.read(length)
            self.stream.read(2)
            return result.decode()
        if kind == b'*':
            return [self.read() for _ in range(int(value))]
        raise RuntimeError('Unexpected Redis reply')

    def close(self):
        self.stream.close()
        self.sock.close()


def verify(credentials, api):
    databases = api.call('GET', 'bdbs')
    if len(databases) != 1 or databases[0]['name'] != 'dbt-integration':
        raise RuntimeError('Expected the dedicated dbt Enterprise database')
    database = databases[0]
    database.update(api.call('GET', f"bdbs/{database['uid']}?fields=search"))
    qpf = database.get('query_performance_factor', {})
    if not (database['tls_mode'] == 'enabled' and database['shards_count'] == 3
            and database['status'] == 'active'
            and qpf.get('active') is True and qpf.get('scaling_factor') == 4
            and database.get('search', {}).get('search-workers') == 6
            and database.get('sched_policy') == 'mnp' and database.get('conns') == 32):
        raise RuntimeError('Enterprise database configuration differs from the fixture')
    client = Redis()
    try:
        try:
            client.call('PING')
        except RuntimeError as error:
            if 'NOAUTH' not in str(error):
                raise
        else:
            raise RuntimeError('Unauthenticated connection was accepted')
        try:
            client.call('AUTH', credentials['username'], 'incorrect-password')
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Incorrect password was accepted')
        client.call('AUTH', credentials['username'], credentials['password'])
        assert client.call('PING') == 'PONG'
        client.call('FT._LIST')
        key = 'dbt_env_probe:' + uuid.uuid4().hex
        try:
            assert client.call('HSET', key, 'value', 'verified') == 1
            assert client.call('HGET', key, 'value') == 'verified'
        finally:
            client.call('DEL', key)
    finally:
        client.close()
    try:
        untrusted = Redis(verified=False)
    except ssl.SSLCertVerificationError:
        pass
    else:
        untrusted.close()
        raise RuntimeError('An untrusted certificate was accepted')
    plain = Redis(tls=False)
    try:
        try:
            plain.call('PING')
        except (OSError, ConnectionError):
            pass
        else:
            raise RuntimeError('Plaintext Redis was accepted')
    finally:
        plain.close()
    print('Verified Enterprise: 3 shards, QPF 4x, Search, trusted TLS, named-user auth, write/read/delete.')
    print('Verified rejection of plaintext, untrusted CA, missing auth, and incorrect password.')


def write_environment(exports, github_env=False):
    if any('\n' in value or '\r' in value for value in exports.values()):
        raise ValueError('Connection environment values must be single-line')
    (STATE / 'env.sh').write_text(''.join(
        f'export {key}={shlex.quote(value)}\n' for key, value in exports.items()))
    if github_env:
        print('::add-mask::' + exports['REDIS_PASSWORD'], flush=True)
        with open(os.environ['GITHUB_ENV'], 'a') as output:
            for key, value in exports.items():
                print(f'{key}={value}', file=output)


def up(github_env=False):
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    credential_file = STATE / 'credentials.json'
    if not credential_file.exists():
        credential_file.write_text(json.dumps({'admin_user': 'admin@dbt.test',
            'admin_password': secrets.token_urlsafe(32), 'username': 'dbt@dbt.test',
            'password': secrets.token_urlsafe(32)}))
    credentials = json.loads(credential_file.read_text())
    certificates()
    existing = subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True, text=True)
    if existing.returncode == 0:
        container = json.loads(existing.stdout)[0]
        if container['Config'].get('Labels', {}).get(LABEL) != str(ROOT):
            raise RuntimeError('Container name belongs to another environment')
        command('docker', 'start', CONTAINER)
    else:
        command('docker', 'run', '-d', '--name', CONTAINER, '--label', LABEL + '=' + str(ROOT),
                '--cap-add', 'SYS_RESOURCE', '-p', f'127.0.0.1:{DB_PORT}:12000',
                '-p', f'127.0.0.1:{API_PORT}:9443', IMAGE)
    print('Waiting for dedicated Enterprise cluster...', flush=True)
    # Only the owned, loopback bootstrap endpoint uses its initial self-signed cert.
    bootstrap_api = API(credentials, verified=(STATE / 'verified-api').exists())
    requested = False
    def bootstrapped():
        nonlocal requested
        state = bootstrap_api.call('GET', 'bootstrap')['bootstrap_status']['state']
        if state == 'failed':
            raise RuntimeError('Enterprise bootstrap failed')
        if state == 'idle' and not requested:
            bootstrap_api.call('POST', 'bootstrap/create_cluster', {
                'action': 'create_cluster', 'cluster': {'name': 'dbt-test.local'}, 'node': {},
                'credentials': {'username': credentials['admin_user'],
                                'password': credentials['admin_password']}})
            requested = True
        return state == 'completed'
    wait(bootstrapped, 'Enterprise bootstrap')
    def install_certificates():
        # Reapplying the same certificates is idempotent while the API starts.
        bootstrap_api.call('PUT', 'cluster/certificates', {'certificates': [
            {'name': name, 'certificate': (STATE / 'server.crt').read_text(),
             'key': (STATE / 'server.key').read_text()} for name in ['api', 'proxy']]})
        return True
    wait(install_certificates, 'management certificate installation')
    api = API(credentials)
    wait(lambda: api.call('GET', 'cluster'), 'verified management TLS')
    (STATE / 'verified-api').touch()
    def ensure(path, match, body):
        found = next((item for item in api.call('GET', path) if match(item)), None)
        return found if found else api.call('POST', path, body)
    role = ensure('roles', lambda r: r['name'] == 'dbt-integration',
                  {'name': 'dbt-integration', 'management': 'none'})
    acl = ensure('redis_acls', lambda a: a['name'] == 'dbt-integration',
                 {'name': 'dbt-integration', 'acl': '+@all ~* &*'})
    ensure('users', lambda u: u['email'] == credentials['username'],
        {'email': credentials['username'], 'name': 'dbt integration',
         'password': credentials['password'], 'role_uids': [role['uid']]})
    body = {'name': 'dbt-integration', 'type': 'redis', 'redis_version': '8.6',
        # Full refresh temporarily keeps both the old table and its replacement.
        'port': 12000, 'memory_size': 2147483648, 'replication': False,
        'data_persistence': 'disabled', 'eviction_policy': 'noeviction',
        'shards_count': 3, 'sharding': True, 'shards_placement': 'dense',
        'shard_key_regex': [{'regex': '.*\\{(?<tag>.*)\\}.*'}, {'regex': '(?<tag>.*)'}],
        'query_performance_factor': {'active': True, 'scaling_factor': 4},
        'tls_mode': 'enabled', 'enforce_client_authentication': 'disabled',
        'authentication_redis_pass': secrets.token_urlsafe(32),
        'roles_permissions': [{'role_uid': role['uid'], 'redis_acl_uid': acl['uid']}]}
    database = wait(lambda: ensure('bdbs', lambda b: b['name'] == 'dbt-integration', body),
                    'database creation acceptance')
    uid = database['uid']
    wait(lambda: api.call('GET', f'bdbs/{uid}')['status'] == 'active', 'Enterprise database')
    wait(lambda: len([s for s in api.call('GET', f'bdbs/{uid}/shards')
                       if s['role'] == 'master' and s['status'] == 'active']) == 3, 'three primary shards')
    wait(lambda: api.call('GET', f'bdbs/{uid}?fields=search')
         .get('search', {}).get('search-workers') == 6, 'effective QPF 4x workers')
    exports = {'REDIS_URI': f'rediss://localhost:{DB_PORT}/0',
               'REDIS_USERNAME': credentials['username'], 'REDIS_PASSWORD': credentials['password'],
               'REDIS_TLS_CA_FILE': str(STATE / 'ca.crt')}
    extension = '.dylib' if sys.platform == 'darwin' else '.so'
    driver = ROOT / 'v1' / 'driver' / ('libadbc_driver_redis' + extension)
    exports['REDIS_ADBC_DRIVER'] = str(driver)
    verify(credentials, api)
    write_environment(exports, github_env)
    print('Connection environment: source ' + str(STATE / 'env.sh'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'verify'])
    parser.add_argument('--github-env', action='store_true',
                        help='Mask generated credentials and export verified settings to GITHUB_ENV')
    args = parser.parse_args()
    if args.github_env and (args.action != 'up' or not os.environ.get('GITHUB_ENV')):
        parser.error('--github-env requires up and the GITHUB_ENV environment variable')
    try:
        if args.action == 'up':
            up(args.github_env)
        else:
            credentials = json.loads((STATE / 'credentials.json').read_text())
            verify(credentials, API(credentials))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
