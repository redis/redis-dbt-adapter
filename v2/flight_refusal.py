"""Deterministic native CLI and optional Arrow runtime refusal qualification.

Called with a private TLS Redis publication proxy and its owned Flight server.
Never use this fixture against a shared Redis database.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from runner import SmokeError, configure_transport


def qualify_refusals(binary, engine, env, gate, output):
    schema = 'flight_refusal_' + uuid.uuid4().hex
    receipt = {'status': 'incomplete', 'checks': {}}
    manifest = output / 'refusal.json'
    with tempfile.TemporaryDirectory(prefix='dbt-flight-refusal-') as directory:
        project = Path(directory)
        shutil.copytree(Path(__file__).with_name('smoke'), project, dirs_exist_ok=True)
        env = {**env, 'REDIS_DBT_V2_SCHEMA': schema, 'DBT_LOG_PATH': str(project / 'logs')}
        configure_transport(project, env, 'flightsql')
        (project / 'macros' / 'refusal.sql').write_text('''
{% macro refusal_setup() %}
{% do run_query('create schema "' ~ target.schema ~ '"') %}
{% do run_query('create table "' ~ target.schema ~ '".probe (id bigint)') %}
{% endmacro %}
{% macro refusal_insert() %}
{% do run_query('create temp table refusal_kept as select 42 as id') %}
{% do run_query('insert into "' ~ target.schema ~ '".probe values (1)') %}
{% set result = run_query('select count(*) from "' ~ target.schema ~ '".probe') %}
{% if result.rows[0][0] != 1 %}{{ exceptions.raise_compiler_error('Write replayed or missing') }}{% endif %}
{% set zone = run_query('show time zone') %}
{% if zone.rows[0][0] != 'America/New_York' %}{{ exceptions.raise_compiler_error('Session time zone changed') }}{% endif %}
{% set kept = run_query('select id from refusal_kept') %}
{% if kept.rows[0][0] != 42 %}{{ exceptions.raise_compiler_error('Temporary relation changed') }}{% endif %}
{% set path = run_query('show search_path') %}
{% if path.rows[0][0] != target.schema %}{{ exceptions.raise_compiler_error('Session schema changed') }}{% endif %}
{% endmacro %}
{% macro refusal_script() %}
{% do run_query('insert into "' ~ target.schema ~ '".probe values (2); insert into "' ~ target.schema ~ '".probe values (3)') %}
{% endmacro %}
{% macro refusal_assert_single() %}
{% set result = run_query('select id from "' ~ target.schema ~ '".probe') %}
{% if result.rows | length != 1 or result.rows[0][0] != 1 %}
{{ exceptions.raise_compiler_error('Refused bounded write unexpectedly committed') }}{% endif %}
{% endmacro %}
{% macro refusal_assert_prefix() %}
{% set result = run_query('select id from "' ~ target.schema ~ '".probe order by id') %}
{% if result.rows | length != 2 or result.rows[0][0] != 1 or result.rows[1][0] != 2 %}
{{ exceptions.raise_compiler_error('Committed script prefix was replayed or lost') }}{% endif %}
{% endmacro %}
{% macro refusal_cleanup() %}
{% do run_query('drop schema if exists "' ~ target.schema ~ '" cascade') %}
{% endmacro %}
''')

        def invoke(name, macro, success=True):
            result = subprocess.run([str(binary), 'run-operation', macro, '--project-dir', str(project),
                                     '--profiles-dir', str(project), '--target-path', str(project / 'target')],
                                    env=env, capture_output=True, text=True, timeout=180)
            diagnostic = result.stdout + result.stderr
            for key in ('FLIGHT_SQL_PASSWORD', 'REDIS_PASSWORD'):
                if env.get(key) and env[key] in diagnostic:
                    raise SmokeError('Credential found in refusal diagnostics')
            (output / (name + '.log')).write_text(diagnostic)
            if (result.returncode == 0) != success:
                raise SmokeError('Unexpected result for ' + name + '; inspect retained log')
            if not success and 'snapshot catalog changed concurrently; retry the statement' not in diagnostic:
                raise SmokeError('Expected actual Flight publication refusal for ' + name)

        def record(name, expected_workspaces):
            evidence = gate.receipt()
            receipt['checks'][name] = evidence
            manifest.write_text(json.dumps(receipt, indent=2) + '\n')
            if len(evidence['workspaces']) != expected_workspaces or evidence['refused_cas'] < expected_workspaces:
                raise SmokeError('Publication injection did not exercise expected attempts: ' + name)

        try:
            invoke('refusal-setup', 'refusal_setup')
            # Skip the temporary relation's successful setup publication.
            gate.arm(limit=1, skip=1)
            invoke('refusal-native-retry', 'refusal_insert')
            record('native_retry', 1)
            # Worker shutdown can also publish temporary-relation cleanup.
            # The macro's row/state assertions distinguish a write replay.
            if gate.receipt()['passed_publications'] < 1:
                raise SmokeError('Native retry must publish a fresh workspace')
            # Stop refusing after the expected bound, so an extra SQL attempt
            # would succeed and fail the CLI/error or persisted-state assertions.
            # This also lets connection teardown clean up its temporary objects.
            gate.arm(limit=20, skip=1)
            invoke('refusal-native-bound', 'refusal_insert', success=False)
            record('native_20_attempt_bound', 20)
            gate.arm(limit=0)
            invoke('refusal-native-bound-state', 'refusal_assert_single')
            # The engine splits SQL and retries only the refused statement. The
            # first statement commits once; the second exhausts its own bound.
            gate.arm(limit=20, skip=1)
            invoke('refusal-native-script', 'refusal_script', success=False)
            record('native_statement_boundary', 20)
            gate.arm(limit=0)
            invoke('refusal-native-prefix', 'refusal_assert_prefix')
            qualify_arrow(engine, env, schema, gate, receipt, manifest)
            receipt['status'] = 'passed'
        finally:
            gate.arm(limit=0)
            try:
                invoke('refusal-cleanup', 'refusal_cleanup')
                receipt['cleanup'] = 'passed'
            except BaseException:
                receipt['cleanup'] = 'failed'
                raise
            finally:
                manifest.write_text(json.dumps(receipt, indent=2) + '\n')
    print('Native Flight refusal, statement boundary and optional Arrow checks passed.')


def qualify_arrow(engine, env, schema, gate, receipt, manifest):
    # Import the actual engine runtime, rather than copying its retry algorithm.
    import adbc_driver_flightsql.dbapi as flight
    import adbc_driver_manager as adbc
    import pyarrow as pa
    spec = importlib.util.spec_from_file_location('qualified_redis_runtime',
        engine / 'crates/dbt-adapter/src/python/redis/runtime.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    options = {'username': env['FLIGHT_SQL_USERNAME'], 'password': env['FLIGHT_SQL_PASSWORD'],
               'adbc.flight.sql.client_option.tls_root_certs': Path(env['FLIGHT_SQL_TLS_CA_FILE']).read_text(),
               'adbc.flight.sql.rpc.with_cookie_middleware': 'true'}
    with flight.connect(env['FLIGHT_SQL_URI'], db_kwargs=options, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute('select 1')
            cursor.fetchall()
        table = pa.table({'id': pa.array([], type=pa.int64())})
        for name, data, limit, expected in [
            ('arrow_empty_fresh_reader', table, 1, 1),
            ('arrow_nonempty_fresh_input', pa.table({'id': [42]}), 1, 1),
            ('arrow_20_attempt_bound', table, None, 20),
            ('arrow_one_shot_no_replay', pa.table({'id': [43]}).to_reader(), None, 1),
        ]:
            gate.arm(limit=limit)
            try:
                runtime.ingest(connection, name, data, schema)
            except adbc.Error as error:
                if limit is not None:
                    raise
                if error.status_code != adbc.AdbcStatusCode.IO or error.vendor_code != 14 or '(Unavailable;' not in str(error):
                    raise SmokeError('Wrong Flight error envelope for ' + name) from None
            else:
                if limit is None:
                    raise SmokeError('Expected refusal for ' + name)
            evidence = gate.receipt()
            receipt['checks'][name] = evidence
            manifest.write_text(json.dumps(receipt, indent=2) + '\n')
            if len(evidence['workspaces']) != expected or evidence['refused_cas'] < expected:
                raise SmokeError('Wrong Arrow retry count for ' + name)
            gate.arm(limit=0)
            if limit is not None:
                with connection.cursor() as cursor:
                    cursor.execute(f'select count(*) from "{schema}"."{name}"')
                    if cursor.fetchone()[0] != data.num_rows:
                        raise SmokeError('Arrow retry changed row count for ' + name)
