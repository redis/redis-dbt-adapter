"""Shared connection policy for live Redis Enterprise integration checks.

The endpoint must be provisioned as a Redis Enterprise test cluster by its
operator. URI validation cannot identify a server's product or topology.
"""

import os
from urllib.parse import parse_qsl, urlsplit


def require_integration_config(environ=None):
    env = os.environ if environ is None else environ
    missing = [name for name in ("REDIS_URI", "REDIS_USERNAME", "REDIS_PASSWORD")
               if not env.get(name, "").strip()]
    if missing:
        raise ValueError("Redis Enterprise integration tests require " + ", ".join(missing))
    try:
        uri = urlsplit(env["REDIS_URI"])
        valid = uri.scheme == "rediss" and bool(uri.hostname) and bool(uri.port)
        insecure = any(key.lower() == "skip_verify" and value.lower() != "false"
                       for key, value in parse_qsl(uri.query, keep_blank_values=True))
    except ValueError:
        # Never include the URI or credentials in an error.
        raise ValueError("REDIS_URI must be a valid rediss://host:port/0 endpoint") from None
    if not valid or insecure:
        raise ValueError("Redis Enterprise integration tests require rediss://host:port/0 "
                         "with TLS certificate verification enabled")


if __name__ == "__main__":
    try:
        require_integration_config()
    except ValueError as error:
        raise SystemExit(str(error))
    print("Authenticated TLS integration configuration validated.")
