"""앱 시작 때 SCR-06/08/13이 쓰는 테이블·트리거를 준비한다(이미 있으면 아무것도 바꾸지 않는다)."""
from __future__ import annotations

import os

import streamlit as st

from sea_info import scr06_store, scr13_store


def ensure_once(path: str | None = None) -> None:
    key = f"_schema_ready:{path or os.getenv('SQLITE_PATH', '')}"
    if st.session_state.get(key):
        return
    scr06_store.ensure_schema(path)  # scr08(수족관) 스키마·트리거 포함
    scr13_store.ensure_schema(path)
    st.session_state[key] = True
