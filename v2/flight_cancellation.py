"""Assess cancellation on one live Flight connection and Redis query leases.

This supplements native CLI SIGINT evidence; the ADBC protocol probe itself
uses Python, and does not claim native engine pool reuse after global SIGINT.
"""
import io
import json
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit

from publication_proxy import command_frame, read_frame
from smoke import SmokeError


def decode(stream):
    line = stream.readline()
    kind, value = line[:1], line[1:-2]
    if kind in (b'+', b':'):
        return value.decode() if kind == b'+' else int(value)
    if kind == b'$':
        size = int(value)
        if size < 0:
            return None
        data = stream.read(size)
        stream.read(2)
        return data
    if kind == b'*':
        return [decode(stream) for _ in range(int(value))]
    raise SmokeError('Unexpected Redis resource-probe response')


class Resources:
    def __init__(self, env):
        uri = urlsplit(env['REDIS_URI'])
        context = ssl.create_default_context(cafile=env['REDIS_TLS_CA_FILE'])
        self.socket = context.wrap_socket(socket.create_connection((uri.hostname, uri.port), timeout=10),
                                          server_hostname=uri.hostname)
        self.stream = self.socket.makefile('rb')
        self.call('AUTH', env['REDIS_USERNAME'], env['REDIS_PASSWORD'])

    def call(self, *args):
        self.socket.sendall(command_frame([arg if isinstance(arg, bytes) else str(arg).encode() for arg in args]))
        return decode(io.BytesIO(read_frame(self.stream)))

    def leases(self):
        cursor, records = 0, {}
        while True:
            cursor, keys = self.call('SCAN', cursor, 'MATCH', 'arrowflight:query:*', 'COUNT', 100)
            for key in keys:
                raw = self.call('GET', key.decode())
                if raw:
                    records[key] = json.loads(raw)
            if int(cursor) == 0:
                return records

    def close(self):
        self.stream.close()
        self.socket.close()


def qualify_cancellation(env, output):
    import adbc_driver_flightsql.dbapi as flight
    import adbc_driver_manager as adbc
    receipt = {'status': 'incomplete', 'client': 'Python ADBC Flight SQL', 'checks': {}}
    manifest = output / 'session-cancellation.json'
    options = {'username': env['FLIGHT_SQL_USERNAME'], 'password': env['FLIGHT_SQL_PASSWORD'],
               'adbc.flight.sql.client_option.tls_root_certs': Path(env['FLIGHT_SQL_TLS_CA_FILE']).read_text(),
               'adbc.flight.sql.rpc.with_cookie_middleware': 'true',
               'adbc.flight.sql.rpc.timeout_seconds.query': '30',
               'adbc.flight.sql.rpc.timeout_seconds.fetch': '15'}
    resources = Resources(env)
    try:
        before = resources.leases()
        with flight.connect(env['FLIGHT_SQL_URI'], db_kwargs=options, autocommit=True) as connection:
            with connection.cursor() as setup:
                for sql in ('select 1', "set time zone 'America/New_York'",
                            'create temp table cancellation_kept as select 42 as id'):
                    setup.execute(sql)
                    setup.fetchall()
            with connection.cursor() as cursor:
                cursor.execute("select repeat(cast(g as varchar), 2000) as payload from generate_series(1, 100000) as s(g)")
                reader = cursor.fetch_record_batch()
                batch = reader.read_next_batch()
                if batch.num_rows == 0:
                    raise SmokeError('Cancellation stream had no data')
                active = {key for key, record in resources.leases().items()
                          if key not in before and record.get('active', record.get('Active', 0)) > 0}
                receipt['checks']['observed_active_leases'] = len(active)
                start = time.monotonic()
                cursor.adbc_cancel()
                cancelled = False
                try:
                    for _ in reader:
                        pass
                except (adbc.Error, OSError) as error:
                    # PyArrow consumes the C stream and surfaces Flight fetch
                    # failures as OSError, outside the DB-API error hierarchy.
                    code = getattr(error, 'status_code', None)
                    cancelled = (code == adbc.AdbcStatusCode.CANCELLED or
                                 (isinstance(error, OSError) and '(Canceled;' in str(error)))
                    receipt['checks']['cancel_status'] = code.name if code is not None else 'Flight Canceled'
                finally:
                    reader.close()
                receipt['checks']['cancel_seconds'] = time.monotonic() - start
                if not cancelled:
                    raise SmokeError('Flight stream did not report cancellation')
            with connection.cursor() as check:
                check.execute('show time zone')
                receipt['checks']['time_zone'] = check.fetchone()[0]
                check.execute('select id from cancellation_kept')
                receipt['checks']['temporary_value'] = check.fetchone()[0]
            if receipt['checks']['time_zone'] != 'America/New_York' or receipt['checks']['temporary_value'] != 42:
                raise SmokeError('Cancellation changed same-session state')
            deadline = time.monotonic() + 10
            while True:
                after = resources.leases()
                remaining = sum(record.get('active', record.get('Active', 0)) for key, record in after.items() if key not in before)
                if remaining == 0:
                    break
                if time.monotonic() > deadline:
                    raise SmokeError('Flight retained active query leases after cancellation')
                time.sleep(.05)
            receipt['checks']['remaining_active_leases'] = remaining
            if not active:
                raise SmokeError('No live server lease observed; resource check would be vacuous')
        receipt['status'] = 'passed'
    except BaseException:
        receipt['status'] = 'failed'
        raise
    finally:
        resources.close()
        manifest.write_text(json.dumps(receipt, indent=2) + '\n')
