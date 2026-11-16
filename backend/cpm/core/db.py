"""DB access. user_tx runs queries AS the caller (SET ROLE authenticated + JWT claims), so Postgres
RLS applies to everything the API does on a user's behalf. service_tx bypasses RLS (worker/system)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from cpm.core.config import get_settings

__all__ = ["Jsonb", "all_", "one", "service_tx", "user_tx"]


def _connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url, row_factory=dict_row)


@contextmanager
def user_tx(user_id: str) -> Iterator[psycopg.Connection]:
    with _connect() as conn, conn.transaction():
        conn.execute("set local role authenticated")
        conn.execute(
            "select set_config('request.jwt.claims', %s, true)",
            (json.dumps({"sub": user_id, "role": "authenticated"}),),
        )
        yield conn


@contextmanager
def service_tx() -> Iterator[psycopg.Connection]:
    with _connect() as conn, conn.transaction():
        if role := get_settings().db_service_role:
            conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        yield conn


def one(conn: psycopg.Connection, sql: str, params: Any = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def all_(conn: psycopg.Connection, sql: str, params: Any = None) -> list[dict]:
    return conn.execute(sql, params).fetchall()
