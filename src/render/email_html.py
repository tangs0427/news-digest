"""메일 본문 HTML. Gmail 이 <style> 블록을 떼어내므로 전부 인라인 스타일로 쓴다."""

from __future__ import annotations

from datetime import tzinfo

from ..models import Digest
from .util import escape, format_header, meta_line

_FONT = "-apple-system, 'Segoe UI', 'Malgun Gothic', sans-serif"
_INK = "#1f2328"
_GRAY = "#5f6368"
_LINE = "#e4e6ea"
_ACCENT = "#1a56db"


def render(digest: Digest, tz: tzinfo, doc_url: str | None) -> str:
    parts: list[str] = [
        f"<div style=\"font-family:{_FONT}; color:{_INK}; max-width:640px; "
        'margin:0 auto; padding:24px 16px; line-height:1.5;">',
        f'<h1 style="font-size:20px; margin:0 0 4px;">{escape(digest.title)}</h1>',
        f'<div style="color:{_GRAY}; font-size:13px; margin-bottom:16px;">'
        f"{escape(format_header(digest.date, digest.total_articles))}</div>",
    ]

    if doc_url:
        parts.append(
            f'<div style="margin:0 0 24px;"><a href="{escape(doc_url, quote=True)}" '
            f'style="display:inline-block; background:{_ACCENT}; color:#ffffff; '
            'text-decoration:none; padding:10px 18px; border-radius:6px; '
            'font-size:14px;">Google Docs 에서 보기</a></div>'
        )

    if digest.summary_error:
        parts.append(
            '<div style="background:#fff8e6; border:1px solid #f0d9a0; border-radius:6px; '
            'padding:10px 14px; margin:0 0 20px; font-size:13px; color:#7a5c12;">'
            f"※ {escape(digest.summary_error)} 헤드라인만 정리했습니다.</div>"
        )
    if digest.overview:
        parts.append(
            '<div style="background:#f4f6f9; border-radius:8px; padding:16px 18px; '
            'margin:0 0 24px;">'
            f'<div style="font-size:13px; font-weight:700; color:{_ACCENT}; '
            'margin-bottom:8px;">오늘의 흐름</div>'
        )
        for line in digest.overview:
            parts.append(
                f'<div style="font-size:14px; margin:0 0 6px; padding-left:12px; '
                f'text-indent:-12px;">· {escape(line)}</div>'
            )
        parts.append("</div>")

    categories = digest.non_empty()
    if not categories:
        parts.append(
            f'<p style="color:{_GRAY};">오늘은 수집된 기사가 없습니다. '
            "피드 상태를 확인해 주세요.</p>"
        )

    for category in categories:
        parts.append(
            f'<div style="margin:24px 0 8px; padding-bottom:6px; '
            f'border-bottom:2px solid {_LINE}; font-size:15px; font-weight:700;">'
            f"{escape(category.label)} "
            f'<span style="color:{_GRAY}; font-weight:400;">({len(category.articles)})</span>'
            "</div>"
        )
        for index, article in enumerate(category.articles, start=1):
            summary = (
                f'<div style="font-size:13px; margin-top:3px; padding-left:18px; '
                f'color:#3d4450;">{escape(article.summary)}</div>'
                if article.summary
                else ""
            )
            parts.append(
                '<div style="margin:0 0 14px;">'
                f'<span style="color:{_GRAY}; font-size:13px;">{index}.</span> '
                f'<a href="{escape(article.url, quote=True)}" '
                f'style="color:{_INK}; text-decoration:none; font-size:14px; '
                'font-weight:600;">'
                f"{escape(article.title)}</a>"
                f"{summary}"
                f'<div style="color:{_GRAY}; font-size:12px; margin-top:3px; '
                f'padding-left:18px;">{escape(meta_line(article, tz))}</div>'
                "</div>"
            )

    parts.append(
        f'<div style="margin-top:32px; padding-top:12px; border-top:1px solid {_LINE}; '
        f'color:{_GRAY}; font-size:12px;">news-digest · 자동 생성</div>'
    )
    parts.append("</div>")
    return "\n".join(parts)


def render_text(digest: Digest, tz: tzinfo, doc_url: str | None) -> str:
    """HTML 을 못 읽는 클라이언트를 위한 대체 본문."""
    lines = [digest.title, format_header(digest.date, digest.total_articles), ""]
    if doc_url:
        lines += [f"문서: {doc_url}", ""]
    if digest.summary_error:
        lines += [f"※ {digest.summary_error} 헤드라인만 정리했습니다.", ""]
    if digest.overview:
        lines.append("[오늘의 흐름]")
        lines += [f"  - {line}" for line in digest.overview]
        lines.append("")
    for category in digest.non_empty():
        lines.append(f"[{category.label}]")
        for index, article in enumerate(category.articles, start=1):
            lines.append(f"  {index}. {article.title} ({meta_line(article, tz)})")
            if article.summary:
                lines.append(f"     {article.summary}")
            lines.append(f"     {article.url}")
        lines.append("")
    return "\n".join(lines)
