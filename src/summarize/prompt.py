"""요약 요청 프롬프트와 응답 스키마.

호출을 둘로 나눈다.
- 카테고리별 요약: 12건씩 끊어서. 한 번에 60건을 보내면 API 가 503 을 낸다.
- 오늘의 흐름: 제목만 모아 한 번. 출력이 짧아 부담이 적다.

기사 대부분은 구글 뉴스에서 와서 제목밖에 없다. 제목만 보고 요약을 쓰게 하면
없는 수치나 배경을 지어내기 쉬우므로, 원문 리드 문단이 있을 때와 없을 때를
나눠서 지시한다.
"""

from __future__ import annotations

import json

from ..models import CategoryDigest, Digest

# 한 줄 요약 길이 상한 (한국어 기준)
SUMMARY_MAX_CHARS = 90

_NO_FABRICATION = """반드시 지킬 것:
- 주어진 제목과 본문에 없는 수치, 인명, 날짜, 기관명을 새로 만들어내지 마라.
- 'body'가 있으면 그 내용에 근거해 요약한다.
- 'body'가 없으면(제목뿐이면) 제목이 말하는 범위 안에서만 쓴다. 구체적 수치를
  모르면 쓰지 말고, 사안의 성격이나 배경을 일반적인 수준에서 설명한다.
- 확실하지 않으면 단정하지 말고 '~로 보인다', '~라고 전해졌다'처럼 쓴다.
- 광고성 표현이나 감탄사는 쓰지 않는다."""

SUMMARY_RULES = f"""너는 한국어 뉴스 다이제스트 편집자다. 아래 기사마다 한 줄 요약을 만든다.

- 모든 id에 대해 빠짐없이 만든다.
- {SUMMARY_MAX_CHARS}자 이내. 평서문 한 문장. '~다'로 끝낸다.
- 제목을 그대로 바꿔 쓰지 말고, 제목이 생략한 맥락이나 의미를 채운다.

{_NO_FABRICATION}"""

OVERVIEW_RULES = f"""너는 한국어 뉴스 다이제스트 편집자다. 아래 오늘의 기사 제목들을 보고
'오늘의 흐름' 3~5개를 만든다.

- 각 항목은 한 문장.
- 오늘 뉴스를 관통하는 큰 줄기를 짚는다. 개별 기사 나열이 아니라 묶어서 본 해석.
- 여러 기사에서 반복되는 주제를 우선한다.
- 취업 준비생(컨설팅·금융권 지망) 관점에서 알아둘 가치가 있는 것을 고른다.

{_NO_FABRICATION}"""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        }
    },
    "required": ["summaries"],
}

OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {"overview": {"type": "array", "items": {"type": "string"}}},
    "required": ["overview"],
}


def build_summary_prompt(category: CategoryDigest, digest: Digest) -> str:
    """카테고리 하나치 요약 요청. id 는 그 카테고리 안에서 0부터."""
    payload = []
    for article_id, article in enumerate(category.articles):
        entry: dict[str, object] = {"id": article_id, "title": article.title}
        if article.description:
            entry["body"] = article.description[:300]
        payload.append(entry)

    return (
        f"{SUMMARY_RULES}\n\n"
        f"오늘 날짜: {digest.date:%Y-%m-%d}\n"
        f"분야: {category.label}\n"
        f"기사 {len(payload)}건:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )


def build_overview_prompt(digest: Digest) -> str:
    """제목만 모아 흐름을 뽑는다. 본문은 넣지 않아 요청이 가볍다."""
    lines = []
    for category in digest.non_empty():
        titles = "\n".join(f"  - {a.title}" for a in category.articles)
        lines.append(f"[{category.label}]\n{titles}")

    return (
        f"{OVERVIEW_RULES}\n\n"
        f"오늘 날짜: {digest.date:%Y-%m-%d}\n\n" + "\n\n".join(lines)
    )


def apply_summaries(category: CategoryDigest, result: dict) -> int:
    """카테고리 응답을 반영하고 요약이 붙은 기사 수를 돌려준다."""
    applied = 0
    for row in result.get("summaries", []):
        if not isinstance(row, dict):
            continue
        try:
            article_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(row.get("text", "")).strip()
        if not text or not 0 <= article_id < len(category.articles):
            continue
        category.articles[article_id].summary = text
        applied += 1
    return applied


def apply_overview(digest: Digest, result: dict) -> int:
    digest.overview = [
        line.strip()
        for line in result.get("overview", [])
        if isinstance(line, str) and line.strip()
    ]
    return len(digest.overview)


def flatten(digest: Digest) -> list:
    """카테고리 순서대로 펼친 기사 목록 (집계·테스트용)."""
    return [article for category in digest.non_empty() for article in category.articles]
