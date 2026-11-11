#!/usr/bin/env python3
"""Exercise a compiled Redis dbt v2 adapter without installing the v1 adapter.

Parse by default. --build writes only to a randomly named smoke-test schema,
builds twice to exercise incremental replacement, and drops that schema afterward.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from integration_config import require_integration_config


PROJECT = "redis_dbt_v2_smoke"
REQUIRED_RESULTS = {
    f"seed.{PROJECT}.trips",
    f"model.{PROJECT}.trips_table",
    f"model.{PROJECT}.zone_totals",
    f"model.{PROJECT}.trips_incremental",
    f"test.{PROJECT}.assert_totals",
}
EPHEMERAL_RESULT = f"model.{PROJECT}.trips_input"
GENERIC_TEST_PREFIXES = {
    f"test.{PROJECT}.{test}_{model}_id."
    for test in ("not_null", "unique")
    for model in ("trips_table", "trips_incremental")
}


class SmokeError(Exception):
    pass


def check_version(output):
    # Both OSS and the full distribution are usable; Python Core 1.x is not.
    if not re.search(r"\bdbt(?:-oss|-fusion)?\s+(?:version\s*[:=]?\s*)?v?2\.\d+", output, re.I):
        raise SmokeError("Expected a dbt v2 executable; pass its path with --dbt.")


def check_results(path):
    try:
        results = json.loads(path.read_text())["results"]
        seen = {result["unique_id"] for result in results}
        # v2 writes its ephemeral no-op as "skipped". Every executable node
        # still needs a successful result, including the ephemeral's consumers.
        failed = [
            result["unique_id"] for result in results
            if result["status"] not in {"success", "pass"}
            and not (result["unique_id"] == EPHEMERAL_RESULT and result["status"] == "skipped")
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SmokeError(f"Missing or invalid build results: {path}") from exc
    missing = REQUIRED_RESULTS - seen
    # Generic-test IDs include a generated hash. Require each test by prefix.
    missing.update(prefix + "*" for prefix in GENERIC_TEST_PREFIXES if not any(node.startswith(prefix) for node in seen))
    if missing or failed:
        raise SmokeError(f"Incomplete build: missing={sorted(missing)}, unsuccessful={failed}")


def run_smoke(binary, *, build=False):
    if build:
        require_integration_config()
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)
    check_version(version.stdout + version.stderr)
    print(version.stdout.strip(), flush=True)

    env = os.environ.copy()
    if not build:
        # Profile rendering still needs values; parse never opens a connection.
        env.setdefault("REDIS_URI", "rediss://parse-only.invalid:6380/0")
        env.setdefault("REDIS_USERNAME", "parse-only")
        env.setdefault("REDIS_PASSWORD", "parse-only")
    # Never accept an externally supplied schema: cleanup must only drop ours.
    env["REDIS_DBT_V2_SCHEMA"] = "dbt_v2_smoke_" + uuid.uuid4().hex[:12]
    env["DBT_ALLOW_EXPERIMENTAL_ADAPTERS"] = "yes"
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"

    with tempfile.TemporaryDirectory(prefix="redis-dbt-v2-") as directory:
        project = Path(directory) / "project"
        shutil.copytree(Path(__file__).parent / "smoke", project)
        # Keep all artifacts and logs outside the v1 project.
        env["DBT_LOG_PATH"] = str(Path(directory) / "logs")
        target = Path(directory) / "target"
        common = ["--project-dir", str(project), "--profiles-dir", str(project), "--target-path", str(target)]

        def invoke(*args):
            print("Running dbt " + " ".join(args), flush=True)
            subprocess.run([binary, *args, *common], env=env, check=True)

        # Do not attempt any warehouse work or cleanup if profile loading fails.
        invoke("parse")
        if not build:
            print("Parse passed. Redis execution has not been tested; use --build to test it.")
            return

        print("Using isolated schema " + env["REDIS_DBT_V2_SCHEMA"], flush=True)
        build_error = None
        try:
            for args in [("build", "--full-refresh"), ("build",)]:
                # Never accept stale results from the previous invocation.
                results_path = target / "run_results.json"
                results_path.unlink(missing_ok=True)
                invoke(*args)
                check_results(results_path)
        except (OSError, subprocess.CalledProcessError, SmokeError) as exc:
            build_error = exc
            raise
        finally:
            try:
                invoke("run-operation", "drop_smoke_schema")
            except (OSError, subprocess.CalledProcessError):
                print("Cleanup failed; remove schema " + env["REDIS_DBT_V2_SCHEMA"], file=sys.stderr)
                if build_error is None:
                    raise
        print("Redis v2 smoke builds and cleanup passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dbt", required=True, help="Path or command name of the compiled dbt v2 executable")
    parser.add_argument("--build", action="store_true", help="Connect to Redis, build twice, and clean up")
    args = parser.parse_args()
    binary = shutil.which(os.path.expanduser(args.dbt))
    if binary is None:
        parser.error(f"Executable not found: {args.dbt}")
    try:
        run_smoke(binary, build=args.build)
    except (OSError, ValueError, SmokeError, subprocess.CalledProcessError) as exc:
        print(f"Redis v2 smoke check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
