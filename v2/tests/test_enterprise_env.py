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
