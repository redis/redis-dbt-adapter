#!/usr/bin/env python3
"""Check Flight authentication and certificate rejection through the native CLI."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

from smoke import SmokeError, configure_transport, require_integration_config


def run_security(binary):
    require_integration_config()
    env = os.environ.copy()
    env.update(REDIS_DBT_V2_SCHEMA="public", DBT_ALLOW_EXPERIMENTAL_ADAPTERS="yes",
               DBT_SEND_ANONYMOUS_USAGE_STATS="false")
    with tempfile.TemporaryDirectory(prefix="dbt-v2-flight-security-") as directory:
        project = Path(directory)
        shutil.copytree(Path(__file__).with_name("smoke"), project, dirs_exist_ok=True)
        configure_transport(project, env, "flightsql")
        (project / "macros" / "flight_probe.sql").write_text(
            "{% macro flight_probe() %}"
            "{% do run_query('create temp table flight_local (id bigint)') %}"
            "{% do run_query('insert into flight_local values (1)') %}"
            "{% call statement('drain', fetch_result=False) %}"
            "select g from generate_series(1, 100000) as s(g){% endcall %}"
            "{% set result = run_query('select id from flight_local') %}"
            "{% if result.rows[0][0] != 1 %}{{ exceptions.raise_compiler_error('Invalid Flight probe') }}"
            "{% endif %}{% endmacro %}\n"
            "{% macro flight_cancel() %}{{ log('Flight cancellation probe started', info=True) }}"
            "{% do run_query('select sum(length(repeat(cast(g as varchar), 2000))) "
            "from generate_series(1, 500000) as s(g)') %}{% endmacro %}\n")
        env["DBT_LOG_PATH"] = str(project / "logs")

        def invoke(overrides, expected=None):
            result = subprocess.run(
                [binary, "run-operation", "flight_probe", "--project-dir", str(project),
                 "--profiles-dir", str(project), "--target-path", str(project / "target")],
                env={**env, **overrides}, capture_output=True, text=True, timeout=60)
            output = (result.stdout + result.stderr).lower()
            if expected is None and result.returncode and env.get("FLIGHT_QUALIFICATION_ARTIFACTS"):
                diagnostic = result.stdout + result.stderr
                for key in ("FLIGHT_SQL_PASSWORD", "REDIS_PASSWORD"):
                    if env.get(key):
                        diagnostic = diagnostic.replace(env[key], "[REDACTED]")
                (Path(env["FLIGHT_QUALIFICATION_ARTIFACTS"]) / "security-failure.log").write_text(diagnostic)
            if expected is None:
                if result.returncode:
                    raise SmokeError("Authenticated native Flight probe failed")
            elif result.returncode == 0 or not any(word in output for word in expected):
                raise SmokeError("Native Flight did not reject the expected security failure")
            # Inspect diagnostics without echoing potentially sensitive output.
            for key in ("FLIGHT_SQL_PASSWORD",):
                value = overrides.get(key, env[key])
                if value and value in result.stdout + result.stderr:
                    raise SmokeError("Flight credentials appeared in native CLI output")

        invoke({})
        invoke({"FLIGHT_SQL_PASSWORD": "deliberately-invalid-flight-password"},
               ("unauthenticated", "unauthorized", "invalid credentials", "authentication"))
        # A valid unrelated CA exercises chain verification, rather than PEM parsing.
        wrong_ca = project / "untrusted.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-subj", "/CN=unrelated-flight-test-ca",
                        "-keyout", str(project / "untrusted.key"), "-out", str(wrong_ca)],
                       check=True, capture_output=True)
        invoke({"FLIGHT_SQL_TLS_CA_FILE": str(wrong_ca)},
               ("unknown authority", "certificate verify", "certificate_unknown"))
        cancellation_log = project / "cancellation.log"
        with cancellation_log.open("w") as log:
            process = subprocess.Popen(
                [binary, "run-operation", "flight_cancel", "--project-dir", str(project),
                 "--profiles-dir", str(project), "--target-path", str(project / "cancel-target")],
                env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 15
                while "Flight cancellation probe started" not in cancellation_log.read_text():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise SmokeError("Native cancellation probe did not start")
                    time.sleep(.05)
                time.sleep(.3)
                if process.poll() is not None:
                    raise SmokeError("Cancellation query finished before interruption")
                process.send_signal(signal.SIGINT)
                process.wait(timeout=15)
                diagnostic = cancellation_log.read_text().lower()
                if process.returncode <= 0 or not any(word in diagnostic for word in ("cancelled", "canceled", "interrupted")):
                    raise SmokeError("Native Flight cancellation was not reported")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if os.environ.get("FLIGHT_QUALIFICATION_ARTIFACTS"):
                    shutil.copyfile(cancellation_log, Path(os.environ["FLIGHT_QUALIFICATION_ARTIFACTS"]) / "cancellation.log")
        invoke({})
    print("Native Flight security passed: authenticated TLS, rejected credentials, "
          "untrusted certificate, no-fetch session preservation, bounded cancellation, "
          "and subsequent recovery.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dbt", required=True)
    args = parser.parse_args()
    try:
        run_security(args.dbt)
    except (OSError, ValueError, SmokeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Native Flight security failed: {error}\n")


if __name__ == "__main__":
    main()
