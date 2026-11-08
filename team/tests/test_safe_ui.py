"""pyarrow가 막힌 PC(Windows 앱 제어 정책)에서도 쓰는 표 도우미 시험."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sea_info import safe_ui  # noqa: E402


class _Capture:
    def __init__(self):
        self.out = ""

    def markdown(self, text, unsafe_allow_html=False):
        self.out += text


def test_html_table_글자는_이스케이프하고_그림은_data주소만(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(safe_ui, "st", cap)
    safe_ui.html_table([{"사진": "data:image/jpeg;base64,AAAA", "이름": "<script>x</script>", "장소": None},
                        {"사진": "http://evil.test/x.png", "이름": "소라게", "장소": "제주"}], image_cols=("사진",))
    assert "<script>" not in cap.out and "&lt;script&gt;" in cap.out
    assert cap.out.count("<img") == 1 and "evil.test" in cap.out and "<img src='http://evil" not in cap.out


def test_pyarrow가_막히면_arrow_ok는_False(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.lib", None)
    monkeypatch.setattr(safe_ui, "_ARROW_OK", None)
    assert safe_ui.arrow_ok() is False


def test_지도는_못그리면_좌표글로_대신(monkeypatch):
    cap = _Capture()
    cap.caption = lambda t: setattr(cap, "out", t)
    monkeypatch.setattr(safe_ui, "st", cap)
    monkeypatch.setattr(safe_ui, "_ARROW_OK", False)
    safe_ui.safe_map(33.5, 126.5)
    assert "33.5000" in cap.out and "126.5000" in cap.out


def test_safe_wrappers_fallback_without_pyarrow():
    import sys
    from streamlit.testing.v1 import AppTest

    code = (
        "import sys\n"
        "sys.modules['pyarrow']=None; sys.modules['pyarrow.lib']=None\n"
        "import streamlit as st\n"
        "from sea_info.safe_ui import safe_dataframe, safe_line_chart, safe_bar_chart\n"
        "safe_dataframe([{'a':1,'b':'x'}])\n"
        "safe_line_chart({'호출':[1,2,3]})\n"
        "l, r = st.columns(2)\n"
        "safe_bar_chart({'v':{'a':1,'b':2}}, container=r)\n"
    )
    at = AppTest.from_string(code).run()
    assert not at.exception
