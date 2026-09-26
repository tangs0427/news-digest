"""같은 사건을 다룬 중복 기사를 걸러낸다.

AI 를 쓰지 않으므로 제목 토큰의 겹침 정도로 판단한다.
- 정규화한 제목이 완전히 같으면 중복
- 의미 토큰(2글자 이상)의 자카드 유사도가 임계값 이상이면 중복
"""

from __future__ import annotations

import re

from ..models import Article

SIMILARITY_THRESHOLD = 0.6

# 제목에서 빼도 의미가 유지되는 장식 요소
_BRACKETS = re.compile(r"[\[\(<【〔][^\]\)>】〕]{0,20}[\]\)>】〕]")
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣\s]")
_SPACES = re.compile(r"\s+")

# 거의 모든 기사 제목에 등장해 변별력이 없는 토큰
_STOPWORDS = {
    "속보", "단독", "종합", "그래픽", "인터뷰", "기자", "뉴스", "오늘",
    "국내", "관련", "예정", "전망", "발표", "밝혀", "대한", "위해",
}


def normalize(title: str) -> str:
    text = _BRACKETS.sub(" ", title)
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip().lower()


def tokenize(title: str) -> frozenset[str]:
    tokens = {
        token
        for token in normalize(title).split()
        if len(token) >= 2 and token not in _STOPWORDS
    }
    return frozenset(tokens)


def _tokens_match(left: str, right: str) -> bool:
    """한국어는 조사·어미가 붙어 같은 말이 다르게 쪼개진다('증가'/'증가세').

    한쪽이 다른 쪽으로 시작하면 같은 말로 본다.
    """
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return len(shorter) >= 2 and longer.startswith(shorter)


def _match_count(a: frozenset[str], b: frozenset[str]) -> int:
    """한 토큰이 여러 번 세지 않도록 짝지으며 센다."""
    remaining = sorted(b)
    matched = 0
    for token in sorted(a):
        for index, other in enumerate(remaining):
            if _tokens_match(token, other):
                remaining.pop(index)
                matched += 1
                break
    return matched


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    matched = _match_count(a, b)
    union = len(a) + len(b) - matched
    return matched / union if union else 0.0


def dedupe(articles: list[Article]) -> list[Article]:
    """중복을 제거한다. 먼저 등장한 기사(= 더 최신)를 남긴다."""
    kept: list[Article] = []
    kept_tokens: list[frozenset[str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    for article in articles:
        if article.url in seen_urls:
            continue

        norm = normalize(article.title)
        if norm and norm in seen_titles:
            continue

        tokens = tokenize(article.title)
        if any(_similarity(tokens, other) >= SIMILARITY_THRESHOLD for other in kept_tokens):
            continue

        kept.append(article)
        kept_tokens.append(tokens)
        seen_urls.add(article.url)
        if norm:
            seen_titles.add(norm)

    return kept


def dedupe_across(
    grouped: dict[str, list[Article]], order: list[str]
) -> dict[str, list[Article]]:
    """카테고리 간 중복도 제거한다. order 앞쪽 카테고리가 기사를 선점한다."""
    result: dict[str, list[Article]] = {}
    global_tokens: list[frozenset[str]] = []
    global_urls: set[str] = set()

    for key in order:
        surviving: list[Article] = []
        for article in dedupe(grouped.get(key, [])):
            if article.url in global_urls:
                continue
            tokens = tokenize(article.title)
            if any(
                _similarity(tokens, other) >= SIMILARITY_THRESHOLD
                for other in global_tokens
            ):
                continue
            surviving.append(article)
            global_tokens.append(tokens)
            global_urls.add(article.url)
        result[key] = surviving

    return result
