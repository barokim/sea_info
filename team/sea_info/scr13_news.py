"""SCR-13 해양 뉴스·칼럼 — 화면."""
from __future__ import annotations

import math
from typing import Any

import streamlit as st

from sea_info import bootstrap, news_collector as nc, scr13_store as ns
from sea_info.dbutil import format_ts


def _identity() -> tuple[str, str]:
    role = st.session_state.get("role", "guest")
    email = st.session_state.get("email", "")
    if role == "guest":
        return role, ""
    return role, email or ("운영자" if role == "admin" else "바다탐험가")


def _viewer_key(user: str) -> str:
    hint = ""
    try:  # 비회원은 접속 환경으로 같은 브라우저를 근사한다(쿠키 없이 가능한 범위)
        headers = st.context.headers
        hint = f"{headers.get('X-Forwarded-For', '')}|{headers.get('User-Agent', '')}"
    except Exception:
        pass
    return ns.make_viewer_key(user, hint)


PERIODS = {"1주": 7, "1개월": 30, "3개월": 90, "전체": None}
DEFAULT_PERIOD = "3개월"


def _source_line(a: dict[str, Any]) -> str:
    return f"출처 {a['source_name']} · 발행 {format_ts(a['published_at'])[:10]} · 조회 {a['view_count']:,}"


def _summary_badge(a: dict[str, Any]) -> str:
    if a["source_kind"] == "샘플":
        return "샘플 콘텐츠"
    return "AI 요약" if a["ai_summarized"] else "원문 발췌 요약"


@st.dialog("뉴스 상세", width="large")
def _detail_dialog(article_id: int) -> None:
    role, user = _identity()
    art = ns.get_article(article_id, include_hidden=role == "admin")
    if art is None:
        st.warning("기사를 찾을 수 없거나 비공개 처리되었습니다.")
        return
    if not art["is_hidden"]:
        ns.record_view(article_id, _viewer_key(user))
        art = ns.get_article(article_id, include_hidden=True) or art
    if art["is_hidden"]:
        st.warning(f"운영자가 숨김 처리한 기사입니다. ({art.get('hidden_reason') or '사유 없음'})")
    st.subheader(art["title"])
    st.caption(_source_line(art))
    st.markdown(f"**{_summary_badge(art)}**")
    st.write(art["summary_detail"] or art["summary"])
    if art["ai_summarized"]:
        st.caption("AI가 만든 요약은 틀릴 수 있습니다. 정확한 내용은 원문을 확인해 주세요.")
    if art["url"].startswith(("http://", "https://")):
        st.link_button("원문 보기", art["url"])
    else:
        st.caption("샘플 콘텐츠라 원문 링크가 없습니다.")


def render() -> None:
    bootstrap.ensure_once()
    role, user = _identity()
    cfg = st.session_state.get("settings", {}).get("integrations", {})
    nc.collect_if_due(enabled=bool(cfg.get("news_enabled")))  # 오늘 06:00 이후 첫 접속 때 한 번(스케줄러가 없을 때의 보조)

    st.caption("SCR-13 · Sea-Info Agent")
    st.title("해양 뉴스 · 칼럼")
    sources = ns.list_sources()
    if all(s["kind"] == "샘플" or not s["last_run_at"] for s in sources):
        st.caption("지금은 샘플 콘텐츠입니다. 뉴스 수집을 켜면 공공기관 소식이 매일 오전 6시(한국 시간)에 들어옵니다.")

    _render_top5()
    st.divider()
    _render_list()
    if role == "admin":
        _render_admin(user)


def _render_top5() -> None:
    settings = ns.get_settings()
    top = ns.top_articles(5)
    st.subheader("🔥 많이 읽은 소식 Top 5")
    st.caption(f"최근 {settings['news_top_days']}일 콘텐츠 · 조회수 순 · {top['refresh_minutes']}분마다 갱신 "
               f"(갱신 {format_ts(top['snapshot_at'])[11:]})")
    if not top["items"]:
        st.info("집계 기간 안에 공개된 기사가 없습니다.")
    for a in top["items"]:
        c1, c2 = st.columns([8, 2])
        c1.markdown(f"**{a['display_rank']}위** {a['title']}")
        c1.caption(_source_line(a))
        if c2.button("보기", key=f"top_{a['id']}"):
            _detail_dialog(a["id"])


def _render_list() -> None:
    st.subheader("전체 소식")
    sources = [s for s in ns.list_sources()]
    names = {0: "전체 출처", **{s["id"]: s["name"] for s in sources}}
    f1, f2, f3 = st.columns([3, 2, 2])
    search = f1.text_input("제목·요약 검색", key="news_search")
    source_id = f2.selectbox("출처", list(names), format_func=lambda i: names[i], key="news_source")
    period = f3.selectbox("기간", list(PERIODS), index=list(PERIODS).index(DEFAULT_PERIOD), key="news_period")
    days = PERIODS[period]
    per_page = ns.get_settings()["news_per_page"]
    items, total = ns.list_articles(search, source_id or None, st.session_state.get("news_page", 1), per_page,
                                    within_days=days)
    pages = max(1, math.ceil(total / per_page))
    page = min(st.session_state.get("news_page", 1), pages)
    if page != st.session_state.get("news_page", 1):
        st.session_state["news_page"] = page
        items, total = ns.list_articles(search, source_id or None, page, per_page, within_days=days)
    if not items:
        st.info("조건에 맞는 소식이 없습니다." + ("" if days is None else " 기간을 넓혀 보세요."))
    for a in items:
        with st.container(border=True):
            st.markdown(f"**{a['title']}**")
            st.write(a["summary"])
            left, right = st.columns([8, 2])
            left.caption(f"{_source_line(a)} · {_summary_badge(a)}")
            if right.button("자세히", key=f"list_{a['id']}"):
                _detail_dialog(a["id"])
    p1, p2, p3 = st.columns([1, 2, 1])
    if p1.button("← 이전", disabled=page <= 1, key="news_prev"):
        st.session_state["news_page"] = page - 1
        st.rerun()
    p2.caption(f"{page} / {pages} 쪽 · 총 {total}건")
    if p3.button("다음 →", disabled=page >= pages, key="news_next"):
        st.session_state["news_page"] = page + 1
        st.rerun()


# ------------------------------------------------------------------ 운영자
def _render_admin(user: str) -> None:
    with st.expander("🛠️ 운영자 도구 (사후 검토 · 수집 · 설정)"):
        t1, t2, t3, t4 = st.tabs(["기사 검토", "수집 출처·재처리", "집계 설정", "수집 이력"])
        with t1:
            _admin_articles()
        with t2:
            _admin_sources()
        with t3:
            _admin_settings()
        with t4:
            runs = ns.recent_runs()
            st.dataframe([{"시각": format_ts(r["started_at"]), "출처": r["source_name"], "실행": r["trigger"],
                           "결과": r["status"], "가져옴": r["fetched"], "새 기사": r["inserted"], "오류": r["error"] or ""}
                          for r in runs], hide_index=True, width="stretch")


def _admin_articles() -> None:
    items, total = ns.list_articles(include_hidden=True, per_page=50)
    st.caption(f"전체 {total}건 중 최신 50건")
    for a in items:
        with st.container(border=True):
            st.markdown(f"{'🙈 ' if a['is_hidden'] else ''}**{a['title']}** · {_source_line(a)}")
            with st.popover("수정"):
                with st.form(f"edit_news_{a['id']}"):
                    title = st.text_input("제목", value=a["title"])
                    summary = st.text_area("짧은 요약", value=a["summary"])
                    detail = st.text_area("상세 요약", value=a["summary_detail"])
                    if st.form_submit_button("저장"):
                        try:
                            ns.edit_article(a["id"], True, title=title, summary=summary, summary_detail=detail)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.toast("저장했습니다.")
                            st.rerun()
            if a["is_hidden"]:
                if st.button("숨김 해제", key=f"unhide_{a['id']}"):
                    ns.set_hidden(a["id"], False, True)
                    st.rerun()
            else:
                reason = st.text_input("숨김 사유", key=f"why_{a['id']}")
                if st.button("숨김", key=f"hide_{a['id']}"):
                    ns.set_hidden(a["id"], True, True, reason)
                    st.rerun()


def _admin_sources() -> None:
    for s in ns.list_sources():
        with st.container(border=True):
            st.markdown(f"**{s['name']}** ({s['kind']}) · 마지막 결과: **{s['last_status']}**"
                        + (f" · {format_ts(s['last_run_at'])}" if s["last_run_at"] else ""))
            if s["last_error"]:
                st.error(f"실패 {s['consecutive_failures']}회 연속: {s['last_error']}")
            if s["kind"] == "샘플":
                continue
            c1, c2, c3 = st.columns(3)
            enabled = c1.toggle("사용", value=bool(s["enabled"]), key=f"src_en_{s['id']}")
            verified = c2.toggle("이용 조건 확인함", value=bool(s["terms_verified"]), key=f"src_tv_{s['id']}",
                                 disabled=s["kind"] == "공공기관")
            if enabled != bool(s["enabled"]) or verified != bool(s["terms_verified"]):
                ns.update_source(s["id"], True, enabled=enabled, terms_verified=verified)
                st.rerun()
            if c3.button("지금 다시 수집", key=f"src_retry_{s['id']}"):
                with st.spinner("수집 중…"):
                    result = nc.run_collection(trigger="retry", source_id=s["id"])
                st.toast(str(result[0]) if result else "수집 가능한 상태가 아닙니다(사용·이용 조건 확인 필요).")
                st.rerun()
    with st.form("add_source"):
        name = st.text_input("출처 이름")
        kind = st.selectbox("종류", ["공공기관", "매체"])
        url = st.text_input("RSS/Atom 주소")
        if st.form_submit_button("출처 추가"):
            try:
                ns.add_source(name, kind, url, True)
            except Exception as exc:
                st.error(f"추가하지 못했습니다: {exc}")
            else:
                st.toast("추가했습니다. 매체는 이용 조건을 확인한 뒤 켜 주세요.")
                st.rerun()


def _admin_settings() -> None:
    cur = ns.get_settings()
    labels = {"news_top_days": "Top 5 집계 기간(일)", "news_rank_refresh_minutes": "순위 갱신 주기(분)",
              "news_view_dedup_hours": "같은 기사 중복 조회 제외(시간)", "news_per_page": "목록 한 쪽 기사 수"}
    with st.form("news_settings"):
        values = {k: st.number_input(v, min_value=1, max_value=3650, value=cur[k]) for k, v in labels.items()}
        if st.form_submit_button("저장"):
            for k, v in values.items():
                ns.set_setting(k, int(v), True)
            st.toast("설정을 저장했습니다.")
            st.rerun()
