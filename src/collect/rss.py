"""RSS 피드를 읽어 Article 목록으로 바꾼다."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from ..config import CategorySpec, FeedSpec, SourceConfig
from ..models import Article

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
TIMEOUT = 20

# 제목 끝에 붙는 " - 언론사" 꼬리표.
# 숫자를 포함한 꼬리는 제목의 일부일 수 있으므로(" - 매출 79조") 건드리지 않는다.
_TRAILING_SOURCE = re.compile(r"\s+[-|—]\s+[^\d\-|—]{2,20}$")
_SEPARATORS = (" - ", " — ", " | ")

# 언론사가 자체 RSS 제목에 매체명을 붙이고 구글 뉴스가 한 번 더 붙이는 경우가
# 있어("... - 조선비즈 - Chosunbiz") 최대 두 번까지 떼어낸다.
_MAX_SUFFIX_STRIPS = 2

# 리드 문단 앞에 붙는 통신사 머리말: "(서울=연합뉴스) 한주홍 기자 = "
_LEAD_PREFIX = re.compile(r"^\([^)]{0,40}\)\s*(?:[가-힣]{2,10}\s*기자\s*=\s*)?")
_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
# 한국어는 정보 밀도가 높아 30자 안팎도 온전한 리드 문단이다. 기준을 높게 잡으면
# 멀쩡한 요약을 버리게 된다. 구글 뉴스의 제목 되풀이는 아래 echo 검사가 걸러낸다.
_MIN_DESCRIPTION = 25


def fetch_feed(feed: FeedSpec) -> list[feedparser.FeedParserDict]:
    """피드 하나를 내려받아 항목 목록을 돌려준다. 실패하면 빈 목록."""
    try:
        response = requests.get(
            feed.url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("피드 실패 [%s]: %s", feed.name, exc)
        return []

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        log.warning("피드 파싱 실패 [%s]: %s", feed.name, parsed.get("bozo_exception"))
        return []
    return parsed.entries


def _published_at(entry: feedparser.FeedParserDict) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            # feedparser 는 struct_time 을 UTC 로 정규화해서 준다.
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def _source_name(entry: feedparser.FeedParserDict, fallback: str) -> str:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("title"):
        return str(source["title"]).strip()
    return fallback


def _strip_source_suffix(title: str, source: str) -> str:
    """꼬리표를 한 번 떼어낸다. 뗄 게 없으면 그대로 돌려준다."""
    if source:
        for separator in _SEPARATORS:
            suffix = separator + source
            if title.endswith(suffix):
                return title[: -len(suffix)].strip()
    stripped = _TRAILING_SOURCE.sub("", title).strip()
    return stripped or title


def _clean_title(raw: str, source: str) -> str:
    original = html.unescape(raw or "").strip()
    title = original
    for _ in range(_MAX_SUFFIX_STRIPS):
        candidate = _strip_source_suffix(title, source)
        if candidate == title:
            break
        title = candidate
    return title or original


def _clean_description(raw: str, title: str) -> str:
    """RSS 리드 문단을 다듬는다. 쓸 만하지 않으면 빈 문자열."""
    text = html.unescape(_TAGS.sub(" ", raw or ""))
    text = _WHITESPACE.sub(" ", text).strip()
    text = _LEAD_PREFIX.sub("", text).strip()

    if len(text) < _MIN_DESCRIPTION:
        return ""
    # 제목을 그대로 되풀이한 것(구글 뉴스)은 정보가 없다.
    if text.startswith(title[:20]):
        return ""
    return text


def _apply_alias(source: str, aliases: dict[str, str]) -> str:
    """'v.daum.net' 같은 도메인형 출처를 읽을 수 있는 매체명으로 바꾼다."""
    return aliases.get(source.lower(), source)


def collect_category(
    category: CategorySpec, config: SourceConfig, now: datetime
) -> list[Article]:
    """카테고리에 속한 모든 피드를 수집해 시간 범위 안의 기사만 돌려준다."""
    cutoff = now - timedelta(hours=config.lookback_hours)
    articles: list[Article] = []

    for feed in category.feeds:
        limit = feed.max_items or config.max_per_feed
        entries = fetch_feed(feed)[:limit]
        kept = 0
        for entry in entries:
            url = (entry.get("link") or "").strip()
            if not url:
                continue

            published = _published_at(entry)
            if published and published < cutoff:
                continue

            # 꼬리표 제거는 원본 출처명으로 해야 한다. 별칭은 표시용이므로
            # 제목 정리가 끝난 뒤에 적용한다.
            raw_source = _source_name(entry, feed.name)
            title = _clean_title(entry.get("title", ""), raw_source)
            if not title:
                continue
            source = _apply_alias(raw_source, config.source_aliases)

            articles.append(
                Article(
                    title=title,
                    url=url,
                    source=source,
                    feed_name=feed.name,
                    category_key=category.key,
                    published=published,
                    description=_clean_description(entry.get("summary", ""), title),
                )
            )
            kept += 1
        log.info("  %-24s %2d건 (전체 %d)", feed.name, kept, len(entries))

    return articles


def collect_all(config: SourceConfig, now: datetime) -> dict[str, list[Article]]:
    """카테고리 키 -> 기사 목록."""
    result: dict[str, list[Article]] = {}
    for category in config.categories:
        log.info("[%s] 수집 중...", category.label)
        result[category.key] = collect_category(category, config, now)
    return result
