"""A security probe must fail without repeating leaked credentials in diagnostics."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flight_security import verify_password_redaction
from smoke import SmokeError


class RedactionTests(unittest.TestCase):
    def test_rejects_either_hop_password_without_echoing_it(self):
        env = {'REDIS_PASSWORD': 'backend-private-value', 'FLIGHT_SQL_PASSWORD': 'client-private-value'}
        for secret in env.values():
            with self.subTest(hop=secret.split('-')[0]):
                with self.assertRaises(SmokeError) as raised:
                    verify_password_redaction('diagnostic: ' + secret, env)
                for password in env.values():
                    self.assertNotIn(password, str(raised.exception))

    def test_accepts_redacted_output_and_absent_optional_hop(self):
        verify_password_redaction('password=[REDACTED]', {'REDIS_PASSWORD': 'backend-private-value'})
        verify_password_redaction('successful query', {})


if __name__ == '__main__':
    unittest.main()
