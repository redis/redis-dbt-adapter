"""Shared runner regressions for resource ownership and failure propagation."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner import dbt_project


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failure = self.cleanup_failure = None
        self.output = io.StringIO()
        for context in [redirect_stdout(self.output), redirect_stderr(self.output),
                        patch.dict(os.environ, REDIS_URI='rediss://fixture.invalid:6380/0',
                                   REDIS_USERNAME='test', REDIS_PASSWORD='private',
                                   REDIS_DBT_V2_SCHEMA='unowned_schema'),
                        patch('runner.subprocess.run', side_effect=self.execute)]:
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def execute(self, command, **options):
        self.calls.append((command, options))
        if command[1] == '--version':
            return subprocess.CompletedProcess(command, 0, 'dbt-oss 2.0.11', '')
        error = self.cleanup_failure if command[1] == 'run-operation' else self.failure
        if error:
            raise error
        return subprocess.CompletedProcess(command, 0)

    def test_success_uses_owned_namespace_and_cleans_up(self):
        with dbt_project('/test/dbt', 'taxi', cleanup='drop_taxi_schemas') as session:
            directory = session.directory
            session.project.mkdir()
            session.variables = {'path': '/fixture.csv'}
            session.run('parse')
            session.run('build', extra_vars={'demo': True})
            self.assertRegex(session.env['REDIS_DBT_V2_SCHEMA'], r'^dbt_v2_taxi_[0-9a-f]{12}$')
            self.assertEqual(session.env['DBT_ALLOW_EXPERIMENTAL_ADAPTERS'], 'yes')
            command, options = self.calls[-1]
            self.assertEqual(json.loads(command[command.index('--vars') + 1]),
                             {'path': '/fixture.csv', 'demo': True})
            self.assertEqual(options['cwd'], session.project)
        self.assertEqual(self.calls[-1][0][1:3], ['run-operation', 'drop_taxi_schemas'])
        self.assertFalse(directory.exists())

    def test_setup_and_parse_failures_remove_files_without_schema_cleanup(self):
        for phase in ['setup', 'parse']:
            self.calls.clear()
            error = subprocess.CalledProcessError(7, ['dbt', phase])
            self.failure = error
            with self.subTest(phase=phase), self.assertRaises(subprocess.CalledProcessError) as raised:
                with dbt_project('/test/dbt', 'parity') as session:
                    directory = session.directory
                    if phase == 'setup':
                        raise error
                    session.run('parse')
            self.assertIs(raised.exception, error)
            self.assertFalse(directory.exists())
            self.assertNotIn('run-operation', [call[0][1] for call in self.calls])

    def test_build_failure_survives_cleanup_failure(self):
        original = subprocess.CalledProcessError(7, ['dbt', 'build'])
        self.cleanup_failure = subprocess.CalledProcessError(8, ['dbt', 'cleanup'])
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            with dbt_project('/test/dbt', 'parity') as session:
                directory = session.directory
                session.run('parse')
                self.failure = original
                session.run('build')
        self.assertIs(raised.exception, original)
        self.assertEqual(self.calls[-1][0][1:3], ['run-operation', 'drop_smoke_schema'])
        self.assertIn('Cleanup failed; remove schema dbt_v2_parity_', self.output.getvalue())
        self.assertFalse(directory.exists())

    def test_retains_artifacts_after_success_or_failure(self):
        for fail in [False, True]:
            with self.subTest(fail=fail):
                try:
                    with dbt_project('/test/dbt', 'parity', keep_artifacts=True) as session:
                        directory = session.directory
                        self.addCleanup(shutil.rmtree, directory)
                        (directory / 'evidence').write_text('retained')
                        if fail:
                            raise ValueError('scenario failed')
                except ValueError:
                    self.assertTrue(fail)
                self.assertEqual((directory / 'evidence').read_text(), 'retained')
                self.assertIn('Parity artifacts: ' + str(directory), self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
