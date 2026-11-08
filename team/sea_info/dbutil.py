"""SCR-06/08/13 데이터 계층이 같이 쓰는 SQLite 도우미."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

from sea_info import store

KST = ZoneInfo("Asia/Seoul")


@contextmanager
def db(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """연결을 열고, 성공하면 커밋·실패하면 롤백하고, 항상 닫는다."""
    con = store.connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def now() -> str:
    return datetime.now(KST).isoformat()


def parse_ts(value: str | None) -> datetime | None:
    """저장된 ISO 시각(UTC 또는 KST)을 한국 시간으로 바꾼다."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def format_ts(value: str | None) -> str:
    dt = parse_ts(value)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def add_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
