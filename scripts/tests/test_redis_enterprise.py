"""Enterprise startup retries must recover without hiding permanent API errors."""
from pathlib import Path
import ssl
import sys
import urllib.error
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redis_enterprise as fixture


class StartupTests(unittest.TestCase):
    def test_stale_verified_marker_fails_without_retry_or_tls_fallback(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                failure = ssl.SSLCertVerificationError(1, 'untrusted certificate')
                if wrapped:
                    failure = urllib.error.URLError(failure)
                api = Mock()
                api.call.side_effect = failure
                with patch.object(fixture, 'API') as new_client, \
                     patch.object(fixture.time, 'sleep') as sleep:
                    with self.assertRaisesRegex(RuntimeError, 'Reset the dedicated fixture'):
                        fixture.wait(lambda: fixture.bootstrap_state(api, verified=True), 'bootstrap')
                api.call.assert_called_once_with('GET', 'bootstrap')
                new_client.assert_not_called()
                sleep.assert_not_called()

    def test_verified_reuse_preserves_the_verified_client(self):
        api = Mock()
        api.call.return_value = {'bootstrap_status': {'state': 'completed'}}
        self.assertEqual(fixture.bootstrap_state(api, verified=True), 'completed')
        api.call.assert_called_once_with('GET', 'bootstrap')

    def test_initial_bootstrap_does_not_hide_certificate_errors(self):
        api = Mock()
        failure = urllib.error.URLError(ssl.SSLCertVerificationError(1, 'untrusted certificate'))
        api.call.side_effect = failure
        with self.assertRaises(urllib.error.URLError) as raised:
            fixture.bootstrap_state(api, verified=False)
        self.assertIs(raised.exception, failure)

    def test_temporary_connection_failure_still_retries(self):
        api = Mock()
        api.call.side_effect = [urllib.error.URLError(ConnectionRefusedError()),
                               {'bootstrap_status': {'state': 'completed'}}]
        with patch.object(fixture.time, 'sleep') as sleep:
            result = fixture.wait(lambda: fixture.bootstrap_state(api, verified=True), 'bootstrap')
        self.assertEqual(result, 'completed')
        self.assertEqual(api.call.call_count, 2)
        sleep.assert_called_once()

    def test_permanent_api_error_is_not_reclassified_as_stale_ca(self):
        api = Mock()
        failure = fixture.APIError('GET', 'bootstrap', 401)
        api.call.side_effect = failure
        with self.assertRaises(fixture.APIError) as raised:
            fixture.bootstrap_state(api, verified=True)
        self.assertIs(raised.exception, failure)

    def test_certificate_install_retries_until_admin_credentials_propagate(self):
        check = Mock(side_effect=[
            fixture.APIError('PUT', 'cluster/certificates', 401),
            fixture.APIError('PUT', 'cluster/certificates', 403),
            fixture.APIError('PUT', 'cluster/certificates', 503),
            True,
        ])
        with patch.object(fixture.time, 'sleep') as sleep:
            self.assertTrue(fixture.wait(check, 'management certificate installation'))
        self.assertEqual(check.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

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
            ('POST', 'users', 403),
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
