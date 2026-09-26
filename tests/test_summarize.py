"""요약 단계 회귀 테스트. 실제 API 는 부르지 않는다."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.collect.rss import _clean_description  # noqa: E402
from src.models import Article, CategoryDigest, Digest  # noqa: E402
from src.render import doc_html, email_html  # noqa: E402
from src.summarize.gemini import (  # noqa: E402
    MAX_TOTAL_CALLS,
    _extract_json,
    _is_daily_quota,
    _retry_delay,
)
from src.summarize.prompt import (  # noqa: E402
    apply_overview,
    apply_summaries,
    build_overview_prompt,
    build_summary_prompt,
    flatten,
)

TZ = ZoneInfo("Asia/Seoul")


def make_digest() -> Digest:
    def article(title: str, key: str, desc: str = "") -> Article:
        return Article(
            title=title,
            url=f"https://example.com/{abs(hash(title))}",
            source="연합뉴스",
            feed_name="피드",
            category_key=key,
            published=datetime(2026, 9, 24, tzinfo=timezone.utc),
            description=desc,
        )

    return Digest(
        date=datetime(2026, 9, 24, tzinfo=TZ),
        categories=[
            CategoryDigest(
                "market", "시장 · 거시", "",
                [
                    article("코스피 약보합 마감", "market", "외국인 매도가 이어졌다." * 3),
                    article("환율 1380원 돌파", "market"),
                ],
            ),
            CategoryDigest("empty", "빈 카테고리", "", []),
            CategoryDigest(
                "career", "채용 · 커리어", "",
                [article("CJ 하반기 공채 40% 확대", "career")],
            ),
        ],
    )


def fill(digest: Digest, overview: list[str], texts: dict[str, list[str]]) -> None:
    """테스트용으로 요약을 채운다."""
    apply_overview(digest, {"overview": overview})
    for category in digest.non_empty():
        rows = texts.get(category.key, [])
        apply_summaries(
            category, {"summaries": [{"id": i, "text": t} for i, t in enumerate(rows)]}
        )


class DescriptionTest(unittest.TestCase):
    def test_strips_wire_prefix(self):
        raw = "(서울=연합뉴스) 한주홍 기자 = 출생아 감소로 침체했던 분유 시장이 회복세를 보이고 있다."
        self.assertTrue(_clean_description(raw, "분유 시장 회복").startswith("출생아 감소로"))

    def test_strips_html_tags(self):
        raw = "<p>외국인 매도가 이어지며 <b>코스피</b>가 약보합으로 마감했다고 전해졌다.</p>"
        cleaned = _clean_description(raw, "코스피 마감")
        self.assertNotIn("<", cleaned)
        self.assertIn("코스피", cleaned)

    def test_drops_google_news_title_echo(self):
        """구글 뉴스는 description 에 제목과 도메인만 되풀이한다."""
        title = "제미나이도 탈옥했다…구글 AI 에이전트 해킹 시인"
        self.assertEqual(_clean_description(f"{title} v.daum.net", title), "")

    def test_drops_too_short(self):
        self.assertEqual(_clean_description("짧은 설명", "제목"), "")


class PromptTest(unittest.TestCase):
    def test_summary_prompt_is_per_category(self):
        """60건을 한 번에 보내면 API 가 503 을 낸다. 카테고리 단위여야 한다."""
        digest = make_digest()
        market = digest.categories[0]
        prompt = build_summary_prompt(market, digest)
        self.assertIn("코스피 약보합 마감", prompt)
        self.assertIn("환율 1380원 돌파", prompt)
        # 다른 카테고리 기사는 들어가면 안 된다
        self.assertNotIn("CJ 하반기 공채", prompt)

    def test_summary_prompt_includes_body_only_when_present(self):
        digest = make_digest()
        prompt = build_summary_prompt(digest.categories[0], digest)
        self.assertEqual(prompt.count('"body"'), 1)

    def test_summary_ids_restart_per_category(self):
        digest = make_digest()
        career = build_summary_prompt(digest.categories[2], digest)
        self.assertIn('"id": 0', career)

    def test_overview_prompt_has_titles_without_bodies(self):
        digest = make_digest()
        prompt = build_overview_prompt(digest)
        self.assertIn("코스피 약보합 마감", prompt)
        self.assertIn("CJ 하반기 공채 40% 확대", prompt)
        # 흐름 요청은 가벼워야 하므로 본문을 넣지 않는다
        self.assertNotIn("외국인 매도가 이어졌다.", prompt)

    def test_overview_prompt_skips_empty_category(self):
        self.assertNotIn("빈 카테고리", build_overview_prompt(make_digest()))

    def test_apply_summaries_maps_ids(self):
        digest = make_digest()
        applied = apply_summaries(
            digest.categories[0],
            {"summaries": [{"id": 0, "text": "약보합 마감했다."},
                           {"id": 1, "text": "환율이 올랐다."}]},
        )
        self.assertEqual(applied, 2)
        self.assertEqual(digest.categories[0].articles[0].summary, "약보합 마감했다.")

    def test_apply_summaries_ignores_bad_rows(self):
        digest = make_digest()
        applied = apply_summaries(
            digest.categories[0],
            {"summaries": [
                {"id": 99, "text": "범위 밖"},
                {"id": "abc", "text": "숫자 아님"},
                {"id": 0, "text": ""},
                "문자열",
                {"id": 1, "text": "정상"},
            ]},
        )
        self.assertEqual(applied, 1)
        self.assertEqual(digest.categories[0].articles[0].summary, "")

    def test_apply_overview_drops_blanks(self):
        digest = make_digest()
        count = apply_overview(digest, {"overview": ["첫 줄", "   ", "둘째 줄", 42]})
        self.assertEqual(count, 2)
        self.assertEqual(digest.overview, ["첫 줄", "둘째 줄"])

    def test_flatten_skips_empty_categories(self):
        self.assertEqual(len(flatten(make_digest())), 3)


class ExtractJsonTest(unittest.TestCase):
    def test_parses_normal_response(self):
        payload = {"candidates": [{"content": {"parts": [{"text": '{"summaries": []}'}]}}]}
        self.assertEqual(_extract_json(payload), {"summaries": []})

    def test_joins_split_parts(self):
        payload = {"candidates": [{"content": {"parts": [
            {"text": '{"overview": []'}, {"text": "}"}]}}]}
        self.assertEqual(_extract_json(payload), {"overview": []})

    def test_raises_on_blocked_response(self):
        with self.assertRaises(ValueError):
            _extract_json({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}})

    def test_raises_on_empty_text(self):
        with self.assertRaises(ValueError):
            _extract_json({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class QuotaTest(unittest.TestCase):
    """무료 티어는 모델당 하루 20회. 일일 한도는 기다려도 안 풀린다."""

    @staticmethod
    def _quota(quota_id: str) -> _FakeResponse:
        return _FakeResponse({"error": {"details": [{
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaId": quota_id}],
        }]}})

    def test_detects_daily_quota(self):
        response = self._quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        self.assertTrue(_is_daily_quota(response))

    def test_minute_quota_is_not_daily(self):
        """분당 한도는 잠깐 기다리면 풀리므로 모델을 버리면 안 된다."""
        response = self._quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
        self.assertFalse(_is_daily_quota(response))

    def test_no_quota_details(self):
        self.assertFalse(_is_daily_quota(_FakeResponse({"error": {}})))

    def test_retry_delay_parsed(self):
        response = _FakeResponse({"error": {"details": [{
            "@type": "type.googleapis.com/google.rpc.RetryInfo",
            "retryDelay": "23s",
        }]}})
        self.assertEqual(_retry_delay(response), 23.0)

    def test_retry_delay_absent(self):
        self.assertIsNone(_retry_delay(_FakeResponse({"error": {"details": []}})))

    def test_call_budget_leaves_room_under_daily_limit(self):
        """정상 경로는 6회(카테고리 5 + 흐름 1). 아침에 4회차를 돌리므로
        회차당 상한이 20을 넘으면 하루치 한도가 한 회차에 날아간다."""
        self.assertLess(MAX_TOTAL_CALLS, 20)
        self.assertGreaterEqual(MAX_TOTAL_CALLS, 6)


class RenderTest(unittest.TestCase):
    """요약이 있을 때·없을 때·실패했을 때 모두 렌더가 깨지지 않아야 한다."""

    def test_renders_without_summaries(self):
        digest = make_digest()
        self.assertIn("코스피 약보합 마감", doc_html.render(digest, TZ))
        self.assertIn("코스피 약보합 마감", email_html.render(digest, TZ, None))
        self.assertNotIn("오늘의 흐름", doc_html.render(digest, TZ))

    def test_renders_with_summaries(self):
        digest = make_digest()
        fill(digest, ["금리 인상 여파가 이어졌다."],
             {"market": ["약보합 마감했다.", "환율이 올랐다."], "career": ["채용을 늘렸다."]})
        for out in (doc_html.render(digest, TZ), email_html.render(digest, TZ, None)):
            self.assertIn("오늘의 흐름", out)
            self.assertIn("금리 인상 여파가 이어졌다.", out)
            self.assertIn("약보합 마감했다.", out)

    def test_shows_failure_notice(self):
        """요약이 조용히 빠지면 왜 없는지 알 수 없다."""
        digest = make_digest()
        digest.summary_error = "Gemini 호출에 실패해 요약을 만들지 못했습니다."
        for out in (doc_html.render(digest, TZ), email_html.render(digest, TZ, None)):
            self.assertIn("요약을 만들지 못했습니다", out)
        self.assertIn("요약을 만들지 못했습니다", email_html.render_text(digest, TZ, None))

    def test_text_body_includes_summary(self):
        digest = make_digest()
        fill(digest, ["흐름"], {"market": ["한 줄 요약"]})
        text = email_html.render_text(digest, TZ, None)
        self.assertIn("[오늘의 흐름]", text)
        self.assertIn("한 줄 요약", text)

    def test_escapes_html_in_summary(self):
        digest = make_digest()
        fill(digest, ["<b>흐름</b>"], {"market": ["<script>alert(1)</script>"]})
        for out in (doc_html.render(digest, TZ), email_html.render(digest, TZ, None)):
            self.assertNotIn("<script>", out)
            self.assertIn("&lt;script&gt;", out)


if __name__ == "__main__":
    unittest.main()
