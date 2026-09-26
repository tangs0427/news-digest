"""다이제스트에 넣을 가치가 없는 기사를 걸러낸다.

구글 뉴스 검색은 블로그/카페 글, 해외 개별종목 시황 필러, 언론사 행사
홍보글까지 같이 끌고 온다. 규칙은 전부 sources.yaml 에 있고 여기서는
적용만 한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..models import Article

log = logging.getLogger(__name__)


@dataclass(slots=True)
class FilterRules:
    exclude_sources: list[str]
    exclude_patterns: list[re.Pattern[str]]
    min_title_length: int

    @classmethod
    def from_raw(cls, raw: dict | None) -> "FilterRules":
        raw = raw or {}
        return cls(
            exclude_sources=[s.lower() for s in raw.get("exclude_sources", [])],
            exclude_patterns=[
                re.compile(p, re.IGNORECASE) for p in raw.get("exclude_title_patterns", [])
            ],
            min_title_length=int(raw.get("min_title_length", 8)),
        )

    def rejects(self, article: Article) -> str | None:
        """걸러낼 이유를 돌려준다. 통과하면 None."""
        if len(article.title) < self.min_title_length:
            return "제목 너무 짧음"

        source = article.source.lower()
        for blocked in self.exclude_sources:
            if blocked in source:
                return f"차단 매체({article.source})"

        for pattern in self.exclude_patterns:
            if pattern.search(article.title):
                return f"차단 패턴({pattern.pattern})"

        return None


def apply(articles: list[Article], rules: FilterRules) -> list[Article]:
    kept: list[Article] = []
    dropped = 0
    for article in articles:
        reason = rules.rejects(article)
        if reason:
            dropped += 1
            log.debug("제외 [%s] %s", reason, article.title)
            continue
        kept.append(article)
    if dropped:
        log.debug("필터로 %d건 제외", dropped)
    return kept
