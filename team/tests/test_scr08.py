from conftest import make_post
from sea_info import scr06_store, scr08_store as aq, store


def test_자동_등록_새종은_종수_증가_기존종은_기록만_추가(dbp):
    make_post(dbp, "alice", "불가사리")
    items = aq.list_aquarium("alice", path=dbp)
    assert [(i["species"], i["record_count"]) for i in items] == [("불가사리", 1)]
    make_post(dbp, "alice", "불가사리", title="두 번째")
    items = aq.list_aquarium("alice", path=dbp)
    assert [(i["species"], i["record_count"]) for i in items] == [("불가사리", 2)]
    make_post(dbp, "alice", "문어")
    assert aq.summary("alice", dbp)["collected_species"] == 2


def test_미확인_게시물도_추가되고_수집_종수에는_포함되지_않는다(dbp):
    make_post(dbp, "bob", "")
    items = aq.list_aquarium("bob", path=dbp)
    assert items[0]["species"] == "미확인" and items[0]["is_unidentified"]
    s = aq.summary("bob", dbp)
    assert s["collected_species"] == 0 and s["unidentified_records"] == 1


def test_이름_검색은_대소문자와_공백을_무시한다(dbp):
    make_post(dbp, "carol", "흰동가리")
    make_post(dbp, "carol", "문어")
    assert [i["species"] for i in aq.list_aquarium("carol", " 문 ", path=dbp)] == ["문어"]
    assert aq.list_aquarium("carol", "없는이름", path=dbp) == []


def test_다른_사람의_수족관은_섞이지_않는다(dbp):
    make_post(dbp, "alice", "문어")
    assert aq.list_aquarium("bob", path=dbp) == []


def test_공개_비공개_상태_표시(dbp):
    make_post(dbp, "alice", "문어")
    assert aq.list_aquarium("alice", path=dbp)[0]["is_public"] is False
    store.set_aquarium_public("alice", "문어", True, dbp)
    assert aq.list_aquarium("alice", path=dbp)[0]["is_public"] is True


def test_게시물_삭제해도_도감_기록은_본인_비공개로_남는다(dbp):
    pid = make_post(dbp, "alice", "문어")
    store.set_aquarium_public("alice", "문어", True, dbp)
    scr06_store.delete_post(pid, "alice", path=dbp)
    item = aq.list_aquarium("alice", path=dbp)[0]
    assert item["species"] == "문어" and item["record_count"] == 1
    assert item["deleted_posts"] == 1 and item["is_public"] is False
    assert aq.list_records("alice", "문어", dbp)[0]["post_deleted"] == 1


def test_원본_delete_observation으로_지워도_sync가_도감을_복구한다(dbp):
    pid = make_post(dbp, "alice", "문어")
    store.delete_observation(pid, "alice", path=dbp)
    report = aq.sync_user("alice", dbp)
    assert report["parents_restored"] == 1
    assert aq.list_aquarium("alice", path=dbp)[0]["species"] == "문어"


def test_일부_실패로_기록이_빠진_경우_sync가_복구한다(dbp):
    make_post(dbp, "alice", "문어")
    with scr06_store.db(dbp) as con:
        con.execute("DELETE FROM aquarium_records")
        con.execute("DELETE FROM aquarium")
    assert aq.list_aquarium("alice", path=dbp) == []
    report = aq.sync_user("alice", dbp)
    assert report["created"] == 1
    assert aq.list_aquarium("alice", path=dbp)[0]["species"] == "문어"
    assert aq.sync_user("alice", dbp)["created"] == 0  # 두 번 불러도 중복 없음


def test_register_observation은_멱등이다(dbp):
    pid = make_post(dbp, "alice", "문어")
    assert aq.register_observation(pid, dbp) is False
    assert aq.list_aquarium("alice", path=dbp)[0]["record_count"] == 1


def test_미확인_재분류(dbp):
    pid = make_post(dbp, "alice", "")
    aq.reclassify_record("alice", pid, "복어", dbp)
    items = aq.list_aquarium("alice", path=dbp)
    assert [i["species"] for i in items] == ["복어"]
    assert store.observations(dbp)[0]["species"] == "복어"


def test_재분류는_본인_기록만(dbp):
    pid = make_post(dbp, "alice", "")
    import pytest
    with pytest.raises(PermissionError):
        aq.reclassify_record("mallory", pid, "복어", dbp)


def test_사용자가_도감_항목을_지우면_sync로_되살아나지_않는다(dbp):
    make_post(dbp, "alice", "문어")
    assert aq.dismiss_species("alice", "문어", dbp) == 1
    aq.sync_user("alice", dbp)
    assert aq.list_aquarium("alice", path=dbp) == []
    make_post(dbp, "alice", "문어", title="다시 만남")  # 새 관찰이 생기면 다시 등록
    assert aq.list_aquarium("alice", path=dbp)[0]["record_count"] == 1


def test_게시물과_사진_공개_상태는_각각_센다(dbp):
    make_post(dbp, "alice", "문어", is_public=True, photo=b"img", public_photo=True)
    make_post(dbp, "alice", "문어", title="비공개", is_public=False)
    it = aq.list_aquarium("alice", path=dbp)[0]
    assert it["record_count"] == 2 and it["public_posts"] == 1 and it["public_photos"] == 1


def test_종_마스터가_시드된다(dbp):
    m = aq.species_master(dbp)
    assert len(m) >= 12 and "흰동가리" in m
    assert aq.species_info("처음보는생물", m)["name"] == "처음보는생물"


def test_사진_공개_철회는_사진을_지우지_않고_본인만_보이게(dbp):
    pid = make_post(dbp, "alice", "문어", photo=b"img", public_photo=True)
    assert aq.make_photos_private("alice", "문어", dbp) == 1
    p = scr06_store.get_post(pid, dbp)
    assert p["photo_blob"] == b"img" and p["photo_public_consent"] == 0
    assert scr06_store.photo_visible(p, "alice", "member") and not scr06_store.photo_visible(p, "bob", "member")
    assert aq.make_photos_private("alice", "문어", dbp) == 0  # 두 번째는 바꿀 게 없음
