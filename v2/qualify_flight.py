#!/usr/bin/env python3
"""Rebuild a Flight server and qualify the native v2 adapter over authenticated TLS.

Default: latest stable Redis ADBC release. --driver-ref main tests latest source.
Each run has a fresh output directory and records resolved identities on failure too.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import time

from smoke import SmokeError, require_integration_config
from publication_proxy import PublicationProxy
from flight_refusal import qualify_refusals
from flight_cancellation import qualify_cancellation


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qualify(args):
    require_integration_config()
    for key in ("FLIGHT_SQL_USERNAME", "FLIGHT_SQL_PASSWORD", "FLIGHT_SQL_TLS_CA_FILE"):
        if not os.environ.get(key):
            raise ValueError("Set separate Flight client credentials and TLS trust: " + key)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "tmp").mkdir()
    os.chmod(output, 0o700)
    binary = Path(args.dbt).resolve()
    engine = args.engine_source.resolve()
    client = os.environ.get("FLIGHT_SQL_DRIVER")
    if not client:
        import adbc_driver_flightsql
        client = adbc_driver_flightsql._driver_path()
    client = str(Path(client).resolve())
    env = {**os.environ, "FLIGHT_SQL_DRIVER": client, "REDIS_ADBC_DRIVER": client,
           "REDIS_ADBC_TRANSPORT": "flightsql", "TMPDIR": str(output / "tmp"),
           "FLIGHT_QUALIFICATION_ARTIFACTS": str(output),
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "false", "DBT_ALLOW_EXPERIMENTAL_ADAPTERS": "yes"}
    evidence = {
        "status": "incomplete", "platform": platform.platform(), "python": sys.version,
        "engine_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=engine, text=True).strip(),
        "engine_patch_sha256": digest(ROOT / "v2/engine/flight-sql.patch"),
        "dbt_version": subprocess.check_output([str(binary), "--version"], text=True).strip(),
        "dbt_sha256": digest(binary), "flight_client_sha256": digest(client), "checks": {},
    }
    patch = ROOT / "v2/engine/flight-sql.patch"
    sources = json.loads((ROOT / "v2/upstream.json").read_text())
    if evidence["engine_commit"] == sources["implementation_commit"]:
        if subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=engine):
            raise ValueError("Pinned engine must have no tracked source changes")
        evidence["engine_source_state"] = "merged-pinned"
    elif evidence["engine_commit"] == sources["flight_patch_base_commit"]:
        evidence["engine_source_state"] = "historical-base-with-patch"
    else:
        raise ValueError("Engine HEAD must match the merged pin or historical patch base")
    subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                   cwd=engine, check=True, capture_output=True)
    paths = re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(), re.M)
    evidence["engine_source_files"] = {path: digest(engine / path) for path in paths}
    evidence["cargo_lock_sha256"] = digest(engine / "Cargo.lock")
    evidence["rustc"] = subprocess.check_output(["rustc", "--version"], cwd=engine, text=True).strip()
    evidence["integration_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    runner_paths = [*sorted((ROOT / "v2").glob("*.py")), ROOT / "v2/flight_profiles.yml",
                    ROOT / "v2/upstream.json", ROOT / "scripts/build_flight_server.py"]
    evidence["runner_source_files"] = {str(p.relative_to(ROOT)): digest(p) for p in runner_paths}
    for path in [*runner_paths, patch]:
        snapshot = output / "source" / path.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(path.read_bytes())
    (output / "Cargo.lock").write_bytes((engine / "Cargo.lock").read_bytes())
    if args.backend_evidence:
        evidence["backend"] = json.loads(args.backend_evidence.read_text())
    for package in ("adbc-driver-flightsql", "adbc-driver-manager", "pyarrow"):
        evidence[package] = importlib.metadata.version(package)
    manifest = output / "qualification.json"

    def run(name, command, *, cwd=ROOT, timeout=900):
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        evidence["checks"][name] = "passed" if result.returncode == 0 else "failed"
        manifest.write_text(json.dumps(evidence, indent=2) + "\n")
        result.check_returncode()

    server = None
    proxy = None
    try:
        command = [sys.executable, str(ROOT / "scripts/build_flight_server.py"),
                   "--source", str(args.server_source.resolve()), "--output", str(output / "flight-server")]
        if args.driver_ref:
            command += ["--driver-ref", args.driver_ref]
        run("server-build", command)
        evidence["server"] = json.loads((output / "flight-server.json").read_text())
        proxy = PublicationProxy(env["REDIS_URI"], env["REDIS_TLS_CA_FILE"],
                                 str(args.tls_cert.resolve()), str(args.tls_key.resolve()))
        proxy.__enter__()
        env["REDIS_URI"] = proxy.uri
        env["REDIS_TLS_CA_FILE"] = env["FLIGHT_SQL_TLS_CA_FILE"]
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        env["FLIGHT_SQL_URI"] = f"grpc+tls://127.0.0.1:{port}"
        with (output / "server.log").open("w") as server_log:
            server = subprocess.Popen([
                str(output / "flight-server"), "--listen", f"127.0.0.1:{port}",
                "--auth", "redis-acl", "--tls-cert", str(args.tls_cert.resolve()),
                "--tls-key", str(args.tls_key.resolve()), "--sessions=true",
                "--adbc-option", "adbc.redis.tls_ca_file=" + env["REDIS_TLS_CA_FILE"],
            ], env=env, stdout=server_log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Flight server exited during startup; inspect server.log")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Flight server startup timed out")
            for name, script, extra in [
                ("security", "flight_security.py", []),
                ("smoke", "smoke.py", ["--build", "--transport", "flightsql"]),
                ("parity-python-csv", "parity.py", ["--keep-artifacts", "--transport", "flightsql"]),
            ]:
                run(name, [sys.executable, str(ROOT / "v2" / script), "--dbt", str(binary), *extra])
            run("rust-protocol", ["cargo", "test", "-p", "dbt-adapter-engine", "--test", "redis_adbc",
                                  "--", "--ignored", "--nocapture"], cwd=engine)
            try:
                qualify_refusals(binary, engine, env, proxy.gate, output)
                if proxy.errors:
                    raise RuntimeError("Publication proxy encountered protocol errors: " + str(proxy.errors))
            except BaseException:
                evidence["checks"]["refusal"] = "failed"
                raise
            evidence["checks"]["refusal"] = "passed"
            try:
                qualify_cancellation(env, output)
            except BaseException:
                evidence["checks"]["session-cancellation"] = "failed"
                raise
            evidence["checks"]["session-cancellation"] = "passed"
        evidence["status"] = "passed"
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if proxy is not None:
            proxy.__exit__(None, None, None)
        evidence["logs"] = {p.name: digest(p) for p in sorted(output.glob("*.log"))}
        manifest.write_text(json.dumps(evidence, indent=2) + "\n")
        print("Flight qualification evidence: " + str(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dbt", required=True)
    parser.add_argument("--engine-source", required=True, type=Path)
    parser.add_argument("--server-source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--tls-cert", required=True, type=Path)
    parser.add_argument("--tls-key", required=True, type=Path)
    parser.add_argument("--driver-ref", help="Explicit driver source ref; omit for latest stable release")
    parser.add_argument("--backend-evidence", type=Path, help="Non-secret verified Redis topology and version JSON")
    args = parser.parse_args()
    try:
        qualify(args)
    except (OSError, ValueError, RuntimeError, SmokeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Flight qualification failed: {error}\n")


if __name__ == "__main__":
    main()
