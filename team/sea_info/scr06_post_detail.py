"""SCR-06 관찰 게시물 상세 — 화면.

다른 화면에서 여는 방법 (SCR-01 홈, SCR-05 게시판 목록 담당자용):

    from sea_info.scr06_post_detail import open_post_detail
    if st.button("자세히 보기", key=f"open_{post['id']}"):
        open_post_detail(post["id"], return_page="pages/community.py", return_label="커뮤니티")

돌아가기를 누르면 return_page로 가면서 keep_keys에 적은 session_state 값(기본: 게시판 탭)을 되돌려 준다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from sea_info import bootstrap, scr06_store as s6, scr08_store, store
from sea_info.dbutil import format_ts
from sea_info.safe_ui import safe_map

DETAIL_PAGE = "pages/post_detail.py"
DEFAULT_RETURN = {"page": "pages/community.py", "label": "커뮤니티", "state": {}}


# ------------------------------------------------------------------ 진입·복귀
def open_post_detail(post_id: int, return_page: str = "pages/community.py", return_label: str = "커뮤니티",
                     keep_keys: tuple[str, ...] = ("board_type",)) -> None:
    st.session_state["selected_post_id"] = int(post_id)
    st.session_state["detail_return"] = {
        "page": return_page, "label": return_label,
        "state": {k: st.session_state[k] for k in keep_keys if k in st.session_state},
    }
    st.switch_page(DETAIL_PAGE)


def _go_back(ret: dict[str, Any]) -> None:
    for key, value in ret.get("state", {}).items():
        st.session_state[key] = value
    st.switch_page(ret.get("page", DEFAULT_RETURN["page"]))


# ------------------------------------------------------------------ 도우미
def _identity() -> tuple[str, str]:
    """(role, user_id). screens.identity()와 같은 규칙. 비회원의 user_id는 빈 문자열."""
    role = st.session_state.get("role", "guest")
    email = st.session_state.get("email", "")
    if role == "guest":
        return role, ""
    return role, email or ("운영자" if role == "admin" else "바다탐험가")


def _author_label(author: str, user: str) -> str:
    if user and author == user and st.session_state.get("nickname"):
        character = str(st.session_state.get("character", "🐠 흰동가리")).split(" ")[0]
        return f"{character} {st.session_state['nickname']}"
    return f"🐚 {author.split('@')[0]}"


def _hide_threshold() -> int:
    return int(st.session_state.get("settings", {}).get("moderation", {}).get("hide_threshold", s6.DEFAULT_HIDE_THRESHOLD))


def _login_hint() -> None:
    st.page_link("pages/login.py", label="로그인 후 이용할 수 있습니다", icon="👤")


# ------------------------------------------------------------------ 화면
def render() -> None:
    bootstrap.ensure_once()
    role, user = _identity()
    ret = st.session_state.get("detail_return", DEFAULT_RETURN)
    st.caption("SCR-06 · Sea-Info Agent")
    if st.button(f"← {ret['label']}(으)로 돌아가기", key="detail_back"):
        _go_back(ret)

    post_id = st.session_state.get("selected_post_id")
    if post_id is None:
        raw = st.query_params.get("post")
        post_id = int(raw) if raw and str(raw).isdigit() else None
    if post_id is None:
        st.info("열어 볼 관찰 게시물을 선택해 주세요.")
        st.page_link("pages/community.py", label="커뮤니티로 가기", icon="📝")
        return

    post = s6.get_post(int(post_id))
    if post is None:
        st.warning("게시물을 찾을 수 없습니다. 삭제되었을 수 있습니다.")
        return
    board_enabled = st.session_state.get("board_status", {}).get(post["board_type"], True)
    ok, message = s6.check_access(post, user, role, board_enabled)
    if not ok:
        st.title("열람할 수 없는 게시물")
        st.info(message)
        return

    is_owner = bool(user) and post["author"] == user
    is_admin = role == "admin"
    interactions_on = board_enabled or is_admin

    if post["is_hidden"]:
        st.warning(f"신고가 누적되어 임시 숨김 상태입니다. 다른 사용자에게는 보이지 않습니다. ({post.get('hidden_reason') or '사유 없음'})")
    elif not post["is_public"]:
        st.info("나만 볼 수 있는 비공개 게시물입니다.")

    _render_body(post, user, role)
    _render_location(post, user, role)
    _render_reactions(post, user, role, interactions_on)
    st.divider()
    _render_comments(post, user, role, interactions_on)
    if is_owner or is_admin:
        _render_edit_delete(post, user, role, ret)
    if is_admin:
        _render_admin_review(post, user)


def _render_body(post: dict[str, Any], user: str, role: str) -> None:
    info = scr08_store.species_info(post["species"])
    if s6.photo_visible(post, user, role):
        st.image(post["photo_blob"], width="stretch")
        if not (post["is_public"] and post["photo_public_consent"]):
            st.caption("🔒 이 사진은 공개되지 않았습니다. 작성자와 운영자에게만 보입니다.")
    st.caption(f"{info['emoji']} {post['species'] or '미확인'} · {post['board_type']}")
    st.title(post["title"])

    left, right = st.columns([2, 3])
    label = _author_label(post["author"], user)
    if left.button(label, key="author_link", help="작성자가 공개한 도감 보기"):
        st.session_state["public_profile_author"] = post["author"]
        if Path("pages/author_profile.py").exists():  # SCR-07 담당자가 만든 화면이 있으면 그쪽으로
            st.switch_page("pages/author_profile.py")
        st.session_state["show_author_panel"] = not st.session_state.get("show_author_panel", False)
    right.caption(f"작성 {format_ts(post['created_at'])}")
    if st.session_state.get("show_author_panel"):
        _render_author_panel(post["author"])
    st.write(post["body"])


def _render_author_panel(author: str) -> None:
    public_posts = [p for p in store.observations() if p["author"] == author and p["is_public"] and not p.get("is_hidden")]
    dex = store.public_species(author)
    with st.container(border=True):
        st.markdown(f"**{author.split('@')[0]} 님의 공개 도감**")
        st.write(f"공개 관찰 {len(public_posts)}건 · 공개 도감 {len(dex)}종")
        st.write(" · ".join(dex) if dex else "공개한 도감이 없습니다.")
        st.caption("비공개 관찰과 나의 수족관 전체는 공개하지 않습니다.")


def _render_location(post: dict[str, Any], user: str, role: str) -> None:
    loc = s6.location_for_viewer(post, user, role)
    if loc is None:
        if post.get("region") not in ("", s6.NO_REGION):
            st.caption("📍 관찰 위치는 작성자가 공개하지 않았습니다.")
        return
    st.markdown(f"##### 📍 관찰 위치 · {loc['label']}")
    if loc["lat"] is not None:
        safe_map(loc["lat"], loc["lon"], zoom=8 if loc["precision"] == "approx" else 10, size=2000)
    if loc["note"]:
        st.caption(loc["note"])


def _render_reactions(post: dict[str, Any], user: str, role: str, interactions_on: bool) -> None:
    c1, c2, c3 = st.columns([1.3, 1, 3])
    if role == "guest":
        c1.write(f"♡ 공감 {post['likes']}")
        with c3:
            _login_hint()
        return
    if not interactions_on:
        c1.write(f"♡ 공감 {post['likes']}")
        c3.caption("이 게시판은 현재 공감·댓글을 받지 않습니다.")
        return
    liked = s6.has_liked(post["id"], user)
    if c1.button(f"{'♥ 공감 취소' if liked else '♡ 공감'} {post['likes']}", key=f"like_{post['id']}"):
        s6.toggle_like(post["id"], user)
        st.rerun()
    if post["author"] != user:
        with c2.popover("🚩 신고"):
            _report_form("observation", post["id"], user)


def _report_form(target_type: str, target_id: int, user: str) -> None:
    key = f"{target_type}_{target_id}"
    reason = st.selectbox("신고 사유", s6.REPORT_REASONS, key=f"rr_{key}")
    detail = st.text_area("자세한 내용(선택)", max_chars=300, key=f"rd_{key}")
    if st.button("신고 접수", key=f"rs_{key}"):
        try:
            result = s6.report_content(target_type, target_id, user, reason, detail, _hide_threshold())
        except s6.DuplicateReport:
            st.warning("이미 신고하셨습니다.")
        except (ValueError, PermissionError) as exc:
            st.error(str(exc))
        else:
            st.toast("신고가 접수되었습니다. 운영자가 검토합니다." + (" 신고 누적으로 임시 숨김 처리되었습니다." if result["hidden"] else ""))
            st.rerun()


# ------------------------------------------------------------------ 댓글
def _render_comments(post: dict[str, Any], user: str, role: str, interactions_on: bool) -> None:
    st.subheader(f"댓글 {s6.count_comments(post['id'])}")
    tree = s6.list_comments(post["id"], user, role)
    if not tree:
        st.caption("아직 댓글이 없습니다.")
    for c in tree:
        _render_comment(post, c, user, role, interactions_on, is_reply=False)
        for r in c["replies"]:
            _render_comment(post, r, user, role, interactions_on, is_reply=True)
    if role == "guest":
        _login_hint()
    elif interactions_on:
        with st.form(f"new_comment_{post['id']}", clear_on_submit=True):
            body = st.text_area("댓글 쓰기", max_chars=s6.MAX_COMMENT_LEN, key=f"new_comment_text_{post['id']}")
            if st.form_submit_button("댓글 등록"):
                try:
                    s6.add_comment(post["id"], user, body)
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
                else:
                    st.toast("댓글을 등록했습니다.")
                    st.rerun()


def _render_comment(post: dict[str, Any], c: dict[str, Any], user: str, role: str, interactions_on: bool,
                    is_reply: bool) -> None:
    pad, body = st.columns([1, 14]) if is_reply else (None, st.container())
    box = body if not is_reply else body
    with box:
        with st.container(border=True):
            head = f"{'↳ ' if is_reply else ''}**{_author_label(c['author'], user)}** · {format_ts(c['created_at'])}"
            st.markdown(head)
            if c["state"] in ("deleted", "hidden"):
                st.caption(c["text"])
            else:
                if c["state"] == "hidden_visible":
                    st.caption("⚠️ 신고 누적으로 다른 사용자에게는 숨겨진 댓글입니다.")
                st.write(c["text"])
            actions = st.columns(4)
            if role != "guest" and interactions_on and c["state"] != "deleted":
                with actions[0].popover("답글"):
                    with st.form(f"reply_form_{c['id']}", clear_on_submit=True):
                        text = st.text_area("답글", max_chars=s6.MAX_COMMENT_LEN, key=f"reply_text_{c['id']}")
                        if st.form_submit_button("답글 등록"):
                            try:
                                s6.add_comment(post["id"], user, text, parent_id=c["id"])
                            except (ValueError, PermissionError) as exc:
                                st.error(str(exc))
                            else:
                                st.toast("답글을 등록했습니다.")
                                st.rerun()
            if c["can_delete"]:
                with actions[1].popover("삭제"):
                    st.write("이 댓글을 삭제할까요?")
                    if st.button("삭제 확인", key=f"cdel_{c['id']}"):
                        s6.delete_comment(c["id"], user, is_admin=role == "admin")
                        st.toast("댓글을 삭제했습니다.")
                        st.rerun()
            if c["can_report"] and interactions_on:
                with actions[2].popover("🚩"):
                    _report_form("comment", c["id"], user)
            if role == "admin" and c["state"] == "hidden_visible":
                with actions[3].popover("검토"):
                    _review_buttons("comment", c["id"], user)


# ------------------------------------------------------------------ 수정·삭제
def _render_edit_delete(post: dict[str, Any], user: str, role: str, ret: dict[str, Any]) -> None:
    has_photo = post["photo_blob"] is not None
    with st.expander("✏️ 수정 · 삭제"):
        with st.form(f"edit_form_{post['id']}"):
            title = st.text_input("제목", value=post["title"])
            body = st.text_area("관찰 이야기", value=post["body"], height=140)
            location = st.selectbox("위치 공개", s6.LOCATION_LEVELS, index=s6.LOCATION_LEVELS.index(post["location_visibility"]))
            is_public = st.checkbox("게시물을 커뮤니티에 공개", value=bool(post["is_public"]))
            photo_public = None
            if has_photo:
                photo_public = st.checkbox("첨부 사진을 다른 사용자에게 공개", value=bool(post["photo_public_consent"]))
                st.caption("사진 공개를 끄면 사진은 나에게만 보입니다. 변경 내용은 동의 이력에 기록됩니다.")
            if st.form_submit_button("수정 저장", type="primary"):
                try:
                    changed = s6.update_post(post["id"], user, is_admin=role == "admin", title=title, body=body,
                                             location_visibility=location, is_public=is_public, photo_public=photo_public)
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
                else:
                    st.toast("변경: " + ", ".join(changed) if changed else "바뀐 내용이 없습니다.")
                    st.rerun()
        st.markdown("---")
        st.caption("게시물을 삭제해도 나의 수족관 도감 기록은 나에게만 보이도록 남습니다.")
        confirmed = st.checkbox("이 게시물을 삭제하겠습니다.", key=f"del_confirm_{post['id']}")
        if st.button("게시물 삭제", key=f"del_{post['id']}", disabled=not confirmed):
            try:
                s6.delete_post(post["id"], user, is_admin=role == "admin")
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("selected_post_id", None)
                st.toast("게시물을 삭제했습니다.")
                _go_back(ret)


# ------------------------------------------------------------------ 운영자 검토
def _review_buttons(target_type: str, target_id: int, reviewer: str) -> None:
    c1, c2 = st.columns(2)
    if c1.button("숨김 유지(확정)", key=f"keep_{target_type}_{target_id}"):
        s6.review_reports(target_type, target_id, "keep_hidden", reviewer, is_admin=True)
        st.rerun()
    if c2.button("숨김 해제(신고 기각)", key=f"restore_{target_type}_{target_id}"):
        s6.review_reports(target_type, target_id, "restore", reviewer, is_admin=True)
        st.rerun()


def _render_admin_review(post: dict[str, Any], reviewer: str) -> None:
    reports = s6.list_reports("observation", post["id"])
    with st.expander(f"🛡️ 운영자 검토 · 신고 {len(reports)}건", expanded=bool(post["is_hidden"])):
        if not reports:
            st.caption("접수된 신고가 없습니다.")
        for r in reports:
            st.write(f"[{r['status']}] {r['reason']} · {format_ts(r['created_at'])}" + (f" — {r['detail']}" if r["detail"] else ""))
        if reports:
            _review_buttons("observation", post["id"], reviewer)
