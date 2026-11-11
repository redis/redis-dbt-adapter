"""Tests of the runner's failure handling; these do not emulate a Redis adapter."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import smoke


def successful_results():
    nodes = smoke.REQUIRED_RESULTS | {prefix + "fixturehash" for prefix in smoke.GENERIC_TEST_PREFIXES}
    return {"results": [{"unique_id": node, "status": "success"} for node in sorted(nodes)]}


class ResultTests(unittest.TestCase):
    def test_rejects_core_v1(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.check_version("Core:\n  - installed: 1.12.5\n")

    def test_accepts_v2_distributions(self):
        for version in ["dbt-oss 2.0.5", "dbt 2.0.8", "dbt-fusion 2.0.0-preview.1"]:
            with self.subTest(version=version):
                smoke.check_version(version)

    def test_requires_all_fixture_results_and_success_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_results.json"
            for invalid in [None, {}, {"results": []}, {"results": None}]:
                with self.subTest(invalid=invalid):
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(smoke.SmokeError):
                        smoke.check_results(path)
            for status in ["fail", "error", "skipped", "warn"]:
                with self.subTest(status=status):
                    data = successful_results()
                    data["results"][0]["status"] = status
                    path.write_text(json.dumps(data))
                    with self.assertRaises(smoke.SmokeError):
                        smoke.check_results(path)
            path.write_text(json.dumps(successful_results()))
            smoke.check_results(path)

    def test_only_ephemeral_model_can_be_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_results.json"
            data = successful_results()
            data["results"].append({"unique_id": smoke.EPHEMERAL_RESULT, "status": "skipped"})
            path.write_text(json.dumps(data))
            smoke.check_results(path)
            for node in smoke.REQUIRED_RESULTS:
                with self.subTest(node=node):
                    invalid = successful_results()
                    next(result for result in invalid["results"] if result["unique_id"] == node)["status"] = "skipped"
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(smoke.SmokeError):
                        smoke.check_results(path)

    def test_cannot_silently_omit_generic_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run_results.json"
            data = successful_results()
            data["results"] = [result for result in data["results"] if "unique_trips_incremental_id" not in result["unique_id"]]
            path.write_text(json.dumps(data))
            with self.assertRaises(smoke.SmokeError):
                smoke.check_results(path)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "REDIS_URI": "rediss://enterprise.test.invalid:6380/0",
            "REDIS_USERNAME": "integration-user",
            "REDIS_PASSWORD": "unit-test-placeholder",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.calls = []
        self.envs = []
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stderr = redirect_stderr(self.output)
        self.stdout.__enter__()
        self.stderr.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def execute(self, command, **kwargs):
        self.calls.append(command)
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "dbt-oss 2.0.5\n", "")
        self.envs.append(kwargs["env"])
        if command[1] == "build":
            target = Path(command[command.index("--target-path") + 1])
            target.mkdir(exist_ok=True)
            (target / "run_results.json").write_text(json.dumps(successful_results()))
        return subprocess.CompletedProcess(command, 0)

    def test_parse_does_not_build_or_clean_up(self):
        with patch("smoke.subprocess.run", side_effect=self.execute):
            smoke.run_smoke("/test/dbt")
        self.assertEqual([c[1] for c in self.calls], ["--version", "parse"])
        self.assertIn("execution has not been tested", self.output.getvalue())

    def test_unsupported_adapter_failure_does_not_touch_database(self):
        def fail_parse(command, **kwargs):
            result = self.execute(command, **kwargs)
            if command[1] == "parse":
                raise subprocess.CalledProcessError(1, command)
            return result

        with patch("smoke.subprocess.run", side_effect=fail_parse):
            with self.assertRaises(subprocess.CalledProcessError):
                smoke.run_smoke("/test/dbt", build=True)
        self.assertEqual([c[1] for c in self.calls], ["--version", "parse"])

    def test_build_twice_in_isolated_schema_then_cleanup(self):
        with patch.dict(os.environ, {"REDIS_DBT_V2_SCHEMA": "existing_production_schema"}):
            with patch("smoke.subprocess.run", side_effect=self.execute):
                smoke.run_smoke("/test/dbt", build=True)
        self.assertEqual([c[1] for c in self.calls], ["--version", "parse", "build", "build", "run-operation"])
        self.assertIn("--full-refresh", self.calls[2])
        self.assertNotIn("--full-refresh", self.calls[3])
        self.assertEqual(self.calls[-1][2], "drop_smoke_schema")
        schemas = {env["REDIS_DBT_V2_SCHEMA"] for env in self.envs}
        self.assertEqual(len(schemas), 1)
        self.assertRegex(next(iter(schemas)), r"^dbt_v2_smoke_[0-9a-f]{12}$")
        self.assertTrue(all(env["DBT_ALLOW_EXPERIMENTAL_ADAPTERS"] == "yes" for env in self.envs))

    def test_second_build_cannot_reuse_stale_results(self):
        builds = 0

        def omit_second_results(command, **kwargs):
            nonlocal builds
            if command[1] == "build":
                builds += 1
                if builds == 2:
                    self.calls.append(command)
                    return subprocess.CompletedProcess(command, 0)
            return self.execute(command, **kwargs)

        with patch("smoke.subprocess.run", side_effect=omit_second_results):
            with self.assertRaises(smoke.SmokeError):
                smoke.run_smoke("/test/dbt", build=True)
        self.assertEqual(self.calls[-1][1:3], ["run-operation", "drop_smoke_schema"])

    def test_cleanup_failure_is_not_success(self):
        def fail_cleanup(command, **kwargs):
            result = self.execute(command, **kwargs)
            if command[1] == "run-operation":
                raise subprocess.CalledProcessError(1, command)
            return result

        with patch("smoke.subprocess.run", side_effect=fail_cleanup):
            with self.assertRaises(subprocess.CalledProcessError):
                smoke.run_smoke("/test/dbt", build=True)
        self.assertIn("Cleanup failed; remove schema dbt_v2_smoke_", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
