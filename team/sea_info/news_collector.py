"""SCR-13 뉴스 수집기: RSS/Atom → 요약 → news_articles 저장.

- 매일 한국 시간 06:00 실행은 `scripts/collect_news.py`를 스케줄러(작업 스케줄러/cron)에 등록해서 한다.
- 스케줄러가 없을 때를 위해 `collect_if_due()`가 화면 접속 시 '오늘 06:00 이후 아직 안 돌았으면' 한 번 돌린다.
- 수집이 실패해도 기존 기사는 그대로 둔다(저장만 추가). 출처별 실패 상태는 DB에 남아 운영자가 재처리한다.
"""
from __future__ import annotations

import html
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urljoin

from sea_info import ai_summary, scr13_store as ns
from sea_info.dbutil import KST, parse_ts

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS_PER_SOURCE = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Sea-Info-Agent-NewsCollector/1.0"
SCHEDULE_HOUR = 6


class FeedError(Exception):
    pass


def fetch_url(url: str, timeout: int = 15) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise FeedError("지원하지 않는 주소입니다.")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, text/xml, text/html;q=0.9, */*;q=0.5",
                                               "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise FeedError("피드가 너무 큽니다.")
    return data


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _child_text(el: ET.Element, *names: str) -> str:
    for child in el:
        if _tag(child) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def _parse_date(value: str, fallback: datetime) -> datetime:
    value = (value or "").strip()
    if value:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            dt = parse_ts(value)
        if dt is not None:
            return (dt if dt.tzinfo else dt.replace(tzinfo=KST)).astimezone(KST)
    return fallback


def parse_feed(data: bytes, now: datetime | None = None) -> list[dict[str, Any]]:
    """RSS 2.0 / Atom 파싱. 외부 엔티티·DTD가 있는 문서는 거부한다(XML 폭탄 방지)."""
    now = now or datetime.now(KST)
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data[:65536].lower():
        raise FeedError("DTD/ENTITY가 포함된 피드는 처리하지 않습니다.")
    for end in (b"</rss>", b"</feed>", b"</rdf:rdf>"):  # 끝맺음 뒤에 붙은 광고·스크립트 찌꺼기는 버린다
        pos = data.lower().rfind(end)
        if pos != -1:
            data = data[:pos + len(end)]
            break
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FeedError(f"피드 형식 오류: {exc}") from exc
    entries = [e for e in root.iter() if _tag(e) in ("item", "entry")]
    items = []
    for e in entries[:MAX_ITEMS_PER_SOURCE]:
        title = strip_html(_child_text(e, "title"))
        link = _child_text(e, "link")
        if not link:
            for c in e:
                if _tag(c) == "link" and c.get("href"):
                    link = c.get("href", "").strip()
                    break
        if not title or not link.startswith(("http://", "https://")):
            continue
        body = _child_text(e, "encoded", "content", "description", "summary")
        published = _parse_date(_child_text(e, "pubDate", "published", "updated", "date"), now)
        items.append({"title": title[:200], "url": link, "text": strip_html(body), "published_at": published.isoformat()})
    return items

_LI = re.compile(r"(?is)<li\b[^>]*>(.*?)</li>")
_VIEW = re.compile(r"""(?is)<a\b[^>]*href=["']([^"']*articleView\.html\?idxno=\d+[^"']*)["'][^>]*>(.*?)</a>""")
_SUMMARY = re.compile(r"""(?is)<p\b[^>]*class=["'][^"']*(?:lead|summary)[^"']*["'][^>]*>(.*?)</p>""")
_DATE_FULL = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})\s+(\d{2}):(\d{2})")
_DATE_SHORT = re.compile(r"(?<![\d.\-])(\d{2})-(\d{2})\s+(\d{2}):(\d{2})")


def is_html_list(data: bytes) -> bool:
    return b"<html" in data[:4096].lower() or b"<!doctype html" in data[:4096].lower()


def _list_date(block: str, now: datetime) -> datetime:
    text = strip_html(block)
    m = _DATE_FULL.search(text)
    try:
        if m:
            y, mo, d, h, mi = map(int, m.groups())
            return datetime(y, mo, d, h, mi, tzinfo=KST)
        m = _DATE_SHORT.search(text)
        if m:
            mo, d, h, mi = map(int, m.groups())
            dt = datetime(now.year, mo, d, h, mi, tzinfo=KST)
            return dt.replace(year=now.year - 1) if dt > now + timedelta(days=1) else dt  # 연도 없는 날짜
    except ValueError:
        pass
    return now


def parse_article_list(data: bytes, base_url: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """인터넷신문 솔루션의 '기사목록' 화면(articleList.html)에서 기사 제목·링크·요약·시각을 읽는다.
    RSS가 없는 구역(소분류)용. 제목은 h2 안의 링크, 요약은 lead/summary 문단이다."""
    now = now or datetime.now(KST)
    page = data.decode("utf-8", errors="replace")
    items, seen = [], set()
    for block in _LI.findall(page):
        links = _VIEW.findall(block)
        if not links:
            continue
        href = links[0][0]
        title = ""
        h2 = re.search(r"(?is)<h2\b[^>]*>(.*?)</h2>", block)
        if h2:
            title = strip_html(h2.group(1))
        if not title:
            title = next((strip_html(t) for _, t in links if strip_html(t)), "")
        url = urljoin(base_url, html.unescape(href))
        if not title or url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        m = _SUMMARY.search(block)
        items.append({"title": title[:200], "url": url, "text": strip_html(m.group(1)) if m else "",
                      "published_at": _list_date(block, now).isoformat()})
    if not items:
        raise FeedError("기사 목록을 찾지 못했습니다(화면 구조가 바뀌었을 수 있습니다).")
    return items[:MAX_ITEMS_PER_SOURCE]


def is_mabik_board(data: bytes) -> bool:
    return b"fn_search_detail(" in data


def parse_mabik_board(data: bytes, base_url: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """국립해양생물자원관 보도자료 게시판(표). 제목 버튼의 글 번호로 상세 주소를 만든다. 요약이 없어 제목을 본문으로 쓴다."""
    now = now or datetime.now(KST)
    page = data.decode("utf-8", errors="replace")
    root = re.sub(r"(?:/view)?\.do(?:\?.*)?$", "", base_url)
    items = []
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", page):
        m = re.search(r"fn_search_detail\(\s*'([^']+)'", row)
        t = re.search(r"(?is)<strong[^>]*bbs-subject-txt[^>]*>(.*?)</strong>", row)
        if not (m and t and strip_html(t.group(1))):
            continue
        title = strip_html(t.group(1))
        d = re.search(r"(\d{4})[.\-](\d{2})[.\-](\d{2})", strip_html(re.sub(r"(?is)^.*?class=\"regDate\"", "", row)))
        try:
            when = datetime(*map(int, d.groups()), tzinfo=KST) if d else now
        except ValueError:
            when = now
        items.append({"title": title[:200], "url": f"{root}/view.do?nttId={m.group(1)}", "text": title,
                      "published_at": when.isoformat()})
    if not items:
        raise FeedError("게시판 목록을 찾지 못했습니다(화면 구조가 바뀌었을 수 있습니다).")
    return items[:MAX_ITEMS_PER_SOURCE]


def parse_source(data: bytes, url: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """RSS/Atom이면 피드로, 기사목록 웹페이지면 목록으로 읽는다."""
    if is_mabik_board(data):
        return parse_mabik_board(data, url, now)
    if is_html_list(data):
        return parse_article_list(data, url, now)
    try:
        return parse_feed(data, now)
    except FeedError as exc:
        head = re.sub(r"\s+", " ", data[:160].decode("utf-8", errors="replace")).strip()
        raise FeedError(f"{exc} [받은 내용 앞부분: {head}]") from exc


def _summarizer_from_settings() -> Callable[[str, str], dict[str, Any]]:
    """config의 ai.provider(mock|gemini)와 환경변수 GEMINI_API_KEY/GEMINI_MODEL을 따른다."""
    import config
    ai = config.load_settings()["ai"]
    return lambda title, text: ai_summary.summarize(title, text, provider=ai["provider"],
                                                    api_key=ai["api_key"], model=ai["model"])


def collect_source(source: dict[str, Any], *, trigger: str = "schedule", fetch: Callable[[str], bytes] = fetch_url,
                   summarize: Callable[[str, str], dict[str, Any]] | None = None, now: datetime | None = None,
                   path: str | None = None) -> dict[str, Any]:
    """출처 하나를 수집한다. 예외는 밖으로 던지지 않고 결과 dict의 status에 담는다."""
    now = now or datetime.now(KST)
    summarize = summarize or _summarizer_from_settings()
    run_id = ns.start_run(source["id"], trigger, now, path)
    try:
        items = parse_source(fetch(source["feed_url"]), source["feed_url"], now)
        prepared = []
        for it in items:
            s = summarize(it["title"], it["text"])
            prepared.append({"title": it["title"], "url": it["url"], "published_at": it["published_at"],
                             "summary": s["short"], "summary_detail": s["detail"], "ai_summarized": s["ai"]})
        inserted = ns.insert_articles(source["id"], prepared, now, path)
        ns.finish_run(run_id, source["id"], "성공", len(items), inserted, now=now, path=path)
        return {"source": source["name"], "status": "성공", "fetched": len(items), "inserted": inserted}
    except Exception as exc:  # 어떤 오류든 기존 콘텐츠는 건드리지 않고 실패만 기록
        ns.finish_run(run_id, source["id"], "실패", error=f"{type(exc).__name__}: {exc}", now=now, path=path)
        return {"source": source["name"], "status": "실패", "error": f"{type(exc).__name__}: {exc}"}


def run_collection(*, trigger: str = "schedule", source_id: int | None = None, fetch: Callable[[str], bytes] = fetch_url,
                   summarize: Callable[[str, str], dict[str, Any]] | None = None, now: datetime | None = None,
                   path: str | None = None) -> list[dict[str, Any]]:
    sources = ns.collectable_sources(path)
    if source_id is not None:
        sources = [s for s in sources if s["id"] == source_id]
    return [collect_source(s, trigger=trigger, fetch=fetch, summarize=summarize, now=now, path=path) for s in sources]


def due_since(now: datetime) -> datetime:
    """가장 최근에 지나간 06:00(KST)."""
    today = now.astimezone(KST).replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    return today if now.astimezone(KST) >= today else today - timedelta(days=1)


def is_due(now: datetime | None = None, path: str | None = None) -> bool:
    now = (now or datetime.now(KST)).astimezone(KST)
    last = parse_ts(ns.last_scheduled_attempt(path))
    return (last is None or last < due_since(now)) and not ns.run_in_progress(now, path=path)


def collect_if_due(*, enabled: bool, now: datetime | None = None, background: bool = True,
                   path: str | None = None, **kwargs: Any) -> bool:
    """뉴스 수집이 켜져 있고 오늘 06:00 이후 아직 시도하지 않았다면 수집을 시작한다. 시작했으면 True."""
    if not enabled or not is_due(now, path):
        return False
    job = lambda: run_collection(trigger="lazy", now=now, path=path, **kwargs)  # noqa: E731
    if background:
        threading.Thread(target=job, daemon=True).start()
    else:
        job()
    return True
