"""Validate private CA and credential handoff to subsequent CI steps."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import redis_enterprise


class EnterpriseStartupTests(unittest.TestCase):
    def test_retries_unavailable_bootstrap_and_rejected_database_creation(self):
        for method, path, code in [('GET', 'bootstrap', 503), ('POST', 'bdbs', 406),
                                   ('PUT', 'cluster/certificates', 503),
                                   ('PUT', 'cluster/certificates', 403),
                                   ('PUT', 'cluster/certificates', 401)]:
            with self.subTest(method=method, code=code), \
                 patch.object(redis_enterprise.time, 'sleep'), \
                 patch.object(redis_enterprise.time, 'monotonic', return_value=0):
                check = unittest.mock.Mock(side_effect=[redis_enterprise.APIError(method, path, code), True])
                self.assertTrue(redis_enterprise.wait(check, 'startup'))
                self.assertEqual(check.call_count, 2)

    def test_does_not_retry_auth_errors_or_ambiguous_writes(self):
        for method, path, code in [('GET', 'bootstrap', 401), ('GET', 'bootstrap', 403),
                                   ('POST', 'users', 503), ('POST', 'bdbs', 400),
                                   ('POST', 'users', 403), ('PUT', 'bdbs/1', 503)]:
            with self.subTest(method=method, code=code):
                check = unittest.mock.Mock(side_effect=redis_enterprise.APIError(method, path, code))
                # A regression must fail promptly instead of exhausting the
                # real five-minute provisioning deadline in the unit suite.
                with patch.object(redis_enterprise.time, 'sleep'), \
                     patch.object(redis_enterprise.time, 'monotonic', side_effect=[0, 0, 301]), \
                     self.assertRaises(redis_enterprise.APIError):
                    redis_enterprise.wait(check, 'startup')
                check.assert_called_once()


class EnterpriseEnvironmentTests(unittest.TestCase):
    def test_ci_handoff_masks_password_and_exports_explicit_ca_without_global_trust_override(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            output = io.StringIO()
            exports = {'REDIS_URI': 'rediss://localhost:16380/0',
                       'REDIS_USERNAME': 'dbt@dbt.test', 'REDIS_PASSWORD': 'test-password',
                       'REDIS_TLS_CA_FILE': str(state / 'ca.crt')}
            with patch.object(redis_enterprise, 'STATE', state), \
                 patch.dict(os.environ, {'GITHUB_ENV': str(state / 'github-env')}), \
                 redirect_stdout(output):
                redis_enterprise.write_environment(exports, github_env=True)
            self.assertEqual(output.getvalue(), '::add-mask::test-password\n')
            actual = dict(line.split('=', 1) for line in (state / 'github-env').read_text().splitlines())
            self.assertEqual(actual, exports)
            self.assertNotIn('SSL_CERT_FILE', actual)

    def test_rejects_multiline_values_before_writing_or_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            output = io.StringIO()
            with patch.object(redis_enterprise, 'STATE', state), redirect_stdout(output):
                with self.assertRaises(ValueError):
                    redis_enterprise.write_environment({'REDIS_PASSWORD': 'secret\nINJECTED=value'}, True)
            self.assertFalse((state / 'env.sh').exists())
            self.assertEqual(output.getvalue(), '')

    def test_ci_flag_requires_github_environment_before_provisioning(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sys, 'argv', ['redis_enterprise.py', 'up', '--github-env']), \
             patch.object(redis_enterprise, 'up') as up, \
             patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:
                redis_enterprise.main()
            self.assertEqual(error.exception.code, 2)
            up.assert_not_called()


if __name__ == '__main__':
    unittest.main()
