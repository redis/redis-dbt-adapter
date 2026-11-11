#!/usr/bin/env python3
"""Run the complete taxi example and demos on native v2 in isolated schemas."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from smoke import require_integration_config, SmokeError, check_version


def check_build(target, *, allow_warnings=True):
    manifest = json.loads((target / 'manifest.json').read_text())
    results = json.loads((target / 'run_results.json').read_text())['results']
    nodes = {**manifest['nodes'], **manifest.get('unit_tests', {})}
    required = {key for key, node in nodes.items()
                if node['resource_type'] in {'model', 'seed', 'snapshot', 'test', 'unit_test'}
                and node.get('config', {}).get('enabled', True)}
    seen = {row['unique_id'] for row in results}
    if required - seen:
        raise SmokeError('Taxi build omitted nodes: ' + str(sorted(required - seen)))
    for row in results:
        node = nodes.get(row['unique_id'], {})
        config = node.get('config', {})
        allowed = {'success', 'pass'}
        if allow_warnings and node.get('resource_type') == 'test' and str(config.get('severity', '')).lower() == 'warn':
            allowed.add('warn')
        if node.get('resource_type') == 'model' and config.get('materialized') == 'ephemeral':
            allowed.add('skipped')
        if row['status'] not in allowed:
            raise SmokeError(f"Taxi result failed: {row['unique_id']}={row['status']}")
    print('Verified taxi build results: ' + str(len(results)), flush=True)


def run_taxi(binary, csv_path, keep_artifacts=False):
    require_integration_config()
    check_version(subprocess.run([binary, '--version'], capture_output=True, text=True, check=True).stdout)
    csv_path = Path(csv_path).resolve(strict=True)
    directory = Path(tempfile.mkdtemp(prefix='redis-dbt-v2-taxi-'))
    project, target = directory / 'project', directory / 'target'
    source = Path(__file__).resolve().parents[1] / 'v1'
    project.mkdir()
    for name in ['models', 'seeds', 'tests', 'macros', 'analyses', 'snapshots', 'redis_adbc_utils']:
        shutil.copytree(source / name, project / name)
    for name in ['dbt_project.yml', 'packages.yml', 'package-lock.yml']:
        if (source / name).exists():
            shutil.copy2(source / name, project / name)
    profile = (Path(__file__).parent / 'smoke/profiles.yml').read_text().replace('redis_dbt_v2_smoke:', 'nyc_taxi:')
    (project / 'profiles.yml').write_text(profile)
    config = project / 'dbt_project.yml'
    config.write_text(config.read_text().replace('seeds:\n  nyc_taxi:\n', 'seeds:\n  nyc_taxi:\n    +quote_columns: true\n'))
    # Keep even the custom raw loader inside the runner's schema namespace.
    sources = project / 'models/staging/_sources.yml'
    sources.write_text(sources.read_text().replace('schema: raw', 'schema: "{{ target.schema }}_raw"'))
    loader = project / 'macros/load_raw_trips.sql'
    loader.write_text(loader.read_text().replace("schema='raw'", "schema=target.schema ~ '_raw'"))
    shutil.copy2(Path(__file__).parent / 'parity/macros/assert_parity.sql', project / 'macros/assert_parity.sql')
    (project / 'macros/drop_taxi_schemas.sql').write_text('''{% macro drop_taxi_schemas() %}
  {% if not target.schema.startswith('dbt_v2_taxi_') %}
    {{ exceptions.raise_compiler_error('Refusing cleanup outside v2 taxi namespace') }}
  {% endif %}
  {% for suffix in ['', '_raw', '_seeds', '_staging', '_intermediate', '_marts', '_snapshots'] %}
    {% do adapter.drop_schema(api.Relation.create(database=target.database, schema=target.schema ~ suffix)) %}
  {% endfor %}
{% endmacro %}
''')
    schema = 'dbt_v2_taxi_' + uuid.uuid4().hex[:12]
    env = os.environ.copy()
    env.update(REDIS_DBT_V2_SCHEMA=schema, DBT_ALLOW_EXPERIMENTAL_ADAPTERS='yes',
               DBT_SEND_ANONYMOUS_USAGE_STATS='false', DBT_LOG_PATH=str(directory / 'logs'))
    variables = {'raw_trips_path': str(csv_path)}
    common = ['--project-dir', str(project), '--profiles-dir', str(project), '--target-path', str(target)]
    parsed = False

    def run(*args, extra_vars=None):
        print('Taxi: dbt ' + ' '.join(args), flush=True)
        subprocess.run([binary, *args, '--vars', json.dumps({**variables, **(extra_vars or {})}), *common],
                       cwd=project, env=env, check=True)

    def assert_query(sql, expected):
        run('run-operation', 'assert_query', '--args', json.dumps({'sql': sql, 'expected': expected}))

    def table(suffix, name):
        return f'"{schema}_{suffix}"."{name}"'

    try:
        run('deps')
        run('parse')
        parsed = True
        run('seed', '--full-refresh')
        run('run-operation', 'load_raw_trips')
        (target / 'run_results.json').unlink(missing_ok=True)
        run('build', '--write-catalog')
        check_build(target)
        run('docs', 'generate', '--write-catalog')
        catalog = json.loads((target / 'catalog.json').read_text())
        if catalog.get('errors') or 'model.nyc_taxi.fct_trips' not in catalog['nodes']:
            raise SmokeError('Taxi catalog is incomplete')
        run('run', '-s', '+agg_zone_daily', '--full-refresh', extra_vars={'trips_end': '2019-01-16 00:00:00'})
        run('run', '-s', '+agg_zone_daily')
        assert_query(f'select (select count(*) from {table("marts", "fct_trips")}) - (select sum(trips) from {table("marts", "agg_zone_daily")})', 0)
        run('snapshot')
        run('run-operation', 'rename_zone', '--args', '{location_id: 132, name: "JFK International Airport"}')
        run('snapshot')
        assert_query(f'select count(*) from {table("snapshots", "zones_snapshot")} where "LocationID"=132', 2)
        run('seed')
        run('run', '-s', 'fct_trips_microbatch', '--full-refresh', '--event-time-start', '2019-01-01', '--event-time-end', '2019-01-04', extra_vars={'microbatch_demo': True})
        run('run', '-s', 'fct_trips_microbatch', '--event-time-start', '2019-01-02', '--event-time-end', '2019-01-03', extra_vars={'microbatch_demo': True})
        assert_query(f'select count(distinct pickup_date) from {table("marts", "fct_trips_microbatch")}', 3)
        assert_query(f"select (select count(*) from {table('marts','fct_trips_microbatch')} where pickup_date=cast('2019-01-02' as date)) - (select count(*) from {table('staging','stg_yellow_trips')} where pickup_date=cast('2019-01-02' as date))", 0)
        run('build', '--empty', '--exclude-resource-type', 'snapshot')
        # Snapshot is intentionally outside the empty build selection.
        results = json.loads((target / 'run_results.json').read_text())['results']
        if any(row['status'] not in {'success', 'pass'} for row in results):
            raise SmokeError('Taxi empty build contained unsuccessful results')
        print('Full native taxi project, packages, Python, incremental/snapshot/microbatch demos, docs, and empty build passed.', flush=True)
    finally:
        try:
            if parsed:
                run('run-operation', 'drop_taxi_schemas')
        finally:
            if keep_artifacts:
                print('Taxi artifacts: ' + str(directory), flush=True)
            else:
                shutil.rmtree(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbt', required=True)
    parser.add_argument('--csv', required=True, help='Existing yellow_tripdata_2019-01.csv.gz')
    parser.add_argument('--keep-artifacts', action='store_true')
    args = parser.parse_args()
    try:
        run_taxi(str(Path(args.dbt).resolve()), args.csv, args.keep_artifacts)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, SmokeError) as error:
        parser.exit(1, f'Native taxi validation failed: {error}\n')


if __name__ == '__main__':
    main()
