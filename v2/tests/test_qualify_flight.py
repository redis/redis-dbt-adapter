"""Proxy failures must survive qualification cancellation and teardown."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualify_flight
from publication_proxy import PublicationProxy


class QualificationProxyTests(unittest.TestCase):
    def qualify(self, failure_phase=None, *, earlier_failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Cargo.lock').write_text('lock')
            binary = root / 'dbt'
            binary.write_text('binary')
            output = root / 'evidence'
            args = argparse.Namespace(output_dir=output, dbt=str(binary), engine_source=root,
                                      server_source=root, tls_cert=root / 'cert', tls_key=root / 'key',
                                      driver_ref=None, backend_evidence=None)
            proxy = PublicationProxy.__new__(PublicationProxy)
            proxy.lock = threading.Lock()
            proxy.errors = []
            proxy.phase = 'startup'
            proxy.uri = 'rediss://127.0.0.1:1'
            proxy.gate = Mock()
            proxy.__enter__ = Mock()

            def inject(*args):
                error = ssl.SSLError(ssl.SSL_ERROR_SSL, 'private-password')
                error.library, error.reason = 'SSL', 'APPLICATION_DATA_AFTER_CLOSE_NOTIFY'
                proxy.record_error(error, 'client-read')

            proxy.__exit__ = Mock(side_effect=inject if failure_phase == 'proxy-shutdown' else None)
            server = Mock()
            server.poll.return_value = None
            if failure_phase == 'server-shutdown':
                server.terminate.side_effect = inject

            def run(command, **kwargs):
                (output / 'flight-server.json').write_text('{}')
                result = Mock(returncode=0)
                return result

            def refusal(*args):
                if earlier_failure:
                    raise RuntimeError('earlier refusal failure')
                if failure_phase == 'refusal':
                    inject()

            env = {key: 'fixture' for key in ('FLIGHT_SQL_USERNAME', 'FLIGHT_SQL_PASSWORD',
                                              'FLIGHT_SQL_TLS_CA_FILE', 'REDIS_TLS_CA_FILE')}
            env.update(REDIS_URI='rediss://localhost:1', FLIGHT_SQL_DRIVER=str(binary))
            with patch.dict(os.environ, env), \
                    patch.object(qualify_flight, 'require_integration_config'), \
                    patch.object(qualify_flight, 'verify', return_value={}), \
                    patch.object(qualify_flight.platform, 'platform', return_value='test'), \
                    patch.object(qualify_flight.importlib.metadata, 'version', return_value='test'), \
                    patch.object(qualify_flight.subprocess, 'check_output', return_value='test'), \
                    patch.object(qualify_flight.subprocess, 'run', side_effect=run), \
                    patch.object(qualify_flight.subprocess, 'Popen', return_value=server), \
                    patch.object(qualify_flight.socket, 'create_connection'), \
                    patch.object(qualify_flight, 'PublicationProxy', return_value=proxy), \
                    patch.object(qualify_flight, 'qualify_refusals', side_effect=refusal), \
                    patch.object(qualify_flight, 'qualify_cancellation',
                                 side_effect=inject if failure_phase == 'session-cancellation' else None), \
                    patch('builtins.print'):
                if failure_phase or earlier_failure:
                    expected = 'earlier refusal failure' if earlier_failure else 'protocol errors'
                    with self.assertRaisesRegex(RuntimeError, expected):
                        qualify_flight.qualify(args)
                else:
                    qualify_flight.qualify(args)
            return json.loads((output / 'qualification.json').read_text())

    def test_success_requires_no_proxy_errors_after_shutdown(self):
        receipt = self.qualify()
        self.assertEqual(receipt['status'], 'passed')
        self.assertEqual(receipt['checks']['publication-proxy'], 'passed')
        self.assertEqual(receipt['proxy_errors'], [])

    def test_failures_in_refusal_cancellation_and_shutdown_are_fatal_and_retained(self):
        for phase in ('refusal', 'session-cancellation', 'server-shutdown', 'proxy-shutdown'):
            with self.subTest(phase=phase):
                receipt = self.qualify(phase)
                self.assertEqual(receipt['status'], 'failed')
                self.assertEqual(receipt['checks']['publication-proxy'], 'failed')
                self.assertEqual(receipt['proxy_errors'][0]['phase'], phase)
                self.assertNotIn('private-password', json.dumps(receipt))

    def test_teardown_errors_do_not_mask_an_earlier_failure(self):
        receipt = self.qualify('proxy-shutdown', earlier_failure=True)
        self.assertEqual(receipt['checks']['refusal'], 'failed')
        self.assertEqual(receipt['checks']['publication-proxy'], 'failed')
        self.assertEqual(receipt['proxy_errors'][0]['phase'], 'proxy-shutdown')


if __name__ == '__main__':
    unittest.main()
