"""SCR-08 나의 수족관 목록 — 화면. (SCR-09 도감 상세는 편성훈 담당: 아래 `_species_detail` 자리에 연결)

SCR-09 담당자가 `sea_info/scr09_dex_detail.py`에 `render_species_detail(species: str) -> None`을 만들면
이 화면이 자동으로 그 함수를 부른다. 없으면 이 파일의 임시 상세(`_fallback_detail`)를 쓴다.
"""
from __future__ import annotations

import importlib

import streamlit as st

from sea_info import bootstrap, scr06_store, scr08_store as aq, store
from sea_info.dbutil import format_ts
from sea_info.scr06_post_detail import open_post_detail


def _identity() -> tuple[str, str]:
    role = st.session_state.get("role", "guest")
    email = st.session_state.get("email", "")
    if role == "guest":
        return role, ""
    return role, email or ("운영자" if role == "admin" else "바다탐험가")


def render() -> None:
    bootstrap.ensure_once()
    role, user = _identity()
    st.caption("SCR-08 · Sea-Info Agent")
    st.title("나의 수족관")
    if role == "guest":
        st.info("나의 수족관은 로그인한 회원만 이용할 수 있습니다. 로그인하면 관찰 기록이 자동으로 모입니다.")
        st.page_link("pages/login.py", label="로그인 / 회원가입", icon="👤")
        return

    repaired = aq.sync_user(user)
    if repaired["created"] or repaired["parents_restored"]:
        st.info(f"어긋난 도감 기록 {repaired['created'] + repaired['parents_restored']}건을 복구했습니다.")

    current = st.session_state.get("aquarium_species")
    if current:
        if st.button("← 목록으로", key="aq_back"):
            st.session_state.pop("aquarium_species", None)
            st.rerun()
        _species_detail(current, user)
        return
    _render_list(user)


def _render_list(user: str) -> None:
    summary = aq.summary(user)
    a, b, c = st.columns(3)
    a.metric("수집한 생물", f"{summary['collected_species']} / {summary['master_species']}종")
    b.metric("관찰 기록", f"{summary['total_records']}건")
    c.metric("이름 확인 필요", f"{summary['unidentified_records']}건")
    if summary["master_species"]:
        st.progress(min(1.0, summary["collected_species"] / summary["master_species"]))

    search = st.text_input("생물 이름 검색", key="aq_search", placeholder="예: 불가사리")
    items = aq.list_aquarium(user, search)
    if not items:
        if search.strip():
            st.warning("검색 결과가 없습니다.")
        else:
            st.info("아직 기록한 생물이 없습니다. 생물을 알아보고 관찰 게시물을 등록하면 이곳에 자동으로 추가됩니다.")
            l, r = st.columns(2)
            l.page_link("pages/explore.py", label="사진으로 생물 알아보기", icon="🔎")
            r.page_link("pages/community.py", label="관찰 게시물 쓰기", icon="📝")
    cols = st.columns(3)
    for i, item in enumerate(items):
        with cols[i % 3], st.container(border=True):
            st.markdown(f"### {item['emoji']} {item['species']}")
            st.markdown(":green[공개]" if item["is_public"] else ":gray[비공개]")
            st.caption(f"관찰 {item['record_count']}건 · 최근 {format_ts(item['last_observed'])[:10]}")
            if item["is_unidentified"]:
                st.caption("이름을 확인하면 다른 생물로 옮길 수 있습니다.")
            st.caption(f"공개 게시물 {item['public_posts']}건 · 공개 사진 {item['public_photos']}건"
                       + (f" · 삭제된 글 {item['deleted_posts']}건" if item["deleted_posts"] else ""))
            if st.button("도감 상세 · SCR-09", key=f"aq_open_{item['species']}"):
                st.session_state["aquarium_species"] = item["species"]
                st.rerun()

    master = aq.species_master()
    owned = {i["species"] for i in aq.list_aquarium(user)}
    missing = [m for m in master.values() if m["name"] not in owned]
    if missing:
        with st.expander(f"🔒 아직 만나지 못한 생물 {len(missing)}종"):
            st.write(" · ".join(f"{m['emoji']} {m['name']}" for m in missing))


def _species_detail(species: str, user: str) -> None:
    try:
        module = importlib.import_module("sea_info.scr09_dex_detail")
        return module.render_species_detail(species)
    except ModuleNotFoundError as exc:
        if exc.name != "sea_info.scr09_dex_detail":
            raise
    _fallback_detail(species, user)


def _fallback_detail(species: str, user: str) -> None:
    """SCR-09 담당자의 화면이 들어오기 전까지 쓰는 임시 상세."""
    records = aq.list_records(user, species)
    if not records:
        st.warning("이 생물의 도감 기록을 찾을 수 없습니다.")
        return
    info = aq.species_info(species)
    with st.container(border=True):
        st.subheader(f"{info['emoji']} {species} · 나의 바다 도감")
        if info["scientific"]:
            st.caption(info["scientific"])
        if info["habitat"]:
            st.write(f"**서식지** {info['habitat']}")
            st.write(f"**먹이** {info['diet']}")
        st.write(info["summary"])
    st.markdown("##### 관찰 기록")
    master_names = [n for n in aq.species_master() if n != species]
    for rec in records:
        with st.container(border=True):
            tag = " · 게시물 삭제됨(나에게만 보임)" if rec["post_deleted"] else ""
            st.write(f"{format_ts(rec['observed_at'])[:10]} · {rec['title']} · {rec['region']}{tag}")
            c1, c2 = st.columns([1, 3])
            if not rec["post_deleted"] and c1.button("게시물 보기", key=f"aq_post_{rec['observation_id']}"):
                open_post_detail(rec["observation_id"], return_page="pages/aquarium.py", return_label="나의 수족관",
                                 keep_keys=("aquarium_species",))
            if species == aq.UNIDENTIFIED:
                with c2:
                    target = st.selectbox("이 생물의 이름", master_names, key=f"aq_rc_{rec['observation_id']}")
                    if st.button("이름 바꾸기", key=f"aq_rcb_{rec['observation_id']}"):
                        aq.reclassify_record(user, rec["observation_id"], target)
                        st.session_state.pop("aquarium_species", None)
                        st.toast(f"{target}(으)로 옮겼습니다.")
                        st.rerun()

    is_public = st.toggle("다른 사용자의 공개 도감에 표시", value=store.aquarium_is_public(user, species), key=f"aq_pub_{species}")
    if is_public != store.aquarium_is_public(user, species):
        store.set_aquarium_public(user, species, is_public)
        st.rerun()
    st.caption("게시물 공개와 사진 공개는 각각 따로 검사됩니다. 공개 도감에는 이 토글을 켠 생물만 보입니다.")
    with st.expander("동의 · 삭제 관리"):
        sure = st.checkbox("이 생물 사진의 공개 동의를 철회합니다(사진은 나에게만 보입니다).", key=f"aq_wd_{species}")
        if st.button("사진 공개 동의 철회", key=f"aq_wdb_{species}", disabled=not sure):
            st.toast(f"사진 {aq.make_photos_private(user, species)}건을 비공개로 바꿨습니다.")
            st.rerun()
        st.markdown("---")
        gone = st.checkbox("도감에서 이 생물을 삭제합니다(게시물은 그대로 남습니다).", key=f"aq_del_{species}")
        if st.button("도감에서 삭제", key=f"aq_delb_{species}", disabled=not gone):
            aq.dismiss_species(user, species)
            st.session_state.pop("aquarium_species", None)
            st.toast("도감에서 삭제했습니다.")
            st.rerun()
