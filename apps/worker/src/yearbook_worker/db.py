"""Postgres connections: one pool per worker process plus a dedicated LISTEN connection."""

from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(dsn: str, *, min_size: int = 1, max_size: int = 4) -> ConnectionPool:
    """Open a connection pool. Rows come back as dicts; `vector` columns as pgvector values."""
    return ConnectionPool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        kwargs={"row_factory": dict_row},
        configure=register_vector,
        open=True,
        name="yearbook-worker",
    )


def listen_connection(dsn: str, channel: str) -> psycopg.Connection:
    """Open an autocommit connection subscribed to `channel`."""
    conn = psycopg.connect(dsn, autocommit=True)
    conn.execute(psycopg.sql.SQL("listen {}").format(psycopg.sql.Identifier(channel)))
    return conn
