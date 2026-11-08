import pytest
from conftest import make_post
from sea_info import scr06_store as s6, store


def test_접근권한_비공개와_숨김(dbp):
    pid = make_post(dbp, "alice", is_public=False)
    p = s6.get_post(pid, dbp)
    assert s6.check_access(p, "alice", "member")[0]
    assert s6.check_access(p, "root", "admin")[0]
    ok, msg = s6.check_access(p, "bob", "member")
    assert not ok and "비공개" in msg
    ok, _ = s6.check_access(p, "", "guest")
    assert not ok


def test_접근권한_운영하지_않는_게시판(dbp):
    p = s6.get_post(make_post(dbp, "alice"), dbp)
    assert not s6.check_access(p, "bob", "member", board_enabled=False)[0]
    assert s6.check_access(p, "root", "admin", board_enabled=False)[0]


def test_사진은_게시물공개와_사진동의_둘_다_있어야_타인에게_보인다(dbp):
    p1 = s6.get_post(make_post(dbp, "alice", photo=b"img", public_photo=True), dbp)
    assert s6.photo_visible(p1, "bob", "member")
    assert s6.photo_visible(p1, "", "guest")
    p2 = s6.get_post(make_post(dbp, "alice", photo=b"img", public_photo=False), dbp)  # 동의 없으면 저장 안 됨
    assert not s6.photo_visible(p2, "bob", "member")
    # 철회 후: blob은 남아 있고 본인만 본다
    pid = make_post(dbp, "alice", photo=b"img", public_photo=True)
    s6.update_post(pid, "alice", is_admin=False, title="t", body="b", location_visibility="비공개",
                   is_public=True, photo_public=False, path=dbp)
    p3 = s6.get_post(pid, dbp)
    assert s6.photo_visible(p3, "alice", "member") and not s6.photo_visible(p3, "bob", "member")


def test_위치_비공개는_본인만(dbp):
    p = s6.get_post(make_post(dbp, "alice", region="제주", visibility="비공개"), dbp)
    assert s6.location_for_viewer(p, "bob", "member") is None
    assert s6.location_for_viewer(p, "root", "admin") is None
    assert s6.location_for_viewer(p, "alice", "member")["precision"] == "owner"


def test_위치_대략공개는_좌표를_뭉갠다(dbp):
    pid = make_post(dbp, "alice", region="제주", visibility="대략 공개")
    with s6.db(dbp) as con:
        con.execute("UPDATE observations SET latitude=33.48721, longitude=126.51234 WHERE id=?", (pid,))
    loc = s6.location_for_viewer(s6.get_post(pid, dbp), "bob", "member")
    assert (loc["lat"], loc["lon"]) == (33.5, 126.5) and loc["precision"] == "approx"


def test_위치_정확공개_좌표_없으면_지역중심과_안내(dbp):
    p = s6.get_post(make_post(dbp, "alice", region="부산", visibility="정확 공개"), dbp)
    loc = s6.location_for_viewer(p, "bob", "member")
    assert loc["precision"] == "region" and loc["note"] and loc["lat"] is not None


def test_위치_기록하지_않음이면_None(dbp):
    p = s6.get_post(make_post(dbp, "alice", region="기록하지 않음", visibility="비공개"), dbp)
    assert s6.location_for_viewer(p, "alice", "member") is None


def test_댓글과_답글과_삭제(dbp):
    pid = make_post(dbp, "alice")
    c1 = s6.add_comment(pid, "bob", "첫 댓글", path=dbp)
    r1 = s6.add_comment(pid, "alice", "답글", parent_id=c1, path=dbp)
    r2 = s6.add_comment(pid, "bob", "답글에 답글", parent_id=r1, path=dbp)  # 같은 묶음에 붙는다
    tree = s6.list_comments(pid, "carol", "member", dbp)
    assert len(tree) == 1 and [r["id"] for r in tree[0]["replies"]] == [r1, r2]
    assert s6.count_comments(pid, dbp) == 3
    with pytest.raises(PermissionError):
        s6.delete_comment(c1, "carol", path=dbp)
    s6.delete_comment(c1, "bob", path=dbp)
    tree = s6.list_comments(pid, "carol", "member", dbp)
    assert tree[0]["state"] == "deleted" and tree[0]["text"] == "삭제된 댓글입니다." and len(tree[0]["replies"]) == 2
    with pytest.raises(ValueError):
        s6.add_comment(pid, "bob", "삭제된 댓글에 답글", parent_id=c1, path=dbp)


def test_댓글_검증(dbp):
    pid = make_post(dbp, "alice")
    with pytest.raises(ValueError):
        s6.add_comment(pid, "bob", "   ", path=dbp)
    with pytest.raises(ValueError):
        s6.add_comment(pid, "bob", "가" * 501, path=dbp)
    with pytest.raises(PermissionError):
        s6.add_comment(pid, "", "비회원", path=dbp)
    other = make_post(dbp, "alice", title="다른 글")
    c = s6.add_comment(other, "bob", "다른 글 댓글", path=dbp)
    with pytest.raises(ValueError):
        s6.add_comment(pid, "bob", "엉뚱한 부모", parent_id=c, path=dbp)


def test_신고_중복_본인_사유_검증(dbp):
    pid = make_post(dbp, "alice")
    assert s6.report_content("observation", pid, "bob", "스팸·광고", path=dbp)["report_count"] == 1
    with pytest.raises(s6.DuplicateReport):
        s6.report_content("observation", pid, "bob", "기타", path=dbp)
    with pytest.raises(ValueError):
        s6.report_content("observation", pid, "alice", "기타", path=dbp)
    with pytest.raises(ValueError):
        s6.report_content("observation", pid, "carol", "없는사유", path=dbp)
    with pytest.raises(PermissionError):
        s6.report_content("observation", pid, "", "기타", path=dbp)


def test_신고가_기준에_닿으면_임시숨김_운영자가_복원(dbp):
    pid = make_post(dbp, "alice")
    for u in ("u1", "u2"):
        assert s6.report_content("observation", pid, u, "스팸·광고", hide_threshold=3, path=dbp)["hidden"] is False
    assert s6.report_content("observation", pid, "u3", "스팸·광고", hide_threshold=3, path=dbp)["hidden"] is True
    p = s6.get_post(pid, dbp)
    assert p["is_hidden"] == 1
    assert not s6.check_access(p, "bob", "member")[0]
    assert s6.check_access(p, "alice", "member")[0]  # 작성자는 본다
    assert pid not in [x["id"] for x in s6.list_visible_observations("bob", "member", dbp)]
    assert s6.report_queue(dbp)[0]["reporters"] == 3
    with pytest.raises(PermissionError):
        s6.review_reports("observation", pid, "restore", "bob", is_admin=False, path=dbp)
    s6.review_reports("observation", pid, "restore", "root", is_admin=True, path=dbp)
    assert s6.get_post(pid, dbp)["is_hidden"] == 0 and s6.report_queue(dbp) == []
    # 기각된 신고는 다시 세지 않는다: 새 신고 2건으로는 숨겨지지 않음
    for u in ("n1", "n2"):
        r = s6.report_content("observation", pid, u, "기타", hide_threshold=3, path=dbp)
    assert r["hidden"] is False


def test_댓글_신고와_숨김(dbp):
    pid = make_post(dbp, "alice")
    cid = s6.add_comment(pid, "bob", "나쁜 말", path=dbp)
    for u in ("u1", "u2"):
        s6.report_content("comment", cid, u, "욕설·혐오 표현", hide_threshold=2, path=dbp)
    other = s6.list_comments(pid, "carol", "member", dbp)[0]
    assert other["state"] == "hidden" and "나쁜 말" not in other["text"]
    own = s6.list_comments(pid, "bob", "member", dbp)[0]
    assert own["state"] == "hidden_visible" and own["text"] == "나쁜 말"


def test_수정_권한과_변경항목과_동의이력(dbp):
    pid = make_post(dbp, "alice", photo=b"img", public_photo=True)
    with pytest.raises(PermissionError):
        s6.update_post(pid, "bob", is_admin=False, title="x", body="y", location_visibility="비공개", is_public=True, path=dbp)
    changed = s6.update_post(pid, "alice", is_admin=False, title="새 제목", body="내용", location_visibility="대략 공개",
                             is_public=True, photo_public=False, path=dbp)
    assert set(changed) == {"제목", "위치 공개", "사진 공개"}
    with s6.db(dbp) as con:
        rows = con.execute("SELECT consent_type, enabled FROM consent_history WHERE observation_id=? "
                           "AND consent_type='public_photo' ORDER BY id", (pid,)).fetchall()
    assert [tuple(r) for r in rows][-1] == ("public_photo", 0)
    assert s6.update_post(pid, "root", is_admin=True, title="새 제목", body="내용", location_visibility="대략 공개",
                          is_public=True, photo_public=False, path=dbp) == []


def test_수정_검증(dbp):
    pid = make_post(dbp, "alice", region="기록하지 않음")
    base = dict(is_admin=False, title="t", body="b", is_public=True, path=dbp)
    with pytest.raises(ValueError):
        s6.update_post(pid, "alice", location_visibility="정확 공개", **base)
    with pytest.raises(ValueError):
        s6.update_post(pid, "alice", location_visibility="없는값", **base)
    with pytest.raises(ValueError):
        s6.update_post(pid, "alice", location_visibility="비공개", photo_public=True, **base)  # 사진 없음
    with pytest.raises(ValueError):
        s6.update_post(pid, "alice", location_visibility="비공개", **{**base, "title": " "})


def test_게시물을_비공개로_바꾸면_사진공개도_꺼진다(dbp):
    pid = make_post(dbp, "alice", photo=b"img", public_photo=True)
    changed = s6.update_post(pid, "alice", is_admin=False, title="t", body="b", location_visibility="비공개",
                             is_public=False, path=dbp)
    assert "게시물 공개" in changed and "사진 공개" in changed
    assert s6.get_post(pid, dbp)["photo_public_consent"] == 0


def test_삭제_권한과_연쇄정리(dbp):
    pid = make_post(dbp, "alice")
    cid = s6.add_comment(pid, "bob", "댓글", path=dbp)
    s6.report_content("comment", cid, "u1", "기타", path=dbp)
    s6.report_content("observation", pid, "u1", "기타", path=dbp)
    with pytest.raises(PermissionError):
        s6.delete_post(pid, "bob", path=dbp)
    s6.delete_post(pid, "alice", path=dbp)
    assert s6.get_post(pid, dbp) is None
    assert s6.count_comments(pid, dbp) == 0
    assert s6.report_queue(dbp) == []


def test_공감은_사용자당_한번(dbp):
    pid = make_post(dbp, "alice")
    assert s6.toggle_like(pid, "bob", dbp) is True and s6.has_liked(pid, "bob", dbp)
    assert s6.get_post(pid, dbp)["likes"] == 1
    assert s6.toggle_like(pid, "bob", dbp) is False
    assert s6.get_post(pid, dbp)["likes"] == 0
    with pytest.raises(PermissionError):
        s6.toggle_like(pid, "", dbp)


def test_삭제하면_포인트_회수(dbp):
    pid = store.create_observation(title="t", body="b", species="문어", author="alice", region="제주",
                                   visibility="비공개", public_photo=False, operator_photo=False,
                                   post_points=10, daily_points_cap=50, path=dbp)
    assert store.get_points("alice", dbp) == 10
    s6.delete_post(pid, "alice", path=dbp)
    assert store.get_points("alice", dbp) == 0
