"""파이프라인 전체가 주고받는 데이터 구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# strftime("%a") 는 실행 환경 로케일에 따라 'Thu'/'목'/'木' 으로 갈린다.
# 문서 이름으로 '오늘 것을 이미 보냈는지'를 판단하므로 결정적이어야 한다.
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def digest_title(date: datetime) -> str:
    """그날의 문서 제목. 같은 날이면 어디서 부르든 같은 문자열이어야 한다."""
    return f"뉴스 다이제스트 {date:%Y-%m-%d} ({_WEEKDAYS[date.weekday()]})"


@dataclass(slots=True)
class Article:
    """수집된 기사 한 건."""

    title: str
    url: str
    source: str  # 언론사명 (없으면 피드 이름)
    feed_name: str
    category_key: str
    published: datetime | None = None
    # RSS 가 준 원문 리드 문단. 구글 뉴스는 제목만 주므로 비어 있을 수 있다.
    description: str = ""
    # 요약 단계가 채우는 한 줄 요약. 실패하면 빈 문자열로 남는다.
    summary: str = ""

    @property
    def sort_key(self) -> float:
        """최신순 정렬용. 발행 시각을 모르면 가장 뒤로 보낸다."""
        return self.published.timestamp() if self.published else 0.0


@dataclass(slots=True)
class CategoryDigest:
    """카테고리 하나의 최종 묶음."""

    key: str
    label: str
    description: str
    articles: list[Article] = field(default_factory=list)


@dataclass(slots=True)
class Digest:
    """하루치 다이제스트 전체."""

    date: datetime  # 로컬(KST) 기준 생성 시각
    categories: list[CategoryDigest] = field(default_factory=list)
    # 맨 위에 붙는 '오늘의 흐름'. 요약을 못 만들면 빈 목록.
    overview: list[str] = field(default_factory=list)
    # 요약 실패 사유. 조용히 빠지면 왜 없는지 알 수 없으므로 문서/메일에 표시한다.
    # --no-ai 로 일부러 끈 경우에는 비어 있다.
    summary_error: str = ""

    @property
    def total_articles(self) -> int:
        return sum(len(c.articles) for c in self.categories)

    @property
    def title(self) -> str:
        return digest_title(self.date)

    def non_empty(self) -> list[CategoryDigest]:
        return [c for c in self.categories if c.articles]
