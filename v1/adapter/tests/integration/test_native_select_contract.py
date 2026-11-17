"""Five scoped replacements for the blanket general-grants exclusions.

Run serially against the dedicated Enterprise fixture. Management configuration
comes from scripts/redis_enterprise.py or explicit REDIS_RBAC_API_* settings.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import adbc_driver_manager.dbapi as dbapi
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
from rbac_fixture import provision


@pytest.fixture(scope='module')
def roles():
    if not os.environ.get('REDIS_RBAC_API_URL') and not (ROOT / '.redis-enterprise/credentials.json').exists():
        if os.environ.get('REDIS_REQUIRE_RBAC_TESTS') == '1':
            pytest.fail('Required Enterprise management fixture is missing')
        pytest.skip('requires the dedicated verified Enterprise management fixture')
    with provision() as provisioned:
        yield provisioned


def setup_project(path, config):
    schema = 'dbt_grants_' + uuid4().hex[:12]
    for name in ('models', 'seeds', 'snapshots'):
        (path / name).mkdir()
    (path / 'dbt_project.yml').write_text("name: grant_contract\nversion: '1.0'\nconfig-version: 2\nprofile: grant_contract\n")
    (path / 'profiles.yml').write_text('''grant_contract:
  target: test
  outputs:
    test:
      type: redis_adbc
      driver: "{{ env_var('REDIS_ADBC_DRIVER') }}"
      uri: "{{ env_var('REDIS_URI') }}"
      username: "{{ env_var('REDIS_USERNAME') }}"
      password: "{{ env_var('REDIS_PASSWORD') }}"
      schema: SCHEMA
      database: redis
      threads: 1
      driver_options:
        adbc.redis.tls_ca_file: "{{ env_var('REDIS_TLS_CA_FILE') }}"
        adbc.redis.rbac: "{{ env_var('DBT_ENV_SECRET_REDIS_RBAC') }}"
'''.replace('SCHEMA', schema))
    (path / 'seeds/input.csv').write_text('id,value\n1,one\n2,two\n')
    return schema


def connect(reader=None):
    kw = {'uri': os.environ['REDIS_URI'], 'adbc.redis.tls_ca_file': os.environ['REDIS_TLS_CA_FILE']}
    kw.update(reader or {'username': os.environ['REDIS_USERNAME'], 'password': os.environ['REDIS_PASSWORD']})
    return dbapi.connect(driver=os.environ['REDIS_ADBC_DRIVER'], db_kwargs=kw, autocommit=True)


def run(path, config, *args, success=True):
    env = {**os.environ, 'DBT_ENV_SECRET_REDIS_RBAC': json.dumps(config),
           'DBT_SEND_ANONYMOUS_USAGE_STATS': 'false', 'DBT_PARTIAL_PARSE': 'false'}
    result = subprocess.run([str(Path(sys.executable).parent/'dbt'), *args,
                             '--project-dir', str(path), '--profiles-dir', str(path)],
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    assert (result.returncode == 0) == success, result.stdout
    return result.stdout


def access(reader, schema, allowed):
    deadline = time.monotonic() + 30
    while True:
        try:
            with connect(reader) as conn, conn.cursor() as cursor:
                cursor.execute(f'select id from {schema}.allowed order by id')
                rows = cursor.fetchall()
            if allowed:
                assert rows == [(1,), (2,)]
                return
        except dbapi.Error as error:
            if not allowed and 'NOPERM' in str(error):
                return
            if time.monotonic() >= deadline:
                raise
        assert time.monotonic() < deadline, 'SELECT access did not converge to the expected grant'
        time.sleep(.1)


@pytest.mark.parametrize('kind', ['table', 'seed', 'incremental', 'snapshot'])
def test_select_grant_revoke_and_replacement(tmp_path, roles, kind):
    config, readers = roles
    names = list(config['roles'])
    schema = setup_project(tmp_path, config)
    def write(grantees):
        grants = {'select': grantees}
        if kind == 'seed':
            (tmp_path/'seeds/allowed.csv').write_text('id,value\n1,one\n2,two\n')
            (tmp_path/'dbt_project.yml').write_text("name: grant_contract\nversion: '1.0'\nconfig-version: 2\nprofile: grant_contract\n"
                + 'seeds:\n  grant_contract:\n    allowed:\n      +grants: ' + repr(grants) + '\n')
        elif kind == 'snapshot':
            (tmp_path/'snapshots/allowed.sql').write_text("{% snapshot allowed %}\n{{ config(strategy='check', unique_key='id', check_cols=['value'], grants="
                + repr(grants) + ") }}\nselect * from {{ ref('input') }}\n{% endsnapshot %}")
        else:
            (tmp_path/'models/allowed.sql').write_text("{{ config(materialized='"+kind+"', unique_key='id', incremental_strategy='merge', grants="
                + repr(grants)+") }}\nselect * from {{ ref('input') }}")
    if kind == 'table':
        (tmp_path/'models/schema.yml').write_text("version: 2\nmodels:\n  - name: allowed\n    columns:\n      - name: id\n        data_tests: [unique, not_null]\n")
    command = 'seed' if kind == 'seed' else ('snapshot' if kind == 'snapshot' else 'run')
    try:
        run(tmp_path, config, 'seed')
        write([names[0]])
        run(tmp_path, config, command)
        access(readers[0], schema, True)
        access(readers[1], schema, False)
        if kind == 'table':
            run(tmp_path, config, 'build')
            run(tmp_path, config, 'docs', 'generate')
            catalog = json.loads((tmp_path/'target/catalog.json').read_text())
            table = next(node for node in catalog['nodes'].values() if node['metadata']['name'] == 'allowed')
            assert table['metadata']['type'] == 'BASE TABLE'
            assert list(table['columns']) == ['id', 'value']
        run(tmp_path, config, command)
        write([names[1]])
        run(tmp_path, config, command)
        access(readers[0], schema, False)
        access(readers[1], schema, True)
        if kind != 'snapshot':
            run(tmp_path, config, command, '--full-refresh')
            access(readers[1], schema, True)
        write([])
        run(tmp_path, config, command)
        access(readers[1], schema, False)
    finally:
        with connect() as conn, conn.cursor() as cursor:
            cursor.execute(f'drop schema if exists {schema} cascade')


def test_invalid_privileges_roles_and_view_grants(tmp_path, roles):
    config, readers = roles
    schema = setup_project(tmp_path, config)
    try:
        for kind, grants, expected in (
            ('table', {'insert': [next(iter(config['roles']))]}, 'only SELECT'),
            ('table', {'select': ['unprovisioned_role']}, 'binding'),
            ('view', {'select': [next(iter(config['roles']))]}, 'base table'),
        ):
            (tmp_path/'models/invalid.sql').write_text("{{ config(materialized='"+kind+"', grants="+repr(grants)+") }}\nselect 1 as id")
            output = run(tmp_path, config, 'run', success=False)
            assert expected.lower() in output.lower()
    finally:
        with connect() as conn, conn.cursor() as cursor:
            cursor.execute(f'drop schema if exists {schema} cascade')
