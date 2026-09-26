"""Google Docs 로 변환될 HTML 을 만든다.

드라이브의 HTML -> Docs 변환기는 시맨틱 태그(h1/h2/ol/li/a)를 문서 스타일로
옮겨 준다. 복잡한 CSS 는 대부분 무시되므로 태그 구조에 의존한다.
"""

from __future__ import annotations

from datetime import tzinfo

from ..models import Digest
from .util import escape, format_header, meta_line

_GRAY = "#5f6368"


def render(digest: Digest, tz: tzinfo) -> str:
    parts: list[str] = [
        "<html><head><meta charset='utf-8'></head><body>",
        f"<h1>{escape(digest.title)}</h1>",
        f"<p><span style='color:{_GRAY}'>"
        f"{escape(format_header(digest.date, digest.total_articles))}"
        "</span></p>",
    ]

    if digest.summary_error:
        parts.append(
            f"<p><span style='color:{_GRAY}'>※ {escape(digest.summary_error)} "
            "헤드라인만 정리했습니다.</span></p>"
        )
    if digest.overview:
        parts.append("<h2>오늘의 흐름</h2>")
        parts.append("<ul>")
        parts.extend(f"<li>{escape(line)}</li>" for line in digest.overview)
        parts.append("</ul>")

    categories = digest.non_empty()
    if not categories:
        parts.append("<p>오늘은 수집된 기사가 없습니다. 피드 상태를 확인해 주세요.</p>")
    for category in categories:
        parts.append(f"<h2>{escape(category.label)} ({len(category.articles)})</h2>")
        if category.description:
            parts.append(
                f"<p><span style='color:{_GRAY}'>{escape(category.description)}</span></p>"
            )
        parts.append("<ol>")
        for article in category.articles:
            meta = escape(meta_line(article, tz))
            summary = (
                f"<br>{escape(article.summary)}" if article.summary else ""
            )
            parts.append(
                "<li>"
                f"<a href=\"{escape(article.url, quote=True)}\">{escape(article.title)}</a>"
                f"{summary}"
                f"<br><span style='color:{_GRAY}; font-size:9pt'>{meta}</span>"
                "</li>"
            )
        parts.append("</ol>")

    parts.append("</body></html>")
    return "\n".join(parts)
