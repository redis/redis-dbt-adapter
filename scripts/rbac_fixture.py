"""Owned, reversible Software SELECT ACL provisioning for native dbt tests.

Requires the existing dedicated Enterprise fixture or explicit management/TLS
settings. Never use production endpoints. No credentials are printed.
"""
import base64
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import tarfile
import tempfile
import urllib.request
import urllib.error
import time
import uuid

class PrivateConfig(dict):
    def __repr__(self):
        return '<private fixture settings>'

ROOT = Path(__file__).resolve().parents[1]


def driver_cli():
    configured = os.environ.get('REDIS_ADBC_CLI')
    if configured:
        return configured
    import platform
    version = subprocess.check_output(['bash', str(ROOT / 'v1/scripts/resolve_driver_version.sh')], text=True).strip()
    target = ROOT / 'v1' / 'driver' / ('redis-adbc-' + version)
    if target.exists():
        return str(target)
    system = {'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64'}[platform.machine()]
    name = f'redis-adbc-{version}-{system}-{arch}.tar.gz'
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(['gh', 'release', 'download', version, '--repo', 'redis/redis-adbc-driver',
                        '--pattern', name, '--pattern', name + '.sha256', '--dir', directory], check=True,
                       stdout=subprocess.DEVNULL)
        archive = Path(directory) / name
        expected = (Path(directory) / (name + '.sha256')).read_text().split()[0]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Driver CLI checksum mismatch')
        with tarfile.open(archive) as package:
            matches = [m for m in package.getmembers() if m.isfile() and Path(m.name).name == 'redis-adbc']
            if len(matches) != 1:
                raise RuntimeError('Driver CLI archive must contain one executable')
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(package.extractfile(matches[0]).read())
            target.chmod(0o755)
    return str(target)


def management():
    state = ROOT / '.redis-enterprise'
    if os.environ.get('REDIS_RBAC_API_URL'):
        api = os.environ['REDIS_RBAC_API_URL'].rstrip('/')
        user, password = os.environ['REDIS_RBAC_API_USERNAME'], os.environ['REDIS_RBAC_API_PASSWORD']
        ca = os.environ['REDIS_RBAC_API_CA_FILE']
    else:
        credentials = json.loads((state / 'credentials.json').read_text())
        api, user, password, ca = ('https://localhost:19444', credentials['admin_user'],
                                   credentials['admin_password'], str(state / 'ca.crt'))
    if not api.startswith('https://'):
        raise ValueError('RBAC fixture requires verified management TLS')
    context = ssl.create_default_context(cafile=ca)
    auth = base64.b64encode((user + ':' + password).encode()).decode()
    def call(method, path, body=None):
        req = urllib.request.Request(api + '/v1/' + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'})
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(req, context=context, timeout=15) as response:
                    data = response.read()
                    return json.loads(data) if data else None
            except urllib.error.HTTPError as error:
                code = error.code
                error.close()
                if method == 'DELETE' and code == 404:
                    return None
                # Software applies role bindings asynchronously. A confirmed
                # dependency conflict can be retried; never replay POSTs or
                # unknown transport outcomes.
                if method == 'DELETE' and code == 409 and time.monotonic() < deadline:
                    time.sleep(.2)
                    continue
                raise
    return call, PrivateConfig(api_url=api, username=user, password=password, ca_file=ca)


def verify_software(call):
    databases = call('GET', 'bdbs')
    if len(databases) != 1:
        raise RuntimeError('RBAC fixture requires a dedicated single-database test cluster')
    db = call('GET', f"bdbs/{databases[0]['uid']}")
    db.update(call('GET', f"bdbs/{db['uid']}?fields=search"))
    if not (db['status'] == 'active' and db['tls_mode'] == 'enabled'
            and db['eviction_policy'] == 'noeviction'
            and db['query_performance_factor'] == {'active': True, 'scaling_factor': 4}
            and db['search']['search-workers'] == 6 and db['sched_policy'] == 'mnp' and db['conns'] == 32):
        raise RuntimeError('RBAC fixture requires active verified Software with 4x QPF')
    return db


def update_role_bindings(call, database_uid, change):
    deadline = time.monotonic() + 30
    while True:
        current = call('GET', f"bdbs/{database_uid}")['roles_permissions']
        try:
            call('PUT', f"bdbs/{database_uid}", {'roles_permissions': change(current)})
            return
        except urllib.error.HTTPError as error:
            if error.code != 409 or time.monotonic() >= deadline:
                raise
            # Confirmed refusal: re-read rather than restore a stale list.
            time.sleep(.2)


@contextmanager
def provision():
    call, management_config = management()
    db = verify_software(call)
    readers, bindings = [], {}
    def unbind(role):
        update_role_bindings(call, db['uid'], lambda current: [p for p in current if p['role_uid'] != role])
    with ExitStack() as cleanup:
        for _ in range(2):
            name = 'dbt_select_' + uuid.uuid4().hex[:12]
            role = call('POST', 'roles', {'name': name, 'management': 'none'})
            cleanup.callback(call, 'DELETE', f"roles/{role['uid']}")
            domain = f"adbc-select-db{db['uid']}-role{role['uid']}"
            policy = json.loads(subprocess.check_output([driver_cli(), 'reader-acl', '-domain', domain]))
            acl = call('POST', 'redis_acls', {'name': domain, 'acl': policy['acl']})
            cleanup.callback(call, 'DELETE', f"redis_acls/{acl['uid']}")
            # Register compensation before a request whose response may be lost.
            cleanup.callback(unbind, role['uid'])
            update_role_bindings(call, db['uid'], lambda current: current + [{'role_uid': role['uid'], 'redis_acl_uid': acl['uid']}])
            secret = secrets.token_urlsafe(24)
            email = name + '@example.com'
            reader = call('POST', 'users', {'name': name, 'email': email, 'password': secret, 'role_uids': [role['uid']]})
            cleanup.callback(call, 'DELETE', f"users/{reader['uid']}")
            readers.append(PrivateConfig(username=email, password=secret))
            bindings[name] = {'role_uid': role['uid'], 'acl_uid': acl['uid']}
        yield PrivateConfig(**management_config, database_uid=db['uid'], roles=bindings), readers

