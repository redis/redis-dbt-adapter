"""Shared lifecycle for isolated native v2 integration projects (stdlib only)."""
from contextlib import contextmanager
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


class SmokeError(Exception):
    pass


def check_version(output):
    # Both OSS and the full distribution are usable; Python Core 1.x is not.
    if not re.search(r"\bdbt(?:-oss|-fusion)?\s+(?:version\s*[:=]?\s*)?v?2\.\d+", output, re.I):
        raise SmokeError("Expected a dbt v2 executable; pass its path with --dbt.")


def configure_transport(project, env, transport):
    if transport == "redis":
        return
    if transport != "flightsql":
        raise SmokeError("Unknown Redis transport")
    from urllib.parse import urlsplit
    required = ("FLIGHT_SQL_DRIVER", "FLIGHT_SQL_URI", "FLIGHT_SQL_USERNAME",
                "FLIGHT_SQL_PASSWORD", "FLIGHT_SQL_TLS_CA_FILE")
    if any(not env.get(key, "").strip() for key in required):
        raise SmokeError("Flight qualification requires " + ", ".join(required))
    try:
        uri = urlsplit(env["FLIGHT_SQL_URI"])
        valid = (uri.scheme == "grpc+tls" and uri.hostname and uri.port
                 and not uri.username and not uri.password and not uri.query
                 and not uri.fragment and uri.path in ("", "/"))
    except ValueError:
        valid = False
    if not valid:
        raise SmokeError("Flight qualification requires grpc+tls://host:port without URI credentials")
    for key in ("FLIGHT_SQL_DRIVER", "FLIGHT_SQL_TLS_CA_FILE"):
        path = Path(env[key])
        if not path.is_absolute() or not path.is_file():
            raise SmokeError(key + " must be an absolute existing file")
    shutil.copyfile(Path(__file__).with_name("flight_profiles.yml"), project / "profiles.yml")


class DbtProject:
    def __init__(self, binary, name, directory, live):
        self.binary = str(Path(binary).resolve()) if os.path.dirname(binary) else binary
        self.name, self.directory = name, directory
        self.project, self.target = directory / "project", directory / "target"
        self.parsed, self.variables = False, {}
        self.env = os.environ.copy()
        if not live:
            self.env.setdefault("REDIS_URI", "rediss://parse-only.invalid:6380/0")
            self.env.setdefault("REDIS_USERNAME", "parse-only")
            self.env.setdefault("REDIS_PASSWORD", "parse-only")
        self.env.update(REDIS_DBT_V2_SCHEMA="dbt_v2_" + name + "_" + uuid.uuid4().hex[:12],
                        DBT_ALLOW_EXPERIMENTAL_ADAPTERS="yes", DBT_SEND_ANONYMOUS_USAGE_STATS="false",
                        DBT_LOG_PATH=str(directory / "logs"))

    def run(self, *args, extra_vars=None, **options):
        flags = ["--project-dir", str(self.project), "--profiles-dir", str(self.project),
                 "--target-path", str(self.target)]
        if self.variables or extra_vars:
            flags += ["--vars", json.dumps({**self.variables, **(extra_vars or {})})]
        print(self.name.title() + ": dbt " + " ".join(args), flush=True)
        result = subprocess.run([self.binary, *args, *flags], cwd=self.project, env=self.env,
                                text=True, **{"check": True, **options})
        if args[0] == "parse" and result.returncode == 0:
            self.parsed = True
        return result


@contextmanager
def dbt_project(binary, name, *, live=True, keep_artifacts=False, cleanup="drop_smoke_schema"):
    if live:
        require_integration_config()
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)
    check_version(version.stdout + version.stderr)
    print(version.stdout.strip(), flush=True)
    directory = Path(tempfile.mkdtemp(prefix="redis-dbt-v2-" + name + "-"))
    session = DbtProject(binary, name, directory, live)
    try:
        yield session
    finally:
        failed = sys.exc_info()[0] is not None
        try:
            if live and session.parsed:
                try:
                    session.run("run-operation", cleanup)
                except (OSError, subprocess.SubprocessError):
                    print("Cleanup failed; remove schema " + session.env["REDIS_DBT_V2_SCHEMA"], file=sys.stderr)
                    if not failed:
                        raise
        finally:
            if keep_artifacts:
                print(name.title() + " artifacts: " + str(directory), flush=True)
            else:
                shutil.rmtree(directory)
