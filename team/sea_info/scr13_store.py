"""SCR-13 해양 뉴스·칼럼 — 데이터 계층 (SQLite).

명세 v2.5 p13: 매일 06:00(KST) 수집 → AI 요약 후 자동 공개 → 운영자 사후 검토(숨김·수정),
Top 5(최근 30일 콘텐츠, 조회수 내림차순, 순위 1시간마다 갱신), 같은 사용자/브라우저의 같은 콘텐츠 조회는
24시간에 1회만 집계, 수집 오류 시 이전 콘텐츠 유지 + 출처별 실패 상태·재처리.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sea_info.dbutil import KST, add_column, db, parse_ts

SETTING_DEFAULTS = {
    "news_top_days": "30",              # Top 5 집계 기간(일) — 관리자 설정
    "news_rank_refresh_minutes": "60",  # 순위 갱신 주기
    "news_view_dedup_hours": "24",      # 같은 사용자·브라우저의 같은 콘텐츠 중복 집계 제외 시간
    "news_per_page": "10",
}
SOURCE_KINDS = ("공공기관", "매체", "샘플")
# 실제 URL은 네트워크가 열린 PC에서 `python scripts/collect_news.py --check`로 먼저 확인할 것
DEFAULT_SOURCES = [
    {"name": "해양수산부 보도자료(정책브리핑)", "kind": "공공기관", "feed_url": "https://www.korea.kr/rss/dept_mof.xml",
     "enabled": 1, "terms_verified": 1},
    {"name": "Sea-Info 편집팀(샘플)", "kind": "샘플", "feed_url": "", "enabled": 0, "terms_verified": 1},
]
SAMPLE_ARTICLES = [
    ("해양 생태계가 보내는 변화의 신호", "해양 생물과 서식지 변화를 이해하는 짧은 소개입니다.",
     "수온 상승과 서식지 변화가 연안 생물의 분포에 어떤 영향을 주는지 살펴봅니다. 시민이 남긴 관찰 기록이 변화를 읽는 단서가 될 수 있습니다.", 250, 2),
    ("우리 바다를 지키는 작은 관찰", "시민 관찰 기록을 생태 교육에 연결하는 방법입니다.",
     "사진과 짧은 기록만으로도 연안 생물 조사에 참여할 수 있습니다. 관찰할 때는 생물을 만지지 않고 서식지를 훼손하지 않는 것이 기본입니다.", 220, 4),
    ("바다 생물과 함께하는 지속 가능한 미래", "해양 보호를 위한 일상 속 실천을 알아봅니다.",
     "일회용품을 줄이고 해변 쓰레기를 되가져오는 작은 실천이 해양 생물을 보호합니다.", 190, 7),
    ("연안의 계절과 새로운 생명", "계절에 따라 달라지는 연안 생물을 살펴봅니다.",
     "봄에는 조수 웅덩이에 치어와 무척추동물이 늘고 가을에는 철새와 회유성 어류가 찾아옵니다.", 160, 11),
    ("해양 보호를 위한 다양한 노력", "보호구역과 시민 참여의 역할을 정리합니다.",
     "해양보호구역 지정과 시민 모니터링이 함께 이루어질 때 보호 효과가 커집니다.", 130, 16),
    ("갯벌이 품은 생물 이야기", "갯벌에 사는 생물과 그 역할을 소개합니다.",
     "갯벌은 수많은 저서생물의 서식처이자 철새의 먹이터입니다. 물이 빠졌을 때만 드러나는 독특한 생태계입니다.", 95, 21),
    ("해파리 대처 요령", "여름철 해파리 쏘임을 예방하는 방법입니다.",
     "해파리를 발견하면 만지지 말고 거리를 두세요. 쏘였다면 바닷물로 씻고 증상이 심하면 의료기관을 찾아야 합니다.", 70, 26),
    ("한 달이 넘은 오래된 소식(집계 기간 밖 예시)", "Top 5 집계 기간 밖의 콘텐츠 예시입니다.",
     "최근 30일 안의 콘텐츠만 Top 5에 오르는지 확인하기 위한 샘플입니다.", 999, 45),
]


def _s(value: str | None) -> str:
    return (value or "").strip()


def ensure_schema(path: str | None = None, now: datetime | None = None) -> None:
    from sea_info import store
    store.initialize(path)
    with db(path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS news_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK (kind IN ('공공기관','매체','샘플')),
                feed_url TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                terms_verified INTEGER NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT '미실행',
                last_run_at TEXT,
                last_error TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS news_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES news_sources(id),
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                summary_detail TEXT NOT NULL DEFAULT '',
                ai_summarized INTEGER NOT NULL DEFAULT 0,
                url TEXT NOT NULL UNIQUE,
                published_at TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                view_count INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                hidden_reason TEXT,
                edited_by_admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles(published_at DESC);
            CREATE TABLE IF NOT EXISTS news_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
                viewer_key TEXT NOT NULL,
                viewed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_views_lookup ON news_views(article_id, viewer_key, viewed_at);
            CREATE TABLE IF NOT EXISTS news_collect_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES news_sources(id),
                trigger TEXT NOT NULL DEFAULT 'schedule',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT '진행 중',
                fetched INTEGER NOT NULL DEFAULT 0,
                inserted INTEGER NOT NULL DEFAULT 0,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS news_rank_snapshot (
                rank INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                views INTEGER NOT NULL,
                snapshot_at TEXT NOT NULL
            );
            """
        )
        for key, value in SETTING_DEFAULTS.items():
            con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)", (key, value))
        for src in DEFAULT_SOURCES:
            con.execute("INSERT OR IGNORE INTO news_sources(name,kind,feed_url,enabled,terms_verified) "
                        "VALUES(:name,:kind,:feed_url,:enabled,:terms_verified)", src)
        if con.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0] == 0:
            sample_id = con.execute("SELECT id FROM news_sources WHERE kind='샘플'").fetchone()[0]
            base = now or datetime.now(KST)
            for i, (title, summary, detail, views, days_ago) in enumerate(SAMPLE_ARTICLES, 1):
                stamp = (base - timedelta(days=days_ago)).isoformat()
                con.execute(
                    "INSERT OR IGNORE INTO news_articles(source_id,title,summary,summary_detail,ai_summarized,url,"
                    "published_at,collected_at,view_count) VALUES(?,?,?,?,0,?,?,?,?)",
                    (sample_id, title, summary, detail, f"sample://news/{i}", stamp, stamp, views))


# ------------------------------------------------------------------ 설정
def get_settings(path: str | None = None) -> dict[str, int]:
    with db(path) as con:
        rows = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM app_settings")}
    merged = {**SETTING_DEFAULTS, **rows}
    return {k: int(merged[k]) for k in SETTING_DEFAULTS}


def set_setting(key: str, value: int, is_admin: bool, path: str | None = None) -> None:
    if not is_admin:
        raise PermissionError("운영자만 설정을 바꿀 수 있습니다.")
    if key not in SETTING_DEFAULTS:
        raise ValueError("알 수 없는 설정입니다.")
    if int(value) < 1 or int(value) > 3650:
        raise ValueError("1 이상의 값을 입력해 주세요.")
    with db(path) as con:
        con.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(int(value))))


# ------------------------------------------------------------------ 출처
def list_sources(path: str | None = None) -> list[dict[str, Any]]:
    with db(path) as con:
        return [dict(r) for r in con.execute("SELECT * FROM news_sources ORDER BY id")]


def collectable_sources(path: str | None = None) -> list[dict[str, Any]]:
    """수집 가능한 출처: 사용 중이고, 공공기관이거나 이용 조건이 확인된 매체."""
    return [s for s in list_sources(path) if s["enabled"] and s["feed_url"]
            and (s["kind"] == "공공기관" or (s["kind"] == "매체" and s["terms_verified"]))]


def update_source(source_id: int, is_admin: bool, *, enabled: bool | None = None,
                  terms_verified: bool | None = None, path: str | None = None) -> None:
    if not is_admin:
        raise PermissionError("운영자만 출처를 바꿀 수 있습니다.")
    with db(path) as con:
        if enabled is not None:
            con.execute("UPDATE news_sources SET enabled=? WHERE id=?", (int(enabled), source_id))
        if terms_verified is not None:
            con.execute("UPDATE news_sources SET terms_verified=? WHERE id=?", (int(terms_verified), source_id))


def add_source(name: str, kind: str, feed_url: str, is_admin: bool, terms_verified: bool = False,
               path: str | None = None) -> int:
    if not is_admin:
        raise PermissionError("운영자만 출처를 추가할 수 있습니다.")
    if kind not in ("공공기관", "매체"):
        raise ValueError("출처 종류가 올바르지 않습니다.")
    name, feed_url = _s(name), _s(feed_url)
    if not name or not feed_url.startswith(("http://", "https://")):
        raise ValueError("출처 이름과 http(s) 주소를 입력해 주세요.")
    with db(path) as con:
        cur = con.execute("INSERT INTO news_sources(name,kind,feed_url,enabled,terms_verified) VALUES(?,?,?,1,?)",
                          (name, kind, feed_url, int(terms_verified)))
        return int(cur.lastrowid)


# ------------------------------------------------------------------ 기사 조회
def list_articles(search: str = "", source_id: int | None = None, page: int = 1, per_page: int | None = None,
                  include_hidden: bool = False, within_days: int | None = None,
                  now: datetime | None = None, path: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """기사 목록(최신순). `within_days`가 있으면 그 기간에 발행된 기사만 보인다(데이터는 지우지 않는다)."""
    per_page = per_page or get_settings(path)["news_per_page"]
    where, params = [], []
    if within_days:
        where.append("a.published_at>=?")
        params.append(((now or datetime.now(KST)) - timedelta(days=within_days)).isoformat())
    if not include_hidden:
        where.append("a.is_hidden=0")
    if source_id:
        where.append("a.source_id=?")
        params.append(source_id)
    if _s(search):
        where.append("(a.title LIKE ? OR a.summary LIKE ?)")
        params += [f"%{_s(search)}%"] * 2
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    base = "FROM news_articles a JOIN news_sources s ON s.id=a.source_id " + clause
    with db(path) as con:
        total = con.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT a.*, s.name AS source_name, s.kind AS source_kind {base} "
            f"ORDER BY a.published_at DESC, a.id DESC LIMIT ? OFFSET ?",
            params + [per_page, max(0, (page - 1) * per_page)]).fetchall()
    return [dict(r) for r in rows], total


def get_article(article_id: int, include_hidden: bool = False, path: str | None = None) -> dict[str, Any] | None:
    with db(path) as con:
        row = con.execute("SELECT a.*, s.name AS source_name, s.kind AS source_kind FROM news_articles a "
                          "JOIN news_sources s ON s.id=a.source_id WHERE a.id=?", (article_id,)).fetchone()
    if row is None or (row["is_hidden"] and not include_hidden):
        return None
    return dict(row)


# ------------------------------------------------------------------ 조회수·순위
def make_viewer_key(user_id: str | None, client_hint: str | None) -> str:
    """회원은 계정, 비회원은 접속 환경(IP+브라우저 정보) 해시. 원문은 저장하지 않는다."""
    raw = f"user:{user_id}" if user_id else f"anon:{client_hint or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def record_view(article_id: int, viewer_key: str, now: datetime | None = None, path: str | None = None) -> bool:
    """조회를 집계한다. 같은 viewer_key가 dedup 시간 안에 같은 기사를 봤다면 집계하지 않고 False."""
    now = now or datetime.now(KST)
    hours = get_settings(path)["news_view_dedup_hours"]
    since = (now - timedelta(hours=hours)).isoformat()
    with db(path) as con:
        art = con.execute("SELECT is_hidden FROM news_articles WHERE id=?", (article_id,)).fetchone()
        if art is None or art["is_hidden"]:
            return False
        seen = con.execute("SELECT 1 FROM news_views WHERE article_id=? AND viewer_key=? AND viewed_at>=? LIMIT 1",
                           (article_id, viewer_key, since)).fetchone()
        if seen:
            return False
        con.execute("INSERT INTO news_views(article_id,viewer_key,viewed_at) VALUES(?,?,?)",
                    (article_id, viewer_key, now.isoformat()))
        con.execute("UPDATE news_articles SET view_count=view_count+1 WHERE id=?", (article_id,))
        return True


def refresh_ranking(now: datetime | None = None, path: str | None = None) -> str:
    """Top 순위 스냅샷을 새로 만든다. 집계 기간(기본 30일) 안에 발행된 공개 콘텐츠만, 조회수 내림차순."""
    now = now or datetime.now(KST)
    days = get_settings(path)["news_top_days"]
    since = (now - timedelta(days=days)).isoformat()
    with db(path) as con:
        rows = con.execute(
            "SELECT id, view_count FROM news_articles WHERE is_hidden=0 AND published_at>=? "
            "ORDER BY view_count DESC, published_at DESC, id DESC LIMIT 20", (since,)).fetchall()
        con.execute("DELETE FROM news_rank_snapshot")
        con.executemany("INSERT INTO news_rank_snapshot(rank,article_id,views,snapshot_at) VALUES(?,?,?,?)",
                        [(i, r["id"], r["view_count"], now.isoformat()) for i, r in enumerate(rows, 1)])
    return now.isoformat()


def top_articles(n: int = 5, now: datetime | None = None, path: str | None = None) -> dict[str, Any]:
    """Top N. 스냅샷이 갱신 주기(기본 1시간)보다 오래됐으면 먼저 다시 만든다.

    스냅샷 이후 숨김 처리된 기사는 즉시 빠진다(순위 숫자는 다시 매긴다).
    """
    now = now or datetime.now(KST)
    minutes = get_settings(path)["news_rank_refresh_minutes"]
    with db(path) as con:
        snap = con.execute("SELECT MAX(snapshot_at) FROM news_rank_snapshot").fetchone()[0]
    last = parse_ts(snap)
    if last is None or now - last >= timedelta(minutes=minutes):
        snap = refresh_ranking(now, path)
    with db(path) as con:
        rows = con.execute(
            "SELECT r.rank, r.views AS ranked_views, a.*, s.name AS source_name FROM news_rank_snapshot r "
            "JOIN news_articles a ON a.id=r.article_id JOIN news_sources s ON s.id=a.source_id "
            "WHERE a.is_hidden=0 ORDER BY r.rank LIMIT ?", (n,)).fetchall()
    items = [dict(r) | {"display_rank": i} for i, r in enumerate(rows, 1)]
    return {"items": items, "snapshot_at": snap, "refresh_minutes": minutes}


# ------------------------------------------------------------------ 운영자 사후 검토
def set_hidden(article_id: int, hidden: bool, is_admin: bool, reason: str = "", path: str | None = None) -> None:
    if not is_admin:
        raise PermissionError("운영자만 숨김 처리할 수 있습니다.")
    with db(path) as con:
        cur = con.execute("UPDATE news_articles SET is_hidden=?, hidden_reason=? WHERE id=?",
                          (int(hidden), _s(reason) if hidden else None, article_id))
        if cur.rowcount != 1:
            raise ValueError("기사를 찾을 수 없습니다.")


def edit_article(article_id: int, is_admin: bool, *, title: str, summary: str, summary_detail: str,
                 path: str | None = None) -> None:
    if not is_admin:
        raise PermissionError("운영자만 수정할 수 있습니다.")
    title, summary, summary_detail = _s(title), _s(summary), _s(summary_detail)
    if not title or not summary:
        raise ValueError("제목과 요약을 입력해 주세요.")
    with db(path) as con:
        cur = con.execute("UPDATE news_articles SET title=?, summary=?, summary_detail=?, edited_by_admin=1 WHERE id=?",
                          (title, summary, summary_detail, article_id))
        if cur.rowcount != 1:
            raise ValueError("기사를 찾을 수 없습니다.")


# ------------------------------------------------------------------ 수집 기록 (collector가 사용)
def insert_articles(source_id: int, items: list[dict[str, Any]], now: datetime | None = None,
                    path: str | None = None) -> int:
    """URL이 이미 있는 기사는 건너뛴다(기존 내용·조회수 유지). 새로 들어간 개수를 돌려준다."""
    stamp = (now or datetime.now(KST)).isoformat()
    inserted = 0
    with db(path) as con:
        for it in items:
            cur = con.execute(
                "INSERT OR IGNORE INTO news_articles(source_id,title,summary,summary_detail,ai_summarized,url,"
                "published_at,collected_at) VALUES(?,?,?,?,?,?,?,?)",
                (source_id, it["title"], it["summary"], it["summary_detail"], int(it.get("ai_summarized", False)),
                 it["url"], it["published_at"], stamp))
            inserted += cur.rowcount
    return inserted


def start_run(source_id: int | None, trigger: str, now: datetime | None = None, path: str | None = None) -> int:
    with db(path) as con:
        cur = con.execute("INSERT INTO news_collect_runs(source_id,trigger,started_at) VALUES(?,?,?)",
                          (source_id, trigger, (now or datetime.now(KST)).isoformat()))
        return int(cur.lastrowid)


def finish_run(run_id: int, source_id: int | None, status: str, fetched: int = 0, inserted: int = 0,
               error: str = "", now: datetime | None = None, path: str | None = None) -> None:
    stamp = (now or datetime.now(KST)).isoformat()
    with db(path) as con:
        con.execute("UPDATE news_collect_runs SET finished_at=?, status=?, fetched=?, inserted=?, error=? WHERE id=?",
                    (stamp, status, fetched, inserted, error[:500], run_id))
        if source_id is not None:
            if status == "성공":
                con.execute("UPDATE news_sources SET last_status='성공', last_run_at=?, last_error=NULL, "
                            "consecutive_failures=0 WHERE id=?", (stamp, source_id))
            else:
                con.execute("UPDATE news_sources SET last_status='실패', last_run_at=?, last_error=?, "
                            "consecutive_failures=consecutive_failures+1 WHERE id=?", (stamp, error[:500], source_id))


def recent_runs(limit: int = 20, path: str | None = None) -> list[dict[str, Any]]:
    with db(path) as con:
        return [dict(r) for r in con.execute(
            "SELECT r.*, s.name AS source_name FROM news_collect_runs r LEFT JOIN news_sources s ON s.id=r.source_id "
            "ORDER BY r.id DESC LIMIT ?", (limit,))]


def last_scheduled_attempt(path: str | None = None) -> str | None:
    with db(path) as con:
        row = con.execute("SELECT MAX(started_at) FROM news_collect_runs WHERE trigger IN ('schedule','lazy')").fetchone()
    return row[0]


def run_in_progress(now: datetime | None = None, stale_minutes: int = 15, path: str | None = None) -> bool:
    now = now or datetime.now(KST)
    since = (now - timedelta(minutes=stale_minutes)).isoformat()
    with db(path) as con:
        return con.execute("SELECT 1 FROM news_collect_runs WHERE status='진행 중' AND started_at>=? LIMIT 1",
                           (since,)).fetchone() is not None
