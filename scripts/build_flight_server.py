#!/usr/bin/env python3
"""Build a committed Flight source with the latest stable Redis ADBC release.

An explicit --driver-ref qualifies committed driver source instead.
Requires git, gh, Go, and make. The source checkout is never modified; the resolved
release, source revisions, module version, and binary digest are saved for QA.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def output(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Flight server Git checkout")
    parser.add_argument("--output", type=Path, required=True, help="destination executable")
    parser.add_argument("--driver-ref", help="explicit driver commit/tag for source qualification (default: latest stable)")
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.output.resolve()
    release = None if args.driver_ref else output("gh", "api", "repos/redis/redis-adbc-driver/releases/latest", "--jq", ".tag_name")
    driver_ref = args.driver_ref or release
    commit = output("gh", "api", f"repos/redis/redis-adbc-driver/commits/{driver_ref}", "--jq", ".sha")
    server = output("git", "rev-parse", "HEAD", cwd=source)
    with tempfile.TemporaryDirectory(prefix="dbt-flight-build-") as directory:
        build = Path(directory)
        archive = build / "source.tar"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), server],
                       cwd=source, check=True)
        with tarfile.open(archive) as files:
            files.extractall(build, filter="data")
        archive.unlink()
        subprocess.run([
            "go", "mod", "edit",
            "-replace=github.com/adbc-drivers/redis/go="
            f"github.com/redis/redis-adbc-driver/go@{commit}",
        ], cwd=build, check=True)
        subprocess.run(["go", "mod", "tidy"], cwd=build, check=True)
        subprocess.run(["make", "build", f"VERSION=dbt-{server[:12]}-adbc-{commit[:12]}"],
                       cwd=build, check=True)
        module = json.loads(output("go", "list", "-m", "-json",
                                  "github.com/adbc-drivers/redis/go", cwd=build))["Replace"]
        go_version = output("go", "version", cwd=build)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / "bin/redis-flight-server", destination)
    evidence = {
        "flight_source_commit": server,
        "redis_adbc_release": release,
        "redis_adbc_requested_ref": driver_ref,
        "redis_adbc_commit": commit,
        "redis_adbc_go_module": module["Version"],
        "go_version": go_version,
        "binary_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }
    destination.with_suffix(".json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
