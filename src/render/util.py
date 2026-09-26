"""렌더러들이 공유하는 작은 도우미."""

from __future__ import annotations

from datetime import datetime, tzinfo
from html import escape

from ..models import Article

__all__ = ["escape", "local_time", "meta_line"]


def local_time(article: Article, tz: tzinfo) -> str:
    """기사 발행 시각을 로컬 기준 'HH:MM' 으로. 모르면 빈 문자열."""
    if not article.published:
        return ""
    return article.published.astimezone(tz).strftime("%H:%M")


def meta_line(article: Article, tz: tzinfo) -> str:
    """'언론사 · 09:12' 형태의 보조 정보."""
    parts = [article.source]
    stamp = local_time(article, tz)
    if stamp:
        parts.append(stamp)
    return " · ".join(p for p in parts if p)


def format_header(now: datetime, total: int) -> str:
    return f"{now:%Y년 %m월 %d일} 기준 · 총 {total}건"
