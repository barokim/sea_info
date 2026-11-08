"""뉴스 수집 실행 스크립트 (매일 06:00 KST에 스케줄러로 실행).

  python scripts/collect_news.py            # 켜져 있는 출처 전부 수집
  python scripts/collect_news.py --check    # 저장 없이 각 출처가 열리고 파싱되는지 점검
  python scripts/collect_news.py --source 1 # 출처 하나만 재처리

스케줄 예 (Windows 작업 스케줄러): 매일 06:00, 동작 = python scripts/collect_news.py
스케줄 예 (Linux cron, 서버 시간대가 UTC일 때): 0 21 * * *   (UTC 21:00 = KST 06:00)
GEMINI_API_KEY 등 비밀값은 환경변수(.env)로만 읽는다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: F401,E402  (.env 읽기)
from sea_info import news_collector as nc, scr13_store as ns  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source", type=int)
    args = ap.parse_args()
    ns.ensure_schema()
    if args.check:
        bad = 0
        for s in ns.list_sources():
            if not s["feed_url"] or not s["enabled"]:
                continue
            try:
                items = nc.parse_source(nc.fetch_url(s["feed_url"]), s["feed_url"])
                off = "" if s["enabled"] else " (꺼짐)"
                print(f"OK   {s['name']}{off}: 기사 {len(items)}건 파싱 · 예: {items[0]['title'][:30]}")
            except Exception as exc:
                bad += 1
                print(f"FAIL {s['name']}: {type(exc).__name__}: {exc}")
        return 1 if bad else 0
    results = nc.run_collection(trigger="schedule" if not args.source else "retry", source_id=args.source)
    for r in results:
        print(r)
    return 1 if any(r["status"] != "성공" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
