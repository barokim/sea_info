"""시연용 DB를 별도 파일로 만든다. 저장소의 data/sea_info.sqlite3는 건드리지 않는다.

  python scripts/make_demo_data.py                      # data/demo_showcase.sqlite3 생성
  $env:SQLITE_PATH = "data/demo_showcase.sqlite3"       # PowerShell에서 앱을 이 DB로 실행
  python -m streamlit run streamlit_app.py

회원 데모(demo@sea-info.local)에게 관찰 기록 7건(4종, 어항 1개 가득 + 2칸)을 넣는다.
사진은 시연용으로 그린 그림이며 실제 관찰 사진이 아니다. 이미 있으면 덮어쓰지 않는다(--force로 새로 만든다).
"""
import argparse
import io
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO_USER = "demo@sea-info.local"
# (제목, 생물, 지역, 이야기, 배경색)
RECORDS = [
    ("썰물에 드러난 불가사리", "불가사리", "제주", "바위틈에서 오렌지색 불가사리를 만났어요.", (237, 137, 54)),
    ("소라게 가족 발견", "소라게", "부산", "조수 웅덩이에서 소라게 세 마리가 걷고 있었어요.", (160, 120, 200)),
    ("말미잘 사이의 흰동가리", "말미잘", "서귀포", "말미잘 촉수 사이를 작은 물고기가 오갔어요.", (219, 112, 147)),
    ("해변에서 만난 말미잘", "말미잘", "제주", "파도가 빠진 뒤 바위에 붙어 있었어요.", (80, 160, 190)),
    ("두 번째 불가사리", "불가사리", "강릉", "갯바위에서 또 불가사리를 봤어요.", (72, 187, 120)),
    ("소라게 이사하는 날", "소라게", "인천", "더 큰 껍데기로 옮겨 타는 모습이었어요.", (214, 158, 46)),
    ("방파제 아래 흰동가리", "흰동가리", "여수", "방파제 아래 물웅덩이에서 작은 흰동가리를 봤어요.", (66, 153, 225)),
]


def _photo(color: tuple[int, int, int]) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (480, 320), color)
    d = ImageDraw.Draw(img)
    for i in range(0, 320, 16):  # 은은한 물결 줄무늬
        shade = tuple(min(255, c + (i // 16) * 3) for c in color)
        d.rectangle([0, i, 480, i + 8], fill=shade)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "demo_showcase.sqlite3"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"이미 있습니다: {out} (새로 만들려면 --force)")
        return 0
    base = ROOT / "data" / "sea_info.sqlite3"
    out.parent.mkdir(parents=True, exist_ok=True)
    if base.exists():
        shutil.copyfile(base, out)
    elif out.exists():
        out.unlink()
    os.environ["SQLITE_PATH"] = str(out)
    from sea_info import scr06_store, scr13_store, store
    scr06_store.ensure_schema(str(out))
    scr13_store.ensure_schema(str(out))
    # 같은 계정의 기존 시연 글이 중복되지 않게 이 계정의 글만 비우고 다시 넣는다
    import sqlite3
    with sqlite3.connect(out) as con:
        ids = [r[0] for r in con.execute("SELECT id FROM observations WHERE author=?", (DEMO_USER,))]
        for table, col in (("aquarium_records", "observation_id"), ("aquarium", "observation_id"),
                           ("consent_history", "observation_id"), ("observations", "id")):
            try:
                con.executemany(f"DELETE FROM {table} WHERE {col}=?", [(i,) for i in ids])
            except sqlite3.OperationalError:
                pass
        try:
            con.execute("DELETE FROM aquarium_records WHERE user_id=?", (DEMO_USER,))
            con.execute("DELETE FROM aquarium WHERE user_id=?", (DEMO_USER,))
        except sqlite3.OperationalError:
            pass
    for title, species, region, body, color in RECORDS:
        store.create_observation(title=title, body=body, species=species, author=DEMO_USER, region=region,
                                 visibility="비공개", public_photo=True, operator_photo=False, is_public=True,
                                 photo_blob=_photo(color), path=str(out))
    from sea_info import scr08_store as aq
    aq.sync_user(DEMO_USER, str(out))
    t = aq.tank_status(DEMO_USER, path=str(out))
    print(f"만들었습니다: {out}\n회원 데모 관찰 기록 {t['total']}건 · 가득 찬 어항 {t['completed']}개 · 지금 {t['current']}/5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
