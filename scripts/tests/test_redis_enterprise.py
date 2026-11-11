"""Enterprise startup retries must recover without hiding permanent API errors."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redis_enterprise as fixture


class StartupTests(unittest.TestCase):
    def test_certificate_install_retries_until_admin_credentials_propagate(self):
        check = Mock(side_effect=[
            fixture.APIError('PUT', 'cluster/certificates', 401),
            fixture.APIError('PUT', 'cluster/certificates', 503),
            True,
        ])
        with patch.object(fixture.time, 'sleep') as sleep:
            self.assertTrue(fixture.wait(check, 'management certificate installation'))
        self.assertEqual(check.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_persistent_certificate_auth_failure_times_out(self):
        check = Mock(side_effect=fixture.APIError('PUT', 'cluster/certificates', 401))
        with patch.object(fixture.time, 'monotonic', side_effect=[0, 0, 2]), \
             patch.object(fixture.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out waiting for management'):
                fixture.wait(check, 'management certificate installation', seconds=1)
        check.assert_called_once()

    def test_other_auth_and_certificate_errors_fail_immediately(self):
        for method, path, code in [
            ('GET', 'cluster', 401),
            ('POST', 'users', 401),
            ('PUT', 'cluster/certificates', 403),
            ('PUT', 'cluster/certificates', 400),
        ]:
            with self.subTest(method=method, path=path, code=code):
                error = fixture.APIError(method, path, code)
                check = Mock(side_effect=error)
                with patch.object(fixture.time, 'sleep') as sleep:
                    with self.assertRaises(fixture.APIError) as raised:
                        fixture.wait(check, 'startup')
                self.assertIs(raised.exception, error)
                check.assert_called_once()
                sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
