"""Fault fixture regressions: only definite, sealed publication refusals."""
import io
import json
import socket
import shutil
import subprocess
import tempfile
import ssl
import threading
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publication_proxy import PublicationGate, PublicationProxy, _Handler, command_frame, read_command, read_frame


def publication(workspace=b'one'):
    return [b'EVALSHA', b'digest', b'1', b'adbc:{meta}:snapshot:catalog', b'publish', b'base', workspace]


class PublicationGateTests(unittest.TestCase):
    def test_refuses_all_rebases_of_only_first_workspace(self):
        gate = PublicationGate()
        gate.arm()
        for _ in range(4):
            args = publication()
            self.assertTrue(gate.select(args))
            self.assertEqual(args[4], b'seal')
            self.assertEqual(gate.record(b':1\r\n'), b':0\r\n')
        self.assertFalse(gate.select(publication(b'fresh-retry')))
        receipt = gate.receipt()
        self.assertEqual(len(receipt['workspaces']), 1)
        self.assertEqual(receipt['refused_cas'], 4)
        self.assertEqual(receipt['passed_publications'], 1)

    def test_never_masks_unsuccessful_seal(self):
        gate = PublicationGate()
        for reply in (b'-ERR seal failed\r\n', b':0\r\n', b'$-1\r\n'):
            self.assertEqual(gate.record(reply), reply)
        self.assertEqual(gate.receipt()['refused_cas'], 0)

    def test_unarmed_and_unrelated_commands_are_untouched(self):
        gate = PublicationGate()
        for args in (publication(), [b'AUTH', b'alice', b'secret'],
                     [b'EVAL', b'script', b'1', b'other-key', b'publish', b'base', b'one']):
            before = args.copy()
            self.assertFalse(gate.select(args))
            self.assertEqual(args, before)

    def test_bound_and_skip_apply_to_workspaces_not_rebase_calls(self):
        gate = PublicationGate()
        gate.arm(limit=None, skip=1)
        self.assertFalse(gate.select(publication(b'committed-prefix')))
        for number in range(20):
            for _ in range(3):
                self.assertTrue(gate.select(publication(str(number).encode())))
        self.assertEqual(len(gate.receipt()['workspaces']), 20)
        self.assertEqual(sum(p['calls'] for p in gate.receipt()['workspaces']), 60)

    def test_finite_bound_keeps_refusing_rebases_and_allows_later_cleanup(self):
        gate = PublicationGate()
        gate.arm(limit=20)
        for number in range(20):
            self.assertTrue(gate.select(publication(str(number).encode())))
        # Rebase calls still belong to the refused twentieth SQL attempt.
        self.assertTrue(gate.select(publication(b'19')))
        self.assertFalse(gate.select(publication(b'worker-temp-cleanup')))
        self.assertEqual(len(gate.receipt()['workspaces']), 20)
        self.assertEqual(gate.receipt()['passed_publications'], 1)


class RESPTests(unittest.TestCase):
    def test_commands_roundtrip_binary_and_credentials_without_decoding(self):
        command = [b'auth', b'alice', b'password\r\n\x00\xff']
        self.assertEqual(read_command(io.BytesIO(command_frame(command))), command)

    def test_preserves_nested_resp3_frames_and_next_reply(self):
        frame = b'%2\r\n+name\r\n$3\r\na\x00b\r\n+values\r\n*3\r\n:1\r\n_\r\n!9\r\nERR error\r\n'
        stream = io.BytesIO(frame + b'+OK\r\n')
        self.assertEqual(read_frame(stream), frame)
        self.assertEqual(read_frame(stream), b'+OK\r\n')

    def test_rejects_truncated_frames_and_commands(self):
        for frame in (b'', b'+OK', b'$3\r\nx\r\n', b'*2\r\n:1\r\n'):
            with self.assertRaises(EOFError):
                read_frame(io.BytesIO(frame))
        with self.assertRaises(EOFError):
            read_command(io.BytesIO(b'*1\r\n$3\r\nx'))


class ProxyDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.proxy = PublicationProxy.__new__(PublicationProxy)
        self.proxy.lock = threading.Lock()
        self.proxy.errors = []
        self.proxy.phase = 'startup'
        self.proxy.connections = set()
        self.proxy.front_tls = MagicMock()
        self.proxy.backend_tls = MagicMock()
        self.proxy.backend = ('localhost', 6379)
        self.proxy.gate = PublicationGate()
        self.request = MagicMock()

    def ssl_error(self, reason='APPLICATION_DATA_AFTER_CLOSE_NOTIFY'):
        error = ssl.SSLError(ssl.SSL_ERROR_SSL, 'AUTH private-user private-password')
        error.library, error.reason = 'SSL', reason
        return error

    def handle(self):
        _Handler(self.request, ('127.0.0.1', 1), self.proxy)

    def test_front_handshake_ssl_failure_is_safe_and_fatal(self):
        self.proxy.set_phase('refusal')
        self.proxy.front_tls.wrap_socket.side_effect = self.ssl_error()
        self.handle()
        self.assertEqual(self.proxy.error_receipt(), [{
            'type': 'SSLError', 'phase': 'refusal', 'stage': 'front-handshake',
            'ssl_library': 'SSL', 'ssl_reason': 'APPLICATION_DATA_AFTER_CLOSE_NOTIFY',
            'ssl_errno': ssl.SSL_ERROR_SSL}])
        with self.assertRaises(RuntimeError) as caught:
            self.proxy.check_errors()
        self.assertNotIn('private-', str(caught.exception))

    def test_backend_handshake_and_client_read_are_distinguished(self):
        for stage in ('backend-handshake', 'client-read'):
            with self.subTest(stage=stage), patch('publication_proxy.socket.create_connection'):
                self.proxy.errors.clear()
                self.proxy.backend_tls.wrap_socket.side_effect = None
                if stage == 'backend-handshake':
                    self.proxy.backend_tls.wrap_socket.side_effect = self.ssl_error('CERTIFICATE_VERIFY_FAILED')
                else:
                    client = self.proxy.front_tls.wrap_socket.return_value.__enter__.return_value
                    client.makefile.return_value.__enter__.return_value.readline.side_effect = self.ssl_error()
                self.handle()
                self.assertEqual(self.proxy.error_receipt()[0]['stage'], stage)
                self.assertEqual(self.proxy.connections, set())

    def test_exception_text_and_invalid_ssl_identifiers_are_excluded(self):
        error = self.ssl_error('AUTH private-password\n')
        error.library = 'private library details'
        self.proxy.record_error(error, 'backend-read')
        self.proxy.record_error(ValueError('private-password in malformed RESP'), 'backend-read')
        receipt = self.proxy.error_receipt()
        self.assertEqual(receipt[0]['ssl_reason'], 'UNKNOWN')
        self.assertEqual(receipt[0]['ssl_library'], 'UNKNOWN')
        self.assertNotIn('private', json.dumps(receipt))
        self.assertNotIn('ssl_reason', receipt[1])

    def test_ssl_errors_without_reason_and_unclean_eof_remain_fatal(self):
        for error in (ssl.SSLError(ssl.SSL_ERROR_SSL, 'private-password'),
                      ssl.SSLEOFError(ssl.SSL_ERROR_EOF, 'private-password')):
            with self.subTest(error=type(error).__name__):
                self.proxy.errors.clear()
                self.proxy.front_tls.wrap_socket.side_effect = error
                self.handle()
                self.assertIsNone(self.proxy.error_receipt()[0]['ssl_reason'])
                with self.assertRaises(RuntimeError):
                    self.proxy.check_errors()

    def test_snapshots_cannot_change_retained_errors(self):
        self.proxy.record_error(self.ssl_error(), 'backend-read')
        snapshot = self.proxy.error_receipt()
        snapshot[0]['ssl_reason'] = 'CHANGED'
        snapshot.clear()
        self.assertEqual(self.proxy.error_receipt()[0]['ssl_reason'], 'APPLICATION_DATA_AFTER_CLOSE_NOTIFY')

    def test_existing_eof_connection_and_timeout_handling_is_unchanged(self):
        for error in (EOFError(), ConnectionResetError(), TimeoutError()):
            self.proxy.front_tls.wrap_socket.side_effect = error
            self.handle()
        self.assertEqual(self.proxy.error_receipt(), [])
        self.proxy.check_errors()


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL CLI is needed for loopback TLS certificates')
class ProxyLoopbackTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.cert = Path(cls.directory.name) / 'cert.pem'
        cls.key = Path(cls.directory.name) / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
                        '-keyout', str(cls.key), '-out', str(cls.cert)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def connect(self, proxy, context):
        raw = socket.socket()
        raw.settimeout(3)
        self.addCleanup(raw.close)
        raw.connect(proxy.server_address)
        return context.wrap_socket(raw, server_hostname='localhost')

    def test_real_untrusted_client_alert_remains_a_fatal_handshake_error(self):
        with PublicationProxy('rediss://localhost:1', self.cert, self.cert, self.key) as proxy:
            proxy.set_phase('security')
            with self.assertRaises(ssl.SSLCertVerificationError):
                self.connect(proxy, ssl.create_default_context())
        errors = proxy.error_receipt()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['phase'], 'security')
        self.assertEqual(errors[0]['stage'], 'front-handshake')
        self.assertEqual(errors[0]['ssl_library'], 'SSL')
        self.assertIn('ALERT', errors[0]['ssl_reason'])
        with self.assertRaises(RuntimeError):
            proxy.check_errors()

    def test_real_backend_certificate_failure_identifies_backend_handshake(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(3)
            backend_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            backend_tls.load_cert_chain(self.cert, self.key)
            def backend():
                with listener.accept()[0] as raw:
                    try:
                        with backend_tls.wrap_socket(raw, server_side=True):
                            pass
                    except ssl.SSLError:
                        pass  # The proxy deliberately rejects this untrusted peer.
            thread = threading.Thread(target=backend)
            thread.start()
            try:
                port = listener.getsockname()[1]
                with PublicationProxy(f'rediss://127.0.0.1:{port}', self.cert, self.cert, self.key) as proxy:
                    proxy.backend_tls = ssl.create_default_context()
                    with self.connect(proxy, ssl.create_default_context(cafile=str(self.cert))) as client:
                        self.assertEqual(client.recv(1), b'')
                error, = proxy.error_receipt()
                self.assertEqual(error['stage'], 'backend-handshake')
                self.assertEqual(error['type'], 'SSLCertVerificationError')
                self.assertEqual(error['ssl_reason'], 'CERTIFICATE_VERIFY_FAILED')
                with self.assertRaises(RuntimeError):
                    proxy.check_errors()
            finally:
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())

    def test_real_invalid_tls_record_is_fatal_but_normal_close_is_accepted(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), \
                    patch('publication_proxy.socket.create_connection'), \
                    PublicationProxy('rediss://localhost:1', self.cert, self.cert, self.key) as proxy:
                proxy.backend_tls = MagicMock()
                context = ssl.create_default_context(cafile=str(self.cert))
                client = self.connect(proxy, context)
                if corrupt:
                    # Detach TLS after the verified handshake and send a bad record.
                    with socket.socket(fileno=client.detach()) as raw:
                        raw.settimeout(3)
                        raw.sendall(b'\x17\x03\x03\x00\x20' + b'x' * 32)
                        raw.shutdown(socket.SHUT_WR)
                        while raw.recv(4096):
                            pass
                else:
                    client.close()
            if corrupt:
                errors = proxy.error_receipt()
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]['stage'], 'client-read')
                self.assertIsNotNone(errors[0]['ssl_reason'])
                with self.assertRaises(RuntimeError):
                    proxy.check_errors()
            else:
                self.assertEqual(proxy.error_receipt(), [])


if __name__ == '__main__':
    unittest.main()
