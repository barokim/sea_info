"""SCR-06 관찰 게시물 상세 — 데이터 계층 (SQLite).

화면(UI) 코드는 SQL을 직접 쓰지 않고 이 모듈의 함수만 부른다.
나중에 FastAPI로 옮길 때 이 함수들이 그대로 엔드포인트 본문이 된다.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from sea_info import scr08_store, store
from sea_info.dbutil import add_column, db, now

LOCATION_LEVELS = ("비공개", "대략 공개", "정확 공개")
NO_REGION = "기록하지 않음"
REPORT_REASONS = ["스팸·광고", "욕설·혐오 표현", "개인정보 노출", "허위·잘못된 정보", "부적절한 사진", "기타"]
DEFAULT_HIDE_THRESHOLD = 3
MAX_COMMENT_LEN = 500
# 좌표가 저장되지 않은 글의 지도 표시용 지역 중심점
REGION_CENTERS = {
    "제주": (33.4996, 126.5312), "부산": (35.1796, 129.0756), "강릉": (37.7519, 128.8761),
    "인천": (37.4563, 126.7052), "속초": (38.2070, 128.5918), "여수": (34.7604, 127.6622),
}


class DuplicateReport(Exception):
    """같은 사용자가 같은 대상을 다시 신고했을 때."""


def ensure_schema(path: str | None = None) -> None:
    scr08_store.ensure_schema(path)
    with db(path) as con:
        add_column(con, "observations", "is_hidden", "INTEGER NOT NULL DEFAULT 0")
        add_column(con, "observations", "hidden_reason", "TEXT")
        add_column(con, "observations", "hidden_at", "TEXT")
        add_column(con, "observations", "latitude", "REAL")
        add_column(con, "observations", "longitude", "REAL")
        add_column(con, "comments", "parent_id", "INTEGER")
        add_column(con, "comments", "is_hidden", "INTEGER NOT NULL DEFAULT 0")
        add_column(con, "comments", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL CHECK (target_type IN ('observation','comment')),
                target_id INTEGER NOT NULL,
                reporter TEXT NOT NULL,
                reason TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '접수' CHECK (status IN ('접수','숨김 확정','기각')),
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT,
                UNIQUE (target_type, target_id, reporter)
            );
            CREATE INDEX IF NOT EXISTS idx_content_reports_target ON content_reports(target_type, target_id, status);
            """
        )


# ------------------------------------------------------------------ 조회·접근
def get_post(post_id: int, path: str | None = None) -> dict[str, Any] | None:
    with db(path) as con:
        row = con.execute("SELECT * FROM observations WHERE id=?", (post_id,)).fetchone()
    return dict(row) if row else None


def check_access(post: dict[str, Any], viewer: str, role: str, board_enabled: bool = True) -> tuple[bool, str]:
    """이 사용자가 글을 볼 수 있는지와, 못 볼 때 보여 줄 안내 문구."""
    if role == "admin" or (viewer and post["author"] == viewer):
        return True, ""
    if post.get("is_hidden"):
        return False, "신고가 접수되어 운영자 검토 중인 게시물입니다."
    if not post.get("is_public"):
        return False, "작성자가 비공개로 설정한 게시물입니다."
    if not board_enabled:
        return False, "현재 운영하지 않는 게시판의 게시물입니다."
    return True, ""


def photo_visible(post: dict[str, Any], viewer: str, role: str) -> bool:
    """사진은 (게시물 공개 + 사진 공개 동의)일 때만 타인에게 보인다. 작성자·운영자는 항상."""
    if not post.get("photo_blob"):
        return False
    if role == "admin" or (viewer and post["author"] == viewer):
        return True
    return bool(post.get("is_public")) and bool(post.get("photo_public_consent"))


def location_for_viewer(post: dict[str, Any], viewer: str, role: str) -> dict[str, Any] | None:
    """위치 공개 정책에 따라 이 사용자에게 보여 줄 위치. 보여 줄 게 없으면 None.

    - 비공개: 작성자 본인만(운영자에게도 좌표를 주지 않는다).
    - 대략 공개: 좌표를 소수 첫째 자리(약 10km)로 뭉개서 전달한다. 원본 좌표는 내보내지 않는다.
    - 정확 공개: 저장된 좌표. 좌표가 없으면 지역 중심점을 쓰고 그 사실을 알린다.
    """
    region = post.get("region") or ""
    if region in ("", NO_REGION):
        return None
    level = post.get("location_visibility") or "비공개"
    is_owner = bool(viewer) and post["author"] == viewer
    lat, lon = post.get("latitude"), post.get("longitude")
    has_exact = lat is not None and lon is not None
    center = REGION_CENTERS.get(region)
    point = (lat, lon) if has_exact else center

    if level == "비공개":
        if not is_owner:
            return None
        return {"label": f"{region} (나에게만 보임)", "lat": point[0] if point else None,
                "lon": point[1] if point else None, "precision": "owner",
                "note": "위치 공개가 꺼져 있어 다른 사용자에게는 보이지 않습니다."}
    if level == "대략 공개":
        return {"label": f"{region} 부근", "lat": round(point[0], 1) if point else None,
                "lon": round(point[1], 1) if point else None, "precision": "approx",
                "note": "대략적인 위치(반경 약 10km)만 공개됩니다."}
    return {"label": region, "lat": point[0] if point else None, "lon": point[1] if point else None,
            "precision": "exact" if has_exact else "region",
            "note": "" if has_exact else "정확한 좌표가 등록되지 않아 지역 중심으로 표시합니다."}


def list_visible_observations(viewer: str, role: str, path: str | None = None) -> list[dict[str, Any]]:
    """목록 화면(SCR-01/05)이 쓰는 함수: 숨김·비공개 글을 권한에 맞게 걸러서 돌려준다."""
    ensure_schema(path)
    with db(path) as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM observations ORDER BY id DESC")]
    result = []
    for p in rows:
        ok, _ = check_access(p, viewer, role)
        if ok:
            result.append(p)
    return result


# ------------------------------------------------------------------ 공감
def has_liked(post_id: int, user_id: str, path: str | None = None) -> bool:
    with db(path) as con:
        return con.execute("SELECT 1 FROM observation_likes WHERE observation_id=? AND user_id=?",
                           (post_id, user_id)).fetchone() is not None


def toggle_like(post_id: int, user_id: str, path: str | None = None) -> bool:
    """공감 토글(사용자당 1개). 공감 상태가 되면 True."""
    if not user_id:
        raise PermissionError("로그인이 필요합니다.")
    return store.toggle_like(post_id, user_id, path)


# ------------------------------------------------------------------ 댓글·답글
def add_comment(post_id: int, author: str, body: str, parent_id: int | None = None,
                path: str | None = None) -> int:
    body = (body or "").strip()
    if not author:
        raise PermissionError("로그인이 필요합니다.")
    if not body:
        raise ValueError("댓글 내용을 입력해 주세요.")
    if len(body) > MAX_COMMENT_LEN:
        raise ValueError(f"댓글은 {MAX_COMMENT_LEN}자 이하로 써 주세요.")
    with db(path) as con:
        if con.execute("SELECT 1 FROM observations WHERE id=?", (post_id,)).fetchone() is None:
            raise ValueError("게시물을 찾을 수 없습니다.")
        if parent_id is not None:
            parent = con.execute("SELECT * FROM comments WHERE id=? AND observation_id=?",
                                 (parent_id, post_id)).fetchone()
            if parent is None or parent["is_deleted"]:
                raise ValueError("답글을 달 댓글을 찾을 수 없습니다.")
            parent_id = parent["parent_id"] or parent["id"]  # 답글은 한 단계만: 답글에 답글은 같은 묶음에 붙인다
        cur = con.execute("INSERT INTO comments(observation_id,author,body,created_at,parent_id) VALUES(?,?,?,?,?)",
                          (post_id, author, body, now(), parent_id))
        return int(cur.lastrowid)


def _comment_state(c: dict[str, Any], viewer: str, role: str) -> tuple[str, str]:
    privileged = role == "admin" or (bool(viewer) and c["author"] == viewer)
    if c["is_deleted"]:
        return "deleted", "삭제된 댓글입니다."
    if c["is_hidden"] and not privileged:
        return "hidden", "신고가 누적되어 임시로 숨겨진 댓글입니다."
    return ("hidden_visible" if c["is_hidden"] else "normal"), c["body"]


def list_comments(post_id: int, viewer: str, role: str, path: str | None = None) -> list[dict[str, Any]]:
    """댓글 묶음 목록: 각 항목에 replies(답글 목록)가 들어 있다. 숨김·삭제는 문구로 대신한다."""
    with db(path) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM comments WHERE observation_id=? ORDER BY id", (post_id,))]
    items: dict[int, dict[str, Any]] = {}
    for c in rows:
        state, text = _comment_state(c, viewer, role)
        items[c["id"]] = {
            "id": c["id"], "author": c["author"], "created_at": c["created_at"], "state": state, "text": text,
            "can_delete": state != "deleted" and (role == "admin" or (bool(viewer) and c["author"] == viewer)),
            "can_report": state in ("normal",) and bool(viewer) and c["author"] != viewer,
            "parent_id": c["parent_id"], "replies": [],
        }
    top = []
    for c in items.values():
        if c["parent_id"] and c["parent_id"] in items:
            items[c["parent_id"]]["replies"].append(c)
        else:
            top.append(c)
    return top


def count_comments(post_id: int, path: str | None = None) -> int:
    with db(path) as con:
        return con.execute("SELECT COUNT(*) FROM comments WHERE observation_id=? AND is_deleted=0",
                           (post_id,)).fetchone()[0]


def delete_comment(comment_id: int, user_id: str, is_admin: bool = False, path: str | None = None) -> None:
    """작성자·운영자만 삭제. 답글이 달려 있어도 흐름이 끊기지 않게 '삭제된 댓글'로 남긴다."""
    with db(path) as con:
        row = con.execute("SELECT author FROM comments WHERE id=?", (comment_id,)).fetchone()
        if row is None:
            raise ValueError("댓글을 찾을 수 없습니다.")
        if not is_admin and row["author"] != user_id:
            raise PermissionError("작성자 또는 운영자만 삭제할 수 있습니다.")
        con.execute("UPDATE comments SET is_deleted=1 WHERE id=?", (comment_id,))


# ------------------------------------------------------------------ 신고
def report_content(target_type: str, target_id: int, reporter: str, reason: str, detail: str = "",
                   hide_threshold: int = DEFAULT_HIDE_THRESHOLD, path: str | None = None) -> dict[str, Any]:
    """게시물·댓글 신고. 같은 사용자의 중복 신고는 DuplicateReport.

    접수 상태의 서로 다른 신고자 수가 hide_threshold 이상이면 대상을 임시 숨김 처리한다.
    """
    if target_type not in ("observation", "comment"):
        raise ValueError("신고 대상이 올바르지 않습니다.")
    if not reporter:
        raise PermissionError("로그인이 필요합니다.")
    if reason not in REPORT_REASONS:
        raise ValueError("신고 사유를 선택해 주세요.")
    detail = (detail or "").strip()[:300]
    table, owner_col = ("observations", "author") if target_type == "observation" else ("comments", "author")
    with db(path) as con:
        row = con.execute(f"SELECT {owner_col} AS owner FROM {table} WHERE id=?", (target_id,)).fetchone()
        if row is None:
            raise ValueError("신고할 대상을 찾을 수 없습니다.")
        if row["owner"] == reporter:
            raise ValueError("본인이 쓴 글은 신고할 수 없습니다.")
        try:
            con.execute("INSERT INTO content_reports(target_type,target_id,reporter,reason,detail,created_at) "
                        "VALUES(?,?,?,?,?,?)", (target_type, target_id, reporter, reason, detail, now()))
        except sqlite3.IntegrityError as exc:  # UNIQUE(target_type, target_id, reporter)
            raise DuplicateReport("이미 신고한 글입니다.") from exc
        open_count = con.execute(
            "SELECT COUNT(DISTINCT reporter) FROM content_reports WHERE target_type=? AND target_id=? AND status='접수'",
            (target_type, target_id)).fetchone()[0]
        hidden = False
        if hide_threshold > 0 and open_count >= hide_threshold:
            hidden = _set_hidden(con, target_type, target_id, True, f"신고 {open_count}건 누적")
        return {"report_count": open_count, "hidden": hidden}


def _set_hidden(con, target_type: str, target_id: int, hidden: bool, reason: str = "") -> bool:
    if target_type == "observation":
        con.execute("UPDATE observations SET is_hidden=?, hidden_reason=?, hidden_at=? WHERE id=?",
                    (int(hidden), reason if hidden else None, now() if hidden else None, target_id))
    else:
        con.execute("UPDATE comments SET is_hidden=? WHERE id=?", (int(hidden), target_id))
    return hidden


def review_reports(target_type: str, target_id: int, action: str, reviewer: str, is_admin: bool,
                   path: str | None = None) -> None:
    """운영자 검토. action: 'keep_hidden'(숨김 확정) 또는 'restore'(숨김 해제·신고 기각)."""
    if not is_admin:
        raise PermissionError("운영자만 신고를 검토할 수 있습니다.")
    if action not in ("keep_hidden", "restore"):
        raise ValueError("처리 방식이 올바르지 않습니다.")
    status = "숨김 확정" if action == "keep_hidden" else "기각"
    with db(path) as con:
        _set_hidden(con, target_type, target_id, action == "keep_hidden", "운영자 확정")
        con.execute("UPDATE content_reports SET status=?, reviewed_by=?, reviewed_at=? "
                    "WHERE target_type=? AND target_id=? AND status='접수'",
                    (status, reviewer, now(), target_type, target_id))


def list_reports(target_type: str, target_id: int, path: str | None = None) -> list[dict[str, Any]]:
    with db(path) as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM content_reports WHERE target_type=? AND target_id=? ORDER BY id",
            (target_type, target_id))]


def report_queue(path: str | None = None) -> list[dict[str, Any]]:
    """운영자 검토 대기 목록(접수 상태 신고가 있는 대상별 요약). ADM 화면에서 재사용한다."""
    with db(path) as con:
        rows = con.execute(
            "SELECT target_type, target_id, COUNT(DISTINCT reporter) AS reporters, MAX(created_at) AS last_at "
            "FROM content_reports WHERE status='접수' GROUP BY target_type, target_id ORDER BY last_at DESC").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ 수정·삭제
def update_post(post_id: int, user_id: str, *, is_admin: bool, title: str, body: str,
                location_visibility: str, is_public: bool, photo_public: bool | None = None,
                path: str | None = None) -> list[str]:
    """작성자·운영자 수정. 사진 공개 동의·위치 공개 설정의 변경은 함께 검증하고 동의 이력에 남긴다.

    바뀐 항목 이름 목록을 돌려준다.
    """
    title, body = (title or "").strip(), (body or "").strip()
    if not title or not body:
        raise ValueError("제목과 내용을 입력해 주세요.")
    if location_visibility not in LOCATION_LEVELS:
        raise ValueError("위치 공개 설정이 올바르지 않습니다.")
    with db(path) as con:
        post = con.execute("SELECT * FROM observations WHERE id=?", (post_id,)).fetchone()
        if post is None:
            raise ValueError("게시물을 찾을 수 없습니다.")
        if not is_admin and post["author"] != user_id:
            raise PermissionError("작성자 또는 운영자만 수정할 수 있습니다.")
        if location_visibility != "비공개" and post["region"] in ("", NO_REGION):
            raise ValueError("위치를 기록하지 않은 게시물은 위치를 공개할 수 없습니다.")
        has_photo = post["photo_blob"] is not None
        new_photo = bool(post["photo_public_consent"]) if photo_public is None else bool(photo_public)
        if photo_public is None and not is_public:
            new_photo = False  # 게시물을 비공개로 돌리면 사진 공개도 함께 끈다
        if new_photo and not has_photo:
            raise ValueError("공개할 사진이 없습니다.")
        if new_photo and not is_public:
            raise ValueError("비공개 게시물의 사진은 공개할 수 없습니다. 게시물을 먼저 공개해 주세요.")
        changed: list[str] = []
        if title != post["title"]:
            changed.append("제목")
        if body != post["body"]:
            changed.append("내용")
        if location_visibility != post["location_visibility"]:
            changed.append("위치 공개")
        stamp = now()
        if int(is_public) != post["is_public"]:
            changed.append("게시물 공개")
            con.execute("INSERT INTO consent_history(user_id,observation_id,consent_type,enabled,notice_version,created_at) "
                        "VALUES(?,?,?,?,?,?)", (post["author"], post_id, "public_post", int(is_public), "1.0", stamp))
        if int(new_photo) != post["photo_public_consent"]:
            changed.append("사진 공개")
            con.execute("INSERT INTO consent_history(user_id,observation_id,consent_type,enabled,notice_version,created_at) "
                        "VALUES(?,?,?,?,?,?)", (post["author"], post_id, "public_photo", int(new_photo), "1.0", stamp))
        con.execute("UPDATE observations SET title=?, body=?, location_visibility=?, is_public=?, photo_public_consent=? "
                    "WHERE id=?", (title, body, location_visibility, int(is_public), int(new_photo), post_id))
        con.execute("UPDATE aquarium_records SET title_snapshot=? WHERE observation_id=?", (title, post_id))
        return changed


def delete_post(post_id: int, user_id: str, is_admin: bool = False, path: str | None = None) -> None:
    """작성자·운영자 삭제. 수족관 도감 기록은 지우지 않고 본인 비공개로 남긴다(명세 SCR-08)."""
    with db(path) as con:
        post = con.execute("SELECT * FROM observations WHERE id=?", (post_id,)).fetchone()
        if post is None:
            raise ValueError("게시물을 찾을 수 없습니다.")
        if not is_admin and post["author"] != user_id:
            raise PermissionError("작성자 또는 운영자만 삭제할 수 있습니다.")
        comment_ids = [r[0] for r in con.execute("SELECT id FROM comments WHERE observation_id=?", (post_id,))]
        scr08_store.mark_post_deleted(con, post_id)
        con.execute("DELETE FROM observations WHERE id=?", (post_id,))
        con.execute("DELETE FROM content_reports WHERE target_type='observation' AND target_id=?", (post_id,))
        if comment_ids:
            marks = ",".join("?" * len(comment_ids))
            con.execute(f"DELETE FROM content_reports WHERE target_type='comment' AND target_id IN ({marks})", comment_ids)
        points = con.execute("SELECT points FROM point_ledger WHERE user_id=? AND source_type='observation' AND source_id=?",
                             (post["author"], str(post_id))).fetchone()
        if points and points[0]:
            con.execute("INSERT OR IGNORE INTO point_ledger(user_id,source_type,source_id,points,created_at) VALUES(?,?,?,?,?)",
                        (post["author"], "observation_delete", str(post_id), -int(points[0]), now()))
        remaining = con.execute("SELECT 1 FROM observations WHERE author=? AND species=? LIMIT 1",
                                (post["author"], post["species"])).fetchone()
        if not remaining:  # 글이 하나도 안 남은 종은 공개 도감에서 내린다(기록은 본인 비공개로 유지)
            con.execute("UPDATE aquarium_visibility SET is_public=0, updated_at=? WHERE user_id=? AND species=?",
                        (now(), post["author"], post["species"]))
