"""테스트는 항상 임시 SQLite 파일을 쓴다. 저장소에 커밋된 data/sea_info.sqlite3는 건드리지 않는다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sea_info import scr06_store, store  # noqa: E402


@pytest.fixture
def dbp(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    scr06_store.ensure_schema(path)
    return path


def make_post(dbp, author="alice", species="불가사리", title="제목", body="내용", region="제주",
              visibility="비공개", is_public=True, photo=None, public_photo=False):
    return store.create_observation(
        title=title, body=body, species=species, author=author, region=region, visibility=visibility,
        public_photo=public_photo, operator_photo=False, is_public=is_public, photo_blob=photo, path=dbp)
