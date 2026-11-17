"""Loopback TLS fault fixture for the dedicated Redis qualification backend.

Adapted from Flight's publication_refusal_integration_test.go at e4dcbd3.
A selected workspace is sealed, but never published. Returning CAS=0 only after
successful seal makes the driver exhaust its own rebase attempts and emit the
real refused-publication error. No SQL or Flight error is fabricated.
"""
import contextlib
import re
import socket
import socketserver
import ssl
import threading
import time
from urllib.parse import urlsplit


def ssl_enum(value):
    """Keep only bounded OpenSSL symbolic identifiers, never exception text."""
    if value is None:
        return None
    return value if isinstance(value, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', value) else 'UNKNOWN'


def read_frame(stream):
    """Copy one RESP2/3 frame exactly, including errors and nested Search replies."""
    line = stream.readline()
    if not line.endswith(b'\r\n'):
        raise EOFError('Incomplete RESP frame')
    kind, value = line[:1], line[1:-2]
    if kind in (b'$', b'!', b'='):
        size = int(value)
        if size >= 0:
            payload = stream.read(size + 2)
            if len(payload) != size + 2 or not payload.endswith(b'\r\n'):
                raise EOFError('Incomplete RESP payload')
            return line + payload
    elif kind in (b'*', b'~', b'>', b'%', b'|'):
        count = int(value) * (2 if kind in (b'%', b'|') else 1)
        return line + b''.join(read_frame(stream) for _ in range(max(0, count)))
    return line


def read_command(stream):
    line = stream.readline()
    if not line:
        raise EOFError('Connection closed')
    if not line.startswith(b'*'):
        raise ValueError('Expected a RESP command array')
    args = []
    for _ in range(int(line[1:-2])):
        header = stream.readline()
        if not header.startswith(b'$'):
            raise ValueError('Expected a bulk command argument')
        size = int(header[1:-2])
        if size < 0:
            raise ValueError('Null command argument')
        payload = stream.read(size + 2)
        if len(payload) != size + 2 or not payload.endswith(b'\r\n'):
            raise EOFError('Incomplete command argument')
        args.append(payload[:-2])
    return args


def command_frame(args):
    return b'*%d\r\n' % len(args) + b''.join(b'$%d\r\n' % len(arg) + arg + b'\r\n' for arg in args)


class PublicationGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.arm(limit=0)

    def arm(self, *, limit=1, skip=0):
        with self.lock:
            self.limit, self.skip = limit, skip
            self.workspaces = {}
            self.refused = 0
            self.passed = 0
            self.started = time.monotonic()

    def select(self, args):
        if len(args) < 4 or args[0].lower() not in (b'eval', b'evalsha'):
            return False
        count = int(args[2])
        index = 3 + count
        if count < 1 or len(args) <= index + 2 or args[3] != b'adbc:{meta}:snapshot:catalog' or args[index] != b'publish':
            return False
        with self.lock:
            if self.skip:
                self.skip -= 1
                return False
            workspace = args[index + 2]
            if workspace not in self.workspaces:
                if self.limit is not None and len(self.workspaces) >= self.limit:
                    self.passed += 1
                    return False
                self.workspaces[workspace] = {'calls': 0, 'first_seconds': time.monotonic() - self.started}
            self.workspaces[workspace]['calls'] += 1
            args[index] = b'seal'
            return True

    def record(self, reply):
        # Errors and unexpected seal responses must pass through unchanged.
        if reply == b':1\r\n':
            with self.lock:
                self.refused += 1
            return b':0\r\n'
        return reply

    def receipt(self):
        with self.lock:
            return {'workspaces': list(self.workspaces.values()), 'refused_cas': self.refused,
                    'passed_publications': self.passed}


class PublicationProxy(socketserver.ThreadingTCPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, uri, backend_ca, cert, key):
        parsed = urlsplit(uri)
        if parsed.scheme != 'rediss' or parsed.username or parsed.password or parsed.query:
            raise ValueError('Publication fixture requires a credential-free rediss URI')
        self.backend = (parsed.hostname, parsed.port or 6379)
        self.backend_tls = ssl.create_default_context(cafile=str(backend_ca))
        self.front_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.front_tls.minimum_version = ssl.TLSVersion.TLSv1_2
        self.front_tls.load_cert_chain(cert, key)
        self.gate = PublicationGate()
        self.connections = set()
        self.lock = threading.Lock()
        self.errors = []
        self.phase = 'startup'
        super().__init__(('127.0.0.1', 0), _Handler)
        self.uri = f'rediss://127.0.0.1:{self.server_address[1]}{parsed.path}'

    def set_phase(self, phase):
        with self.lock:
            self.phase = phase

    def record_error(self, error, stage):
        # Do not retain str(error), args, RESP data, addresses or certificates.
        with self.lock:
            entry = {'type': type(error).__name__, 'phase': self.phase, 'stage': stage}
            if isinstance(error, ssl.SSLError):
                entry.update(ssl_library=ssl_enum(getattr(error, 'library', None)),
                             ssl_reason=ssl_enum(getattr(error, 'reason', None)),
                             ssl_errno=error.errno)
            self.errors.append(entry)

    def error_receipt(self):
        with self.lock:
            return [dict(entry) for entry in self.errors]

    def check_errors(self):
        errors = self.error_receipt()
        if errors:
            raise RuntimeError('Publication proxy encountered protocol errors: ' + str(errors))

    def __enter__(self):
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        with self.lock:
            for connection in self.connections:
                with contextlib.suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
                connection.close()
        self.server_close()
        self.thread.join()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        proxy = self.server
        self.request.settimeout(30)
        stage = 'front-handshake'
        try:
            with proxy.front_tls.wrap_socket(self.request, server_side=True) as client:
                stage = 'backend-connect'
                with socket.create_connection(proxy.backend, timeout=30) as raw_backend:
                    stage = 'backend-handshake'
                    backend = proxy.backend_tls.wrap_socket(raw_backend, server_hostname=proxy.backend[0])
                with backend:
                    with proxy.lock:
                        proxy.connections.update((client, backend))
                    try:
                        with client.makefile('rb') as requests, backend.makefile('rb') as replies:
                            while True:
                                stage = 'client-read'
                                args = read_command(requests)
                                stage = 'publication-select'
                                refuse = proxy.gate.select(args)
                                stage = 'backend-write'
                                backend.sendall(command_frame(args))
                                stage = 'backend-read'
                                reply = read_frame(replies)
                                # RESP3 attributes decorate the next response.
                                while reply.startswith(b'|'):
                                    stage = 'client-write-attribute'
                                    client.sendall(reply)
                                    stage = 'backend-read'
                                    reply = read_frame(replies)
                                stage = 'client-write'
                                client.sendall(proxy.gate.record(reply) if refuse else reply)
                    finally:
                        with proxy.lock:
                            proxy.connections.difference_update((client, backend))
        except (EOFError, ConnectionError, TimeoutError):
            pass
        except Exception as error:
            proxy.record_error(error, stage)
