"""The live runners must fail closed before starting database work."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke import run_smoke
from parity import run_parity
from taxi import run_taxi
from integration_config import require_integration_config


class IntegrationConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            'REDIS_URI': 'rediss://enterprise.test.invalid:6380/0',
            'REDIS_USERNAME': 'integration-user',
            'REDIS_PASSWORD': 'test-secret',
        }

    def test_requires_each_connection_setting(self):
        for name in self.env:
            for value in ['', '   ']:
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    require_integration_config({**self.env, name: value})

    def test_rejects_plaintext_bad_endpoints_and_certificate_bypasses(self):
        for uri in ['redis://host:6379/0', 'rediss:///0', 'rediss://host:bad/0',
                    'rediss://host:6380/0?skip_verify=true',
                    'rediss://host:6380/0?skip_verify=1',
                    'rediss://host:6380/0?skip_verify=',
                    'rediss://host:6380/0?skip_verify=false&skip_verify=true']:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                require_integration_config({**self.env, 'REDIS_URI': uri})

    def test_accepts_verified_tls_and_separate_credentials(self):
        require_integration_config(self.env)
        require_integration_config({**self.env, 'REDIS_URI':
                                   'rediss://wrong:wrong@enterprise.test.invalid:6380/0?skip_verify=false'})

    def test_diagnostics_do_not_expose_uri_or_credentials(self):
        with self.assertRaises(ValueError) as error:
            require_integration_config({**self.env, 'REDIS_URI': 'redis://user:private@host:6379/0'})
        for secret in ['private', self.env['REDIS_USERNAME'], self.env['REDIS_PASSWORD']]:
            self.assertNotIn(secret, str(error.exception))

    def test_live_runners_reject_missing_config_before_subprocess_or_file_work(self):
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run') as run:
            for invoke in [lambda: run_smoke('/dbt', build=True),
                           lambda: run_parity('/dbt'),
                           lambda: run_taxi('/dbt', '/nonexistent.csv')]:
                with self.assertRaisesRegex(ValueError, 'REDIS_URI'):
                    invoke()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
