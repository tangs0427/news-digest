"""엔트리포인트.

    python -m src.main                # 수집 -> 문서 생성 -> 메일 발송
    python -m src.main --dry-run      # 수집만 하고 결과를 로컬 HTML 로 저장
    python -m src.main --check-feeds  # 피드가 살아 있는지만 점검
    python -m src.main --no-ai        # 요약 없이 (무료 한도를 아낄 때)

아침에 여러 회차를 돌릴 때:

    # 06:00 / 06:20 / 06:40 — 요약이 온전할 때만 발송
    python -m src.main --skip-if-sent --require-summary
    # 07:00 — 마지막이므로 요약이 없어도 발송
    python -m src.main --skip-if-sent
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import PROJECT_ROOT, SourceConfig, load_delivery, load_sources
from .collect import rss
from .deliver import google_docs, mail
from .models import digest_title
from .pipeline import build_digest
from .render import doc_html, email_html
from .summarize import gemini

log = logging.getLogger("news-digest")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)


def _todays_title(config: SourceConfig) -> str:
    return digest_title(datetime.now(ZoneInfo(config.timezone)))


def check_feeds() -> int:
    """모든 피드를 한 번씩 때려보고 항목 수를 출력한다."""
    config = load_sources()
    broken = 0
    for category in config.categories:
        print(f"\n[{category.label}]")
        for feed in category.feeds:
            entries = rss.fetch_feed(feed)
            status = "OK " if entries else "실패"
            if not entries:
                broken += 1
            print(f"  {status} {feed.name:<24} {len(entries):>3}건")
    print(f"\n피드 {sum(len(c.feeds) for c in config.categories)}개 중 실패 {broken}개")
    return 1 if broken else 0


def run(
    dry_run: bool,
    out_path: Path | None,
    use_ai: bool,
    skip_if_sent: bool = False,
    require_summary: bool = False,
) -> int:
    config = load_sources()
    tz = ZoneInfo(config.timezone)
    delivery = load_delivery()

    # 앞선 회차가 이미 보냈으면 수집조차 하지 않고 끝낸다.
    if skip_if_sent and not dry_run:
        if delivery.can_upload_docs:
            title = _todays_title(config)
            existing = google_docs.find_doc(delivery, title)
            if existing:
                log.info("오늘 문서가 이미 있습니다. 건너뜁니다 — %s", existing)
                return 0
        elif require_summary:
            # 드라이브가 없으면 '이미 보냈는지'를 알 방법이 없다. 이 상태로
            # 회차마다 발송하면 하루 네 번 메일이 간다. 마지막 회차에 맡긴다.
            log.warning(
                "Google 인증이 없어 중복 확인을 할 수 없습니다. "
                "중복 발송을 막기 위해 이번 회차는 건너뜁니다(마지막 회차에 발송)."
            )
            return 0

    digest = build_digest(config)
    log.info("총 %d건 수집 완료", digest.total_articles)

    if digest.total_articles == 0:
        log.error("수집된 기사가 없습니다. --check-feeds 로 피드를 점검하세요.")
        return 1

    # 요약은 실패해도 발송을 막지 않는다. 요약만 빠진 채로 나간다.
    summarized = False
    if use_ai:
        summarized = gemini.summarize(digest, delivery)
    else:
        log.info("--no-ai: 요약 없이 진행합니다.")

    # 아침 재시도 회차에서는 요약이 온전할 때만 보낸다. 마지막 회차는
    # --require-summary 없이 불리므로 무조건 발송된다.
    if require_summary and not (summarized and not digest.summary_error):
        log.warning("요약이 온전하지 않아 이번 회차는 발송하지 않습니다. 다음 회차에 다시 시도합니다.")
        return 0

    document_html = doc_html.render(digest, tz)

    if dry_run:
        target = out_path or (PROJECT_ROOT / "output" / f"{digest.date:%Y-%m-%d}.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document_html, encoding="utf-8")
        log.info("드라이런: %s 에 저장했습니다.", target)
        return 0

    doc_url: str | None = None
    if delivery.can_upload_docs:
        doc_url = google_docs.upload_doc(delivery, digest.title, document_html)
    else:
        log.warning("Google 인증 정보가 없어 문서 생성을 건너뜁니다.")

    mail_ok = True
    if delivery.can_send_mail:
        mail_ok = mail.send(
            delivery,
            subject=digest.title,
            html_body=email_html.render(digest, tz, doc_url),
            text_body=email_html.render_text(digest, tz, doc_url),
        )
    else:
        log.warning("메일 인증 정보가 없어 발송을 건너뜁니다.")

    if delivery.can_upload_docs and not doc_url:
        return 1
    if delivery.can_send_mail and not mail_ok:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="매일 아침 뉴스 다이제스트")
    parser.add_argument("--dry-run", action="store_true", help="문서/메일 없이 로컬 저장")
    parser.add_argument("--check-feeds", action="store_true", help="피드 상태만 점검")
    parser.add_argument("--no-ai", action="store_true", help="AI 요약 없이 헤드라인만")
    parser.add_argument(
        "--skip-if-sent",
        action="store_true",
        help="오늘 문서가 드라이브에 이미 있으면 아무것도 하지 않고 종료",
    )
    parser.add_argument(
        "--require-summary",
        action="store_true",
        help="요약이 온전할 때만 발송 (아침 재시도 회차용)",
    )
    parser.add_argument("--out", type=Path, help="드라이런 결과 저장 경로")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    if args.check_feeds:
        return check_feeds()
    return run(
        dry_run=args.dry_run,
        out_path=args.out,
        use_ai=not args.no_ai,
        skip_if_sent=args.skip_if_sent,
        require_summary=args.require_summary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
