"""sources.yaml 과 환경변수를 읽어 설정 객체로 만든다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = PROJECT_ROOT / "config" / "sources.yaml"


@dataclass(slots=True)
class FeedSpec:
    name: str
    type: str  # "rss" | "google_news"
    url: str
    # 이 피드에서 가져올 최대 항목 수. None 이면 전역 max_per_feed 를 쓴다.
    # 자주 발행하는 종합 피드가 최신순 정렬을 독점하는 것을 막는 용도.
    max_items: int | None = None


@dataclass(slots=True)
class CategorySpec:
    key: str
    label: str
    description: str
    feeds: list[FeedSpec]


@dataclass(slots=True)
class SourceConfig:
    timezone: str
    lookback_hours: int
    max_per_category: int
    max_per_feed: int
    categories: list[CategorySpec]
    # 원본 dict 그대로 둔다. 해석은 collect.filters 가 맡는다.
    filters: dict
    # 도메인형 출처명 -> 표시용 매체명 (키는 소문자)
    source_aliases: dict[str, str]


@dataclass(slots=True)
class DeliveryConfig:
    """비밀 값들. 값이 없으면 빈 문자열이며, 각 전달 모듈이 알아서 건너뛴다."""

    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    drive_folder_id: str
    drive_folder_name: str
    gmail_address: str
    gmail_app_password: str
    mail_to: str
    gemini_api_key: str
    gemini_model: str

    @property
    def can_summarize(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def can_upload_docs(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_refresh_token
        )

    @property
    def can_send_mail(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password)

    @property
    def recipient(self) -> str:
        return self.mail_to or self.gmail_address


def _google_news_url(query: str) -> str:
    """구글 뉴스 RSS 검색 URL 생성 (한국어 / 한국 지역)."""
    from urllib.parse import quote_plus

    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR%3Ako"
    )


def load_sources(path: Path | None = None) -> SourceConfig:
    raw = yaml.safe_load((path or DEFAULT_SOURCES).read_text(encoding="utf-8"))

    categories: list[CategorySpec] = []
    for cat in raw.get("categories", []):
        feeds: list[FeedSpec] = []
        for feed in cat.get("feeds", []):
            ftype = feed.get("type", "rss")
            if ftype == "google_news":
                url = _google_news_url(feed["query"])
            else:
                url = feed["url"]
            raw_max = feed.get("max_items")
            feeds.append(
                FeedSpec(
                    name=feed["name"],
                    type=ftype,
                    url=url,
                    max_items=int(raw_max) if raw_max else None,
                )
            )
        categories.append(
            CategorySpec(
                key=cat["key"],
                label=cat["label"],
                description=cat.get("description", ""),
                feeds=feeds,
            )
        )

    return SourceConfig(
        timezone=raw.get("timezone", "Asia/Seoul"),
        lookback_hours=int(raw.get("lookback_hours", 30)),
        max_per_category=int(raw.get("max_per_category", 12)),
        max_per_feed=int(raw.get("max_per_feed", 25)),
        categories=categories,
        filters=raw.get("filters", {}) or {},
        source_aliases={
            key.lower(): value
            for key, value in (raw.get("source_aliases", {}) or {}).items()
        },
    )


def load_delivery() -> DeliveryConfig:
    """환경변수에서 인증 정보를 읽는다. 로컬에서는 .env 도 함께 읽는다."""
    _load_dotenv(PROJECT_ROOT / ".env")
    env = os.environ.get
    return DeliveryConfig(
        google_client_id=env("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=env("GOOGLE_CLIENT_SECRET", "").strip(),
        google_refresh_token=env("GOOGLE_REFRESH_TOKEN", "").strip(),
        drive_folder_id=env("DRIVE_FOLDER_ID", "").strip(),
        drive_folder_name=env("DRIVE_FOLDER_NAME", "뉴스 다이제스트").strip(),
        gmail_address=env("GMAIL_ADDRESS", "").strip(),
        gmail_app_password=env("GMAIL_APP_PASSWORD", "").strip(),
        mail_to=env("MAIL_TO", "").strip(),
        gemini_api_key=env("GEMINI_API_KEY", "").strip(),
        gemini_model=env("GEMINI_MODEL", "gemini-3.6-flash").strip(),
    )


def _load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
