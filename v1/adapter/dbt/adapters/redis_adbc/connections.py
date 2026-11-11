"""Connection management: dbt <-> Redis ADBC driver via adbc_driver_manager's DB-API."""

import os
import random
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Literal, Optional, Set, Tuple, Union
from urllib.parse import urlsplit, urlunsplit

import adbc_driver_manager
import adbc_driver_manager.dbapi as dbapi
import sqlparse
from adbc_driver_manager import AdbcStatusCode
from dbt_common.exceptions import DbtDatabaseError, DbtRuntimeError

from dbt.adapters.contracts.connection import AdapterResponse, Connection, ConnectionState, Credentials
from dbt.adapters.events.logging import AdapterLogger
from dbt.adapters.sql import SQLConnectionManager

logger = AdapterLogger("RedisAdbc")

# Driver options that profile fields set (option -> field), so
# driver_options can't.
_PROFILE_OPTIONS = {
    "uri": "uri",
    "username": "username",
    "password": "password",
    "adbc.redis.default_schema": "schema",
    "adbc.redis.aggregate_pushdown": "aggregate_pushdown",
    "adbc.redis.rename_rekey": "rename_rekey",
    "adbc.redis.time_zone": "time_zone",
    "adbc.redis.read_timeout": "read_timeout",
    "adbc.redis.write_timeout": "write_timeout",
}

# Unknown profile keys already warned about (profiles can load more than once).
_warned_keys: Set[str] = set()

_FLIGHT_COOKIES = "adbc.flight.sql.rpc.with_cookie_middleware"


def _option_value(value: Any) -> str:
    # ADBC options are strings; booleans as the driver spells them.
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass
class RedisAdbcCredentials(Credentials):
    transport: Literal["redis", "flightsql"] = "redis"
    # Path to libadbc_driver_redis.{so,dylib,dll}; falls back to $REDIS_ADBC_DRIVER.
    driver: Optional[str] = None
    uri: str = "redis://localhost:6379/0"
    username: Optional[str] = None
    password: Optional[str] = None
    # exact | all | none (see the driver README).
    aggregate_pushdown: Optional[str] = None
    # Move a renamed table's rows to its new name's keys (driver option
    # adbc.redis.rename_rekey). dbt renames every table it builds, so this
    # copies every row once more per build, in exchange for key names that
    # match the table's.
    rename_rekey: Optional[bool] = None
    # The session time zone (adbc.redis.time_zone): what current_timestamp's
    # text, localtimestamp and TIMESTAMP <-> TIMESTAMP WITH TIME ZONE
    # conversions use. UTC by default.
    time_zone: Optional[str] = None
    # How long the client waits for each reply, and to send each command:
    # "30s", "10m", a number of seconds, or 0 for no timeout.
    read_timeout: Optional[Union[str, int]] = None
    write_timeout: Optional[Union[str, int]] = None
    # Any other driver option, passed as is (see the driver README's Options).
    driver_options: Optional[Dict[str, Any]] = None

    @classmethod
    def __pre_deserialize__(cls, data):
        data = super().__pre_deserialize__(data)
        # The driver exposes a single catalog named "redis".
        data.setdefault("database", "redis")
        # dbt accepts profile keys the adapter doesn't have, and drops them.
        for key in sorted(data.keys() - cls.__dataclass_fields__.keys() - _warned_keys):
            _warned_keys.add(key)
            logger.warning(f"`{key}` isn't a redis_adbc profile option; it's ignored")
        for option, value in (data.get("driver_options") or {}).items():
            if option in _PROFILE_OPTIONS:
                raise DbtRuntimeError(
                    f"driver_options can't set {option}; use the profile's `{_PROFILE_OPTIONS[option]}`"
                )
            if not isinstance(value, (str, int, float, bool)):
                raise DbtRuntimeError(f"driver_options: {option} must be a string, number or boolean")
        if data.get("transport") == "flightsql":
            cls._validate_flight_options(data)
        return data

    @staticmethod
    def _validate_flight_options(data):
        if not data.get("uri", "").startswith(("grpc://", "grpc+tls://")):
            raise DbtRuntimeError("Flight SQL requires a grpc:// or grpc+tls:// uri")
        for name in ("aggregate_pushdown", "rename_rekey", "read_timeout", "write_timeout"):
            if data.get(name) not in (None, ""):
                raise DbtRuntimeError(f"Flight SQL: configure `{name}` on the Flight server")
        for option, value in (data.get("driver_options") or {}).items():
            if option.startswith("adbc.redis."):
                raise DbtRuntimeError(f"Flight SQL: configure `{option}` on the Flight server")
            if option == _FLIGHT_COOKIES and _option_value(value) != "true":
                raise DbtRuntimeError("Flight SQL requires cookie middleware for dbt sessions")

    @classmethod
    def validate(cls, data):
        # dbt validates the profile before __pre_deserialize__ sets the default.
        super().validate({"database": "redis", **data})

    @property
    def type(self) -> str:
        return "redis_adbc"

    @property
    def unique_field(self) -> str:
        # Hashed for dbt's anonymous usage stats: the server, not credentials.
        return _redact_uri(self.uri, keep_user=False)

    def _connection_keys(self) -> Tuple[str, ...]:
        return (
            "transport",
            "driver",
            "uri",
            "database",
            "schema",
            "username",
            "aggregate_pushdown",
            "rename_rekey",
            "time_zone",
            "read_timeout",
            "write_timeout",
            "driver_options",
        )

    def connection_info(self, *, with_aliases: bool = False) -> Iterable[Tuple[str, Any]]:
        # dbt debug prints these and logs them: never the URI's password.
        for key, value in super().connection_info(with_aliases=with_aliases):
            if key == "driver_options" and value:
                # Flight options can contain bearer tokens or private keys.
                value = {option: "<redacted>" for option in value}
            yield key, _redact_uri(value) if key == "uri" and value else value

    def driver_path(self) -> str:
        if self.transport == "flightsql" and not self.driver:
            try:
                import adbc_driver_flightsql
            except ImportError as e:
                raise DbtRuntimeError(
                    "Install dbt-redis-adbc[flightsql] or set `driver` to the Flight SQL library"
                ) from e
            return adbc_driver_flightsql._driver_path()
        path = self.driver or os.environ.get("REDIS_ADBC_DRIVER")
        if not path:
            raise DbtRuntimeError(
                "No Redis ADBC driver configured: set `driver` in profiles.yml or $REDIS_ADBC_DRIVER"
            )
        path = os.path.expanduser(path)
        # `driver/libadbc_driver_redis` means the platform's shared library.
        if not os.path.splitext(os.path.basename(path))[1]:
            path += {"darwin": ".dylib", "win32": ".dll"}.get(sys.platform, ".so")
        return path

    def db_kwargs(self) -> Dict[str, str]:
        """The driver's database options for this profile."""
        kwargs = {option: _option_value(v) for option, v in (self.driver_options or {}).items()}
        if self.transport == "flightsql":
            self._validate_flight_options(vars(self))
            kwargs[_FLIGHT_COOKIES] = "true"
            for name in ("uri", "username", "password"):
                value = getattr(self, name)
                if value is not None and value != "":
                    kwargs[name] = value
            return kwargs
        for option, name in _PROFILE_OPTIONS.items():
            value = getattr(self, name)
            # None, or "" from an unset env_var, leaves the driver's default.
            if value is not None and value != "":
                kwargs[option] = _option_value(value)
        return kwargs


def _redact_uri(uri: str, keep_user: bool = True) -> str:
    """The URI with its password replaced by ****, or (keep_user=False)
    without any credentials."""
    try:
        parts = urlsplit(uri)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "<unparseable uri>"
    if keep_user and (parts.username or parts.password):
        user = parts.username or ""
        host = f"{user}:****@{host}" if parts.password else f"{user}@{host}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


class RedisAdbcCursor:
    """Retry native refused publications, without replaying committed SQL/input."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._cursor.close()

    def _publish(self, action, replayable):
        for attempt in range(20):
            try:
                return action()
            except adbc_driver_manager.OperationalError as error:
                # This specific 40001 is a refused publication, not an unknown
                # commit outcome. Other errors and consumed input must surface.
                if not (
                    replayable
                    and error.sqlstate == "40001"
                    and "snapshot catalog changed concurrently; retry the statement" in str(error)
                    and attempt < 19
                ):
                    raise
                self._cursor.close()
                self._cursor = self._conn.cursor()
                delay = random.uniform(0.05, 0.1) * min(2 ** attempt, 16)
                logger.debug(f"Redis ADBC: retrying snapshot publication conflict in {delay:.2f}s")
                time.sleep(delay)

    def execute(self, operation, parameters=None, **kwargs):
        if parameters is not None:
            return self._cursor.execute(operation, parameters, **kwargs)
        # The native driver autocommits each statement in a script. Split first
        # so a conflict never replays an earlier statement that already committed.
        for statement in sqlparse.split(operation) or [operation]:
            self._publish(lambda: self._cursor.execute(statement, **kwargs), replayable=True)
        return self

    def adbc_ingest(self, table_name, data, **kwargs):
        import pyarrow as pa

        if isinstance(data, pa.RecordBatchReader):
            # Capture a one-shot reader once, without holding its entire result
            # in memory. Every attempt opens fresh input from the private spool.
            with tempfile.TemporaryFile() as spool:
                with pa.ipc.new_file(spool, data.schema) as writer:
                    for batch in data:
                        writer.write_batch(batch)

                def ingest():
                    spool.seek(0)
                    saved = pa.ipc.open_file(spool)
                    batches = (saved.get_batch(i) for i in range(saved.num_record_batches))
                    with pa.RecordBatchReader.from_batches(saved.schema, batches) as reader:
                        return self._cursor.adbc_ingest(table_name, reader, **kwargs)

                return self._publish(ingest, replayable=True)
        # Tables supply fresh Arrow input; unknown stream types are not replayed.
        return self._publish(
            lambda: self._cursor.adbc_ingest(table_name, data, **kwargs),
            replayable=isinstance(data, pa.Table),
        )


class RedisAdbcHandle:
    """Wraps an ADBC DB-API connection so cursors dbt never closes get closed.

    ADBC refuses to close a connection while it still has open statements.
    """

    def __init__(self, conn: dbapi.Connection, native: bool = True):
        self.conn = conn
        self.native = native
        self._cursors: list = []

    def cursor(self):
        # Close finished cursors eagerly so statements don't pile up.
        self._cursors = [c for c in self._cursors if not c._closed]
        cur = RedisAdbcCursor(self.conn) if self.native else self.conn.cursor()
        self._cursors.append(cur)
        return cur

    def commit(self):
        pass  # autocommit only

    def rollback(self):
        pass  # no transactions

    def cancel(self):
        """Cancel the statement running on this connection, or the streamed
        result it is reading (from another thread). Either then fails with
        CANCELLED (see exception_handler).

        A cursor with neither refuses with INVALID_STATE.
        """
        for cur in list(self._cursors):
            if cur._closed:
                continue
            try:
                cur.adbc_cancel()
            except adbc_driver_manager.Error as e:
                if e.status_code != AdbcStatusCode.INVALID_STATE:
                    logger.warning(f"Redis ADBC: cancelling a statement failed: {e}")

    def close(self):
        for cur in self._cursors:
            try:
                cur.close()
            except Exception:
                pass
        self._cursors = []
        self.conn.close()


class RedisAdbcSession:
    """What a Python model gets as `session`: the thread's ADBC DB-API
    connection, except that its cursors go through the handle (so dbt
    closes them, and Ctrl-C cancels them) and it can't be closed."""

    def __init__(self, handle: RedisAdbcHandle):
        self._handle = handle

    def cursor(self):
        return self._handle.cursor()

    def close(self):
        raise DbtRuntimeError("A Python model's session is dbt's connection; it can't be closed")

    def __getattr__(self, name):
        return getattr(self._handle.conn, name)


class RedisAdbcConnectionManager(SQLConnectionManager):
    TYPE = "redis_adbc"

    @classmethod
    def open(cls, connection: Connection) -> Connection:
        if connection.state == ConnectionState.OPEN:
            return connection
        creds: RedisAdbcCredentials = connection.credentials

        def connect():
            conn = dbapi.connect(driver=creds.driver_path(), db_kwargs=creds.db_kwargs(), autocommit=True)
            if creds.transport == "flightsql":
                try:
                    # Prime the cookie before SET: the server starts a session
                    # on the first request that returns its cookie.
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.fetchall()
                        schema = creds.schema.replace('"', '""')
                        cursor.execute(f'SET search_path TO "{schema}"')
                        if creds.time_zone:
                            zone = creds.time_zone.replace("'", "''")
                            cursor.execute(f"SET TIME ZONE '{zone}'")
                except Exception:
                    conn.close()
                    raise
            return RedisAdbcHandle(conn, native=creds.transport == "redis")

        return cls.retry_connection(
            connection,
            connect=connect,
            logger=logger,
            retryable_exceptions=[adbc_driver_manager.OperationalError],
        )

    @contextmanager
    def exception_handler(self, sql: str):
        try:
            yield
        except adbc_driver_manager.Error as e:
            if e.status_code == AdbcStatusCode.CANCELLED:
                # Cancelled (Ctrl-C, --fail-fast): not the database's error.
                # A write keeps the rows it wrote before the cancel.
                logger.debug(f"Redis ADBC: cancelled: {e}")
                raise DbtRuntimeError(str(e).strip()) from e
            logger.debug(f"Redis ADBC error: {e}")
            raise DbtDatabaseError(str(e).strip()) from e
        except Exception as e:
            if isinstance(e, (DbtRuntimeError, DbtDatabaseError)):
                raise
            raise DbtRuntimeError(str(e)) from e

    def execute(self, sql: str, auto_begin: bool = False, fetch: bool = False, limit: Optional[int] = None):
        # The driver streams a long result (over 65,536 rows), so an error
        # past its first batch comes from fetching the rows, which dbt does
        # outside add_query's exception_handler.
        with self.exception_handler(sql):
            return super().execute(sql, auto_begin=auto_begin, fetch=fetch, limit=limit)

    def cancel(self, connection: Connection):
        # dbt calls this from the main thread on Ctrl-C and --fail-fast.
        connection.handle.cancel()

    @classmethod
    def get_response(cls, cursor: Any) -> AdapterResponse:
        rows = cursor.rowcount if cursor is not None else -1
        return AdapterResponse(_message="OK", rows_affected=rows if rows is not None else -1)

    @classmethod
    def data_type_code_to_name(cls, type_code) -> str:
        from dbt.adapters.redis_adbc.impl import arrow_type_to_sql

        return arrow_type_to_sql(type_code)
