#!/usr/bin/env python3
"""Interrupt the taxi microbatch after DELETE; observe and recover its rows.

Run after `make all`. Only the randomly named demo schema is written/dropped.
The fault injector lives in a child process; adapter/model SQL is unchanged.
"""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


MODEL = "fct_trips_microbatch"
COLUMNS = "trip_id, pickup_datetime, pickup_date, pickup_borough, payment_type_name, total_amount"
WINDOW = "pickup_datetime >= '2019-01-01' and pickup_datetime < '2019-01-04'"


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def delete_prefix(sql, target):
    """Recognize the actual microbatch DELETE/INSERT, including dbt comments."""
    boundary = re.search(r";\s*insert\s+into\s+" + re.escape(target) + r"\s*\(", sql, re.I)
    if boundary and re.search(r"\bdelete\s+from\s+" + re.escape(target) + r"\s+as\s+DBT_INTERNAL_TARGET\b", sql[:boundary.start()], re.I):
        return sql[:boundary.start()]
    return None


def worker(project, schema, marker, recover=False):
    from adbc_driver_manager import dbapi
    from dbt.cli.main import dbtRunner

    if marker:
        execute = dbapi.Cursor.execute
        # RedisAdbcRelation's default quote policy renders these unquoted.
        target = f"{schema}.{MODEL}"

        def interrupt(cursor, operation, parameters=None):
            prefix = delete_prefix(operation, target) if isinstance(operation, str) else None
            if prefix is None:
                return execute(cursor, operation, parameters)
            execute(cursor, prefix, parameters)  # Real autocommitted DELETE.
            Path(marker).write_text("DELETE completed; INSERT has not been sent\n")
            # The parent reads the gap before terminating this process. Even if
            # it fails to terminate us, this branch can never send the INSERT.
            time.sleep(120)
            raise RuntimeError("Fault injector timed out waiting for termination")

        dbapi.Cursor.execute = interrupt

    args = ["run", "--project-dir", project, "--profiles-dir", project,
            "--vars", "{microbatch_demo: true}", "-s", MODEL if marker else "+" + MODEL,
            "--event-time-start", "2019-01-02" if marker or recover else "2019-01-01",
            "--event-time-end", "2019-01-03" if marker or recover else "2019-01-04"]
    # Recovery is restricted to the same failed day, without --full-refresh.
    result = dbtRunner().invoke(args)
    if not result.success:
        raise RuntimeError(f"dbt run failed: {result.exception}")


def verify_rows(actual, expected, stage):
    if Counter(actual) != Counter(expected):
        raise RuntimeError(f"{stage}: rows/values differ from the expected source")
    ids = [row[0] for row in actual]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{stage}: duplicate trip_id values")
    counts = Counter(str(row[2]) for row in actual)
    print(f"Reader {stage}: {dict(sorted(counts.items()))}; {len(ids)} rows, no duplicate trip_id", flush=True)


def run_demo(source_schema):
    from adbc_driver_manager import dbapi
    from dbt.adapters.redis_adbc.connections import RedisAdbcCredentials

    root = Path(__file__).resolve().parents[1]
    schema = "dbt_microbatch_failure_" + uuid.uuid4().hex[:12]
    credentials = RedisAdbcCredentials(
        database="redis", schema=schema,
        driver=os.environ.get("REDIS_ADBC_DRIVER", str(root / "driver/libadbc_driver_redis")),
        uri=os.environ.get("REDIS_URI", "redis://localhost:6380/0"),
        username=os.environ.get("REDIS_USERNAME", ""),
        password=os.environ.get("REDIS_PASSWORD", ""),
        time_zone=os.environ.get("REDIS_TIME_ZONE", ""),
    )
    source = f'{quote(source_schema)}."int_trips_enriched"'
    target = f'{quote(schema)}.{quote(MODEL)}'
    env = {**os.environ, "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    child = None
    # This connection remains open across every writer process, like an API's
    # connection pool. Each read issues a fresh query and consumes all rows.
    with tempfile.TemporaryDirectory(prefix="redis-microbatch-failure-") as directory, \
            dbapi.connect(driver=credentials.driver_path(), db_kwargs=credentials.db_kwargs(), autocommit=True) as reader:
        project = Path(directory)
        (project / "models").mkdir()
        (project / "dbt_project.yml").write_text(json.dumps({
            "name": "microbatch_failure", "version": "1.0", "config-version": 2,
            "profile": "microbatch_failure",
        }))
        profile = {key: getattr(credentials, key) for key in
                   ["database", "schema", "uri", "username", "password", "time_zone"]}
        profile.update(type="redis_adbc", driver=credentials.driver_path(), threads=1)
        profile_path = project / "profiles.yml"
        profile_path.touch(mode=0o600)
        profile_path.write_text(json.dumps({"microbatch_failure": {"target": "dev", "outputs": {"dev": profile}}}))
        shutil.copy2(root / f"models/marts/{MODEL}.sql", project / f"models/{MODEL}.sql")
        (project / "models/int_trips_enriched.sql").write_text(
            "{{ config(materialized='view', event_time='pickup_datetime') }}\n"
            f"select {COLUMNS} from {source}\n")
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", directory, "--schema", schema]

        def rows(relation):
            with reader.cursor() as cursor:
                cursor.execute(f"select {COLUMNS} from {relation} where {WINDOW} order by trip_id")
                return cursor.fetchall()

        def observe(stage, expected):
            for _ in range(3):
                verify_rows(rows(target), expected, stage)
                time.sleep(0.1)

        try:
            expected = rows(source)
            if {str(row[2]) for row in expected} != {"2019-01-01", "2019-01-02", "2019-01-03"}:
                raise RuntimeError("Source must contain trips on Jan 1–3; run make all first")
            subprocess.run(command, env=env, check=True, timeout=180)
            observe("before interruption", expected)
            missing_day = [row for row in expected if str(row[2]) != "2019-01-02"]
            marker = project / "deleted"
            with (project / "interrupted.log").open("w") as log:
                child = subprocess.Popen([*command, "--marker", str(marker)], env=env, stdout=log, stderr=log)
                deadline = time.monotonic() + 90
                last_count = None
                while not marker.exists():
                    # Keep querying while the writer prepares and runs its batch.
                    current = rows(target)
                    if len(current) != last_count:
                        print(f"Reader during refresh: {len(current)} rows", flush=True)
                        last_count = len(current)
                    if child.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("Writer did not reach the DELETE barrier:\n" + (project / "interrupted.log").read_text())
                    time.sleep(0.1)
                observe("after DELETE, writer paused", missing_day)
                child.terminate()
                child.wait(timeout=10)
                if child.returncode == 0:
                    raise RuntimeError("Interrupted writer unexpectedly succeeded")
            observe("after writer termination (no rollback)", missing_day)
            subprocess.run([*command, "--recover"], env=env, check=True, timeout=180)
            observe("after Jan 2 recovery", expected)
            subprocess.run([*command, "--recover"], env=env, check=True, timeout=180)
            observe("after second Jan 2 rerun", expected)
            print("PASS: interruption exposed a missing day; reruns restored exact rows without duplicates.", flush=True)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            with reader.cursor() as cursor:
                cursor.execute(f"drop schema if exists {quote(schema)} cascade")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-schema", default="taxi_intermediate")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--schema", help=argparse.SUPPRESS)
    parser.add_argument("--marker", help=argparse.SUPPRESS)
    parser.add_argument("--recover", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.schema, args.marker, args.recover)
    else:
        run_demo(args.source_schema)


if __name__ == "__main__":
    main()
