"""SCR-08 나의 수족관 목록 — 데이터 계층 (SQLite).

설계 원칙 (명세 v2.5 p8)
- 게시물 저장과 도감 기록 연결은 한 트랜잭션에서 처리한다. 이를 위해 observations INSERT
  트리거(`trg_scr08_obs_insert`)가 수족관 행과 관찰 기록 행을 같이 만든다.
  SCR-04/SCR-16 담당자가 따로 함수를 부르지 않아도 정합성이 유지된다.
- 중복 요청은 UNIQUE(observation_id)와 INSERT OR IGNORE로 막는다.
- 트리거가 없던 때 저장된 글, 일부 실패한 글은 `sync_user()`가 찾아 복구한다.
- 게시물을 삭제해도 도감 기록은 남는다(스냅샷 보존, 본인 비공개). 사용자가 따로 지울 수 있다.
"""
from __future__ import annotations

from typing import Any

from sea_info import store
from sea_info.dbutil import db as _db, now as _now
UNIDENTIFIED = "미확인"

SPECIES_SEED: list[dict[str, str]] = [
    {"name": "흰동가리", "scientific": "Amphiprion ocellaris", "emoji": "🐠", "category": "어류",
     "habitat": "따뜻한 열대 바다의 산호초 주변", "diet": "작은 갑각류와 플랑크톤",
     "summary": "말미잘과 공생하며 산호초 생태계에서 살아갑니다."},
    {"name": "불가사리", "scientific": "Asteroidea", "emoji": "⭐", "category": "극피동물",
     "habitat": "바위 해안과 얕은 바다 바닥", "diet": "조개류와 작은 무척추동물",
     "summary": "관족을 이용해 움직이며 종에 따라 재생 능력이 있습니다."},
    {"name": "소라게", "scientific": "Paguroidea", "emoji": "🦀", "category": "갑각류",
     "habitat": "조수 웅덩이와 바위 해안", "diet": "조류, 작은 동물, 유기물",
     "summary": "연약한 배를 보호하려고 빈 고둥 껍데기를 빌려 씁니다."},
    {"name": "말미잘", "scientific": "Actiniaria", "emoji": "🪸", "category": "자포동물",
     "habitat": "바위 해안의 조수 웅덩이와 산호초", "diet": "작은 물고기와 플랑크톤",
     "summary": "촉수의 독침세포로 먹이를 잡으며 흰동가리와 공생합니다."},
    {"name": "문어", "scientific": "Enteroctopus dofleini", "emoji": "🐙", "category": "연체동물",
     "habitat": "암초와 바위 틈이 있는 연안 바다", "diet": "게, 조개류, 작은 물고기",
     "summary": "학습과 위장 능력이 뛰어난 두족류로 팔이 여덟 개입니다."},
    {"name": "해파리", "scientific": "Scyphozoa", "emoji": "🪼", "category": "자포동물",
     "habitat": "연안과 외해의 표층·중층", "diet": "플랑크톤과 작은 어류",
     "summary": "촉수에 독침세포가 있어 맨손으로 만지면 안 됩니다."},
    {"name": "바다거북", "scientific": "Chelonioidea", "emoji": "🐢", "category": "파충류",
     "habitat": "열대·온대 바다와 산란용 모래 해변", "diet": "종에 따라 해조류, 해파리, 갑각류",
     "summary": "수명이 길고 보호 대상인 종이 많아 멀리서 관찰해야 합니다."},
    {"name": "큰돌고래", "scientific": "Tursiops truncatus", "emoji": "🐬", "category": "포유류",
     "habitat": "연안과 외해의 온대·열대 바다", "diet": "물고기와 오징어",
     "summary": "초음파로 위치를 파악하고 무리를 지어 생활합니다."},
    {"name": "살오징어", "scientific": "Todarodes pacificus", "emoji": "🦑", "category": "연체동물",
     "habitat": "동해 등 온대 바다의 표층~중층", "diet": "작은 물고기와 갑각류",
     "summary": "빛에 모이는 습성이 있고 대체로 수명이 1년 안팎으로 짧습니다."},
    {"name": "복어", "scientific": "Tetraodontidae", "emoji": "🐡", "category": "어류",
     "habitat": "연안 바위 지대와 모래 바닥", "diet": "갑각류와 조개류",
     "summary": "일부 종은 내장 등에 독(테트로도톡신)이 있어 먹으면 위험합니다."},
    {"name": "굴", "scientific": "Magallana gigas", "emoji": "🦪", "category": "연체동물",
     "habitat": "조간대 바위와 갯벌 연안", "diet": "플랑크톤(여과 섭식)",
     "summary": "바닷물을 걸러 먹는 여과 섭식자로 연안 수질 정화에 기여합니다."},
    {"name": "대하", "scientific": "Fenneropenaeus chinensis", "emoji": "🦐", "category": "갑각류",
     "habitat": "서해 연안의 얕은 바다", "diet": "작은 갑각류와 유기물",
     "summary": "가을철 서해안에서 많이 잡히는 대형 새우입니다."},
]

_SPECIES_CASE = "CASE WHEN {x} IS NULL OR TRIM({x}) = '' THEN '미확인' ELSE {x} END"


def normalize_species(name: str | None) -> str:
    name = (name or "").strip()
    return name if name else UNIDENTIFIED


def ensure_schema(path: str | None = None) -> None:
    store.initialize(path)
    with _db(path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS species_master (
                name TEXT PRIMARY KEY,
                scientific TEXT NOT NULL DEFAULT '',
                emoji TEXT NOT NULL DEFAULT '🐚',
                category TEXT NOT NULL DEFAULT '',
                habitat TEXT NOT NULL DEFAULT '',
                diet TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS aquarium_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                species TEXT NOT NULL,
                observation_id INTEGER NOT NULL UNIQUE,
                title_snapshot TEXT NOT NULL DEFAULT '',
                region_snapshot TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                added_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','dismissed')),
                post_deleted INTEGER NOT NULL DEFAULT 0 CHECK (post_deleted IN (0,1))
            );
            CREATE INDEX IF NOT EXISTS idx_aq_records_user ON aquarium_records(user_id, species, status);
            DROP TRIGGER IF EXISTS trg_scr08_obs_insert;
            """
        )
        sp = _SPECIES_CASE.format(x="NEW.species")
        con.executescript(
            f"""
            CREATE TRIGGER trg_scr08_obs_insert AFTER INSERT ON observations
            BEGIN
                INSERT OR IGNORE INTO aquarium(user_id, species, first_seen, observation_id)
                    VALUES (NEW.author, {sp}, NEW.created_at, NEW.id);
                INSERT OR IGNORE INTO aquarium_records
                    (user_id, species, observation_id, title_snapshot, region_snapshot, observed_at, added_at)
                    VALUES (NEW.author, {sp}, NEW.id, NEW.title, NEW.region, NEW.created_at, NEW.created_at);
            END;
            """
        )
        if con.execute("SELECT COUNT(*) FROM species_master").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO species_master(name,scientific,emoji,category,habitat,diet,summary) "
                "VALUES(:name,:scientific,:emoji,:category,:habitat,:diet,:summary)",
                SPECIES_SEED,
            )


# ---------------------------------------------------------------- species master
def species_master(path: str | None = None) -> dict[str, dict[str, Any]]:
    with _db(path) as con:
        rows = con.execute("SELECT * FROM species_master ORDER BY name").fetchall()
    return {r["name"]: dict(r) for r in rows}


def species_info(name: str, master: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    master = master if master is not None else species_master()
    if name in master:
        return master[name]
    emoji = "❔" if name == UNIDENTIFIED else "🐚"
    return {"name": name, "scientific": "", "emoji": emoji, "category": "", "habitat": "",
            "diet": "", "summary": "아직 도감 정보가 없는 생물입니다."}


# ---------------------------------------------------------------- 등록 / 정합성
def register_observation(observation_id: int, path: str | None = None) -> bool:
    """관찰 글 하나를 수족관에 등록한다(멱등). 새로 등록했으면 True."""
    with _db(path) as con:
        return _register(con, observation_id)


def _register(con, observation_id: int) -> bool:
    row = con.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone()
    if row is None:
        raise ValueError("관찰 글을 찾을 수 없습니다.")
    species = normalize_species(row["species"])
    cur = con.execute(
        "INSERT OR IGNORE INTO aquarium_records"
        "(user_id,species,observation_id,title_snapshot,region_snapshot,observed_at,added_at) VALUES(?,?,?,?,?,?,?)",
        (row["author"], species, row["id"], row["title"], row["region"], row["created_at"], _now()),
    )
    created = cur.rowcount == 1
    con.execute("INSERT OR IGNORE INTO aquarium(user_id,species,first_seen,observation_id) VALUES(?,?,?,?)",
                (row["author"], species, row["created_at"], row["id"]))
    return created


def sync_user(user_id: str, path: str | None = None) -> dict[str, int]:
    """사용자의 수족관을 점검해 어긋난 곳을 복구한다.

    - 글은 있는데 기록이 없는 경우(트리거 도입 전 글, 중간 실패) → 기록 생성
    - 기록은 있는데 수족관 종 행이 없는 경우(원본 delete_observation이 지운 경우 등) → 종 행 복구
    - 글이 삭제된 기록 → post_deleted 표시 + 본인 비공개 유지
    - 활성 기록이 하나도 없는 종 행 → 정리
    """
    report = {"created": 0, "parents_restored": 0, "marked_deleted": 0, "parents_removed": 0}
    with _db(path) as con:
        for row in con.execute(
            "SELECT o.id FROM observations o LEFT JOIN aquarium_records r ON r.observation_id=o.id "
            "WHERE o.author=? AND r.id IS NULL", (user_id,)
        ).fetchall():
            if _register(con, row["id"]):
                report["created"] += 1
        cur = con.execute(
            "UPDATE aquarium_records SET post_deleted=1 WHERE user_id=? AND post_deleted=0 AND "
            "observation_id NOT IN (SELECT id FROM observations)", (user_id,))
        report["marked_deleted"] = cur.rowcount
        for row in con.execute(
            "SELECT species, MIN(observed_at) AS first_seen, MIN(observation_id) AS oid FROM aquarium_records "
            "WHERE user_id=? AND status='active' GROUP BY species", (user_id,)
        ).fetchall():
            cur = con.execute(
                "INSERT OR IGNORE INTO aquarium(user_id,species,first_seen,observation_id) VALUES(?,?,?,NULL)",
                (user_id, row["species"], row["first_seen"]))
            report["parents_restored"] += cur.rowcount
        cur = con.execute(
            "DELETE FROM aquarium WHERE user_id=? AND species NOT IN "
            "(SELECT species FROM aquarium_records WHERE user_id=? AND status='active')", (user_id, user_id))
        report["parents_removed"] = cur.rowcount
        con.execute(
            "DELETE FROM aquarium_visibility WHERE user_id=? AND species NOT IN "
            "(SELECT species FROM aquarium WHERE user_id=?)", (user_id, user_id))
    return report


def mark_post_deleted(con, observation_id: int) -> None:
    """게시물 삭제 시 호출: 도감 기록은 남기고 표시만 한다."""
    con.execute("UPDATE aquarium_records SET post_deleted=1 WHERE observation_id=?", (observation_id,))


# ---------------------------------------------------------------- 조회
def list_aquarium(user_id: str, search: str = "", path: str | None = None) -> list[dict[str, Any]]:
    """수집한 생물 목록. 이름 검색(대소문자·공백 무시), 공개/비공개 상태 포함."""
    needle = (search or "").strip().casefold()
    with _db(path) as con:
        rows = con.execute(
            """
            SELECT r.species,
                   COUNT(*) AS record_count,
                   MIN(r.observed_at) AS first_seen,
                   MAX(r.observed_at) AS last_observed,
                   SUM(CASE WHEN o.id IS NOT NULL AND o.is_public=1 THEN 1 ELSE 0 END) AS public_posts,
                   SUM(CASE WHEN o.id IS NOT NULL AND o.is_public=1 AND o.photo_public_consent=1
                             AND o.photo_blob IS NOT NULL THEN 1 ELSE 0 END) AS public_photos,
                   SUM(r.post_deleted) AS deleted_posts,
                   COALESCE(v.is_public, 0) AS is_public
            FROM aquarium_records r
            LEFT JOIN observations o ON o.id = r.observation_id
            LEFT JOIN aquarium_visibility v ON v.user_id = r.user_id AND v.species = r.species
            WHERE r.user_id = ? AND r.status = 'active'
            GROUP BY r.species
            ORDER BY MAX(r.observed_at) DESC, r.species
            """, (user_id,)).fetchall()
    master = species_master(path)
    items = []
    for r in rows:
        if needle and needle not in r["species"].casefold():
            continue
        info = species_info(r["species"], master)
        items.append({
            "species": r["species"], "emoji": info["emoji"], "category": info["category"],
            "record_count": r["record_count"], "first_seen": r["first_seen"],
            "last_observed": r["last_observed"], "public_posts": r["public_posts"] or 0,
            "public_photos": r["public_photos"] or 0, "deleted_posts": r["deleted_posts"] or 0,
            "is_public": bool(r["is_public"]), "is_unidentified": r["species"] == UNIDENTIFIED,
        })
    return items


def summary(user_id: str, path: str | None = None) -> dict[str, int]:
    items = list_aquarium(user_id, path=path)
    known = [i for i in items if not i["is_unidentified"]]
    return {
        "collected_species": len(known),
        "unidentified_records": sum(i["record_count"] for i in items if i["is_unidentified"]),
        "total_records": sum(i["record_count"] for i in items),
        "master_species": len(species_master(path)),
    }


def list_records(user_id: str, species: str, path: str | None = None) -> list[dict[str, Any]]:
    with _db(path) as con:
        rows = con.execute(
            """
            SELECT r.id AS record_id, r.observation_id, r.post_deleted, r.observed_at,
                   COALESCE(o.title, r.title_snapshot) AS title,
                   COALESCE(o.region, r.region_snapshot) AS region,
                   o.is_public AS post_public, o.photo_public_consent AS photo_public
            FROM aquarium_records r LEFT JOIN observations o ON o.id = r.observation_id
            WHERE r.user_id=? AND r.species=? AND r.status='active'
            ORDER BY r.observed_at DESC, r.id DESC
            """, (user_id, species)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 변경
def reclassify_record(user_id: str, observation_id: int, new_species: str, path: str | None = None) -> None:
    """미확인 기록의 이름을 정하거나 다른 종으로 옮긴다(본인 기록만)."""
    new_species = (new_species or "").strip()
    if not new_species or new_species == UNIDENTIFIED:
        raise ValueError("옮길 생물 이름을 선택해 주세요.")
    with _db(path) as con:
        rec = con.execute("SELECT * FROM aquarium_records WHERE observation_id=? AND status='active'",
                          (observation_id,)).fetchone()
        if rec is None or rec["user_id"] != user_id:
            raise PermissionError("본인의 도감 기록만 바꿀 수 있습니다.")
        old = rec["species"]
        if old == new_species:
            return
        con.execute("UPDATE aquarium_records SET species=? WHERE id=?", (new_species, rec["id"]))
        con.execute("UPDATE observations SET species=? WHERE id=? AND author=?", (new_species, observation_id, user_id))
        con.execute("INSERT OR IGNORE INTO aquarium(user_id,species,first_seen,observation_id) VALUES(?,?,?,?)",
                    (user_id, new_species, rec["observed_at"], observation_id))
        left = con.execute("SELECT COUNT(*) FROM aquarium_records WHERE user_id=? AND species=? AND status='active'",
                           (user_id, old)).fetchone()[0]
        if left == 0:
            con.execute("DELETE FROM aquarium WHERE user_id=? AND species=?", (user_id, old))
            con.execute("DELETE FROM aquarium_visibility WHERE user_id=? AND species=?", (user_id, old))


def dismiss_species(user_id: str, species: str, path: str | None = None) -> int:
    """사용자가 도감 항목을 직접 지운다. 게시물은 건드리지 않는다. 지운 기록 수를 반환."""
    with _db(path) as con:
        cur = con.execute("UPDATE aquarium_records SET status='dismissed' WHERE user_id=? AND species=? AND status='active'",
                          (user_id, species))
        con.execute("DELETE FROM aquarium WHERE user_id=? AND species=?", (user_id, species))
        con.execute("DELETE FROM aquarium_visibility WHERE user_id=? AND species=?", (user_id, species))
        return cur.rowcount


def make_photos_private(user_id: str, species: str, path: str | None = None) -> int:
    """사진 공개 동의 철회: 사진은 지우지 않고 본인에게만 보이도록 바꾼다(명세 SCR-06/08). 바꾼 글 수를 반환."""
    with _db(path) as con:
        ids = [r[0] for r in con.execute(
            "SELECT r.observation_id FROM aquarium_records r JOIN observations o ON o.id=r.observation_id "
            "WHERE r.user_id=? AND r.species=? AND r.status='active' AND o.photo_public_consent=1", (user_id, species))]
        stamp = _now()
        for oid in ids:
            con.execute("UPDATE observations SET photo_public_consent=0 WHERE id=?", (oid,))
            con.execute("INSERT INTO consent_history(user_id,observation_id,consent_type,enabled,notice_version,created_at) "
                        "VALUES(?,?,?,0,?,?)", (user_id, oid, "public_photo", "1.0", stamp))
        return len(ids)
