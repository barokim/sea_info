"""Arrow(pyarrow)가 막힌 PC에서도 화면이 죽지 않게 하는 도우미.

Windows의 앱 제어 정책이 pyarrow의 DLL(arrow_compute.dll)을 막으면 `st.dataframe`·`st.map`이
ImportError로 화면 전체를 멈춘다. 이때는 표를 HTML로, 지도는 좌표 글로 대신 보여 준다.
"""
from __future__ import annotations

import html
from typing import Any, Iterable

import streamlit as st

_ARROW_OK: bool | None = None


def arrow_ok() -> bool:
    """pyarrow를 불러올 수 있는지 한 번만 확인한다."""
    global _ARROW_OK
    if _ARROW_OK is None:
        try:
            import pyarrow.lib  # noqa: F401
            _ARROW_OK = True
        except Exception:  # noqa: BLE001 - ImportError뿐 아니라 DLL 차단(OSError)도 포함
            _ARROW_OK = False
    return _ARROW_OK


def html_table(rows: list[dict[str, Any]], image_cols: Iterable[str] = (), height: int | None = None) -> None:
    """딕셔너리 목록을 HTML 표로 그린다. 글자는 모두 이스케이프하고, image_cols의 값은 data:image 주소만 그림으로 넣는다."""
    if not rows:
        return
    images = set(image_cols)
    cols = list(rows[0].keys())
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if c in images and isinstance(v, str) and v.startswith("data:image/"):
                cells.append(f"<td><img src='{html.escape(v, quote=True)}' width='48' height='48' "
                             "style='object-fit:cover;border-radius:6px'></td>")
            else:
                cells.append(f"<td>{html.escape('' if v is None else str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    style = ("<style>.sit{border-collapse:collapse;width:100%;font-size:.9rem}"
             ".sit th,.sit td{border-bottom:1px solid rgba(128,128,128,.25);padding:.35rem .5rem;text-align:left;vertical-align:middle}"
             ".sit th{position:sticky;top:0;background:rgba(128,128,128,.12)}</style>")
    box = f"max-height:{height}px;overflow:auto" if height else ""
    st.markdown(f"{style}<div style='{box}'><table class='sit'><thead><tr>{head}</tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table></div>", unsafe_allow_html=True)


def safe_map(lat: float, lon: float, zoom: int = 10, size: int = 2000) -> None:
    """지도를 못 그리면 좌표만 글로 보여 준다."""
    if arrow_ok():
        try:
            st.map({"lat": [lat], "lon": [lon]}, zoom=zoom, size=size)
            return
        except Exception:  # noqa: BLE001
            pass
    st.caption(f"지도를 이 PC에서는 표시할 수 없어 좌표로 보여 줍니다: 위도 {lat:.4f}, 경도 {lon:.4f}")


def _rows_of(data: Any) -> list[dict[str, Any]]:
    """표로 그릴 수 있게 list[dict] 모양으로 바꾼다(dict of list / dict of dict 지원)."""
    if isinstance(data, list):
        return [dict(r) if isinstance(r, dict) else {"값": r} for r in data]
    if isinstance(data, dict):
        rows: list[dict[str, Any]] = []
        for name, series in data.items():
            if isinstance(series, dict):
                rows += [{"항목": k, str(name): v} for k, v in series.items()]
            else:
                rows += [{"번호": i + 1, str(name): v} for i, v in enumerate(series)]
        return rows
    return []


def safe_dataframe(data: Any, **kwargs: Any) -> None:
    """st.dataframe. pyarrow가 막히면 HTML 표로 대신 그린다(행 선택 같은 옵션은 쓰지 않는 표 전용)."""
    if arrow_ok():
        st.dataframe(data, **kwargs)
    else:
        html_table(_rows_of(data))


def safe_line_chart(data: Any, container: Any = None, **kwargs: Any) -> None:
    """container(열 등)를 주면 그 안에 그린다."""
    target = container if container is not None else st
    if arrow_ok():
        target.line_chart(data, **kwargs)
    else:
        if container is not None:
            with container:
                html_table(_rows_of(data))
        else:
            html_table(_rows_of(data))


def safe_bar_chart(data: Any, container: Any = None, **kwargs: Any) -> None:
    target = container if container is not None else st
    if arrow_ok():
        target.bar_chart(data, **kwargs)
    else:
        if container is not None:
            with container:
                html_table(_rows_of(data))
        else:
            html_table(_rows_of(data))
