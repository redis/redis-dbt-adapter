#!/usr/bin/env python3
"""Validate v1 feature scenarios through a Redis-enabled native dbt executable."""
import argparse
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from smoke import require_integration_config, SmokeError, check_results, check_version


def run_parity(binary, keep_artifacts=False):
    require_integration_config()
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True)
    check_version(version.stdout + version.stderr)
    directory = Path(tempfile.mkdtemp(prefix='redis-dbt-v2-parity-'))
    project, target = directory / 'project', directory / 'target'
    shutil.copytree(Path(__file__).parent / 'parity', project)
    schema = 'dbt_v2_parity_' + uuid.uuid4().hex[:12]
    env = os.environ.copy()
    env.update(REDIS_DBT_V2_SCHEMA=schema, DBT_ALLOW_EXPERIMENTAL_ADAPTERS='yes',
               DBT_SEND_ANONYMOUS_USAGE_STATS='false', DBT_LOG_PATH=str(directory / 'logs'))
    common = ['--project-dir', str(project), '--profiles-dir', str(project), '--target-path', str(target)]
    parsed = False

    def run(*args, fails=False):
        print('Parity: dbt ' + ' '.join(args), flush=True)
        result = subprocess.run([binary, *args, *common], env=env, capture_output=fails, text=True)
        if fails:
            if result.returncode == 0 or 'null' not in (result.stdout + result.stderr).lower():
                raise SmokeError('Expected the NOT NULL contract to reject a NULL insert')
        else:
            result.check_returncode()

    def operation(name, **kwargs):
        run('run-operation', name, '--args', json.dumps(kwargs))

    def assert_query(sql, expected):
        operation('assert_query', sql=sql, expected=expected)

    def table(name):
        return f'"{schema}"."{name}"'

    try:
        run('parse')
        parsed = True
        for flags in [('--full-refresh',), ()]:
            (target / 'run_results.json').unlink(missing_ok=True)
            run('build', '--write-catalog', *flags)
            check_results(target / 'run_results.json')
            results = json.loads((target / 'run_results.json').read_text())['results']
            required = {'model.redis_dbt_v2_smoke.' + name for name in ['trips_contract', 'trips_merge', 'trips_python']}
            required.add('snapshot.redis_dbt_v2_smoke.trips_snapshot')
            if not required <= {row['unique_id'] for row in results if row['status'] == 'success'}:
                raise SmokeError('Missing successful parity model or snapshot results')
        assert_query(f'select count(*) from {table("trips_python")} where double_trips != trips * 2', 0)
        assert_query(f'select count(*) from {table("trips_python")}', 3)
        run('run-operation', 'violate_contract', fails=True)
        assert_query(f'select count(*) from {table("trips_contract")}', 3)
        operation('mutate_trips')
        run('snapshot')
        assert_query(f'select count(*) from {table("trips_snapshot")} where id=1', 2)
        assert_query(f"select count(*) from {table('trips_snapshot')} where id=2 and dbt_is_deleted='True'", 1)
        run('run', '-s', 'trips_merge')
        assert_query(f"select count(*) from {table('trips_merge')} where id=1 and zone='updated'", 1)
        assert_query(f'select count(*) from {table("trips_merge")}', 3)
        run('run', '-s', '+trips_microbatch', '--vars', '{microbatch_demo: true}', '--full-refresh',
            '--event-time-start', '2024-01-01', '--event-time-end', '2024-01-03')
        run('run', '-s', 'trips_microbatch', '--vars', '{microbatch_demo: true}',
            '--event-time-start', '2024-01-02', '--event-time-end', '2024-01-03')
        assert_query(f'select count(*) from {table("trips_microbatch")}', 2)
        assert_query(f"select count(*) from {table('trips_microbatch')} where occurred_at < cast('2024-01-02' as timestamp)", 1)
        csv_path = directory / 'sample.csv.gz'
        with gzip.open(csv_path, 'wt') as output:
            output.write('id,name\n10,a\n20,b\n30,c\n40,d\n50,e\n')
        operation('load_parity_csv', path=str(csv_path))
        assert_query(f'select count(*) from {table("csv_sample")}', 2)
        assert_query(f'select sum(file_row) from {table("csv_sample")}', 4)
        assert_query(f'select sum(id) from {table("csv_sample")}', 40)
        run('docs', 'generate', '--write-catalog')
        catalog = json.loads((target / 'catalog.json').read_text())
        if catalog.get('errors'):
            raise SmokeError('Catalog export reported errors')
        contract = catalog['nodes']['model.redis_dbt_v2_smoke.trips_contract']
        if contract['metadata']['comment'] != "Driver's persisted table description":
            raise SmokeError('Persisted table description missing from catalog')
        if contract['columns']['zone']['comment'] != "Driver's persisted zone description":
            raise SmokeError('Persisted column description missing from catalog')
        run('build', '--empty', '--exclude-resource-type', 'snapshot', '--exclude', 'assert_totals')
        assert_query(f'select count(*) from {table("trips_table")}', 0)
        print('Native v2 parity passed: Python, contracts, snapshots, merge, microbatch, CSV sampling, docs, catalog, and empty builds.', flush=True)
    finally:
        try:
            if parsed:
                run('run-operation', 'drop_smoke_schema')
        finally:
            if keep_artifacts:
                print('Parity artifacts: ' + str(directory), flush=True)
            else:
                shutil.rmtree(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dbt', required=True)
    parser.add_argument('--keep-artifacts', action='store_true')
    args = parser.parse_args()
    try:
        run_parity(args.dbt, args.keep_artifacts)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, SmokeError) as error:
        parser.exit(1, f'Native parity failed: {error}\n')


if __name__ == '__main__':
    main()
