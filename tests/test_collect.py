"""수집 단계 회귀 테스트.

의존성 없이 돌도록 표준 라이브러리 unittest 만 쓴다.

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.collect import dedupe, filters  # noqa: E402
from src.collect.rss import _apply_alias, _clean_title  # noqa: E402
from src.models import Article  # noqa: E402


def make(title: str, url: str = "", source: str = "테스트") -> Article:
    return Article(
        title=title,
        url=url or f"https://example.com/{abs(hash(title))}",
        source=source,
        feed_name="테스트 피드",
        category_key="test",
        published=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )


class CleanTitleTest(unittest.TestCase):
    def test_strips_google_news_suffix(self):
        self.assertEqual(
            _clean_title("코스피 강보합 마감 - 연합뉴스", "연합뉴스"),
            "코스피 강보합 마감",
        )

    def test_strips_doubled_suffix(self):
        """언론사 RSS + 구글 뉴스가 매체명을 두 번 붙이는 실제 사례."""
        self.assertEqual(
            _clean_title("증권사들 AI 플랫폼 확대 - 조선비즈 - Chosunbiz", "Chosunbiz"),
            "증권사들 AI 플랫폼 확대",
        )

    def test_keeps_numeric_tail(self):
        """' - 매출 79조' 처럼 숫자가 든 꼬리는 제목의 일부이므로 남긴다."""
        title = "삼성전자 3분기 실적 - 매출 79조"
        self.assertEqual(_clean_title(title, "한국경제"), title)

    def test_unescapes_entities(self):
        self.assertEqual(
            _clean_title("&quot;금리 부담&quot; 커졌다", "매일경제"),
            '"금리 부담" 커졌다',
        )

    def test_alias_is_case_insensitive(self):
        self.assertEqual(_apply_alias("Chosunbiz", {"chosunbiz": "조선비즈"}), "조선비즈")
        self.assertEqual(_apply_alias("알수없는곳", {}), "알수없는곳")


class DedupeTest(unittest.TestCase):
    def test_drops_identical_urls(self):
        a = make("코스피 상승", url="https://x.com/1")
        b = make("완전히 다른 제목입니다", url="https://x.com/1")
        self.assertEqual(len(dedupe.dedupe([a, b])), 1)

    def test_drops_near_identical_titles(self):
        kept = dedupe.dedupe(
            [
                make("코스피 금리 인상에도 상승 마감"),
                make("[속보] 코스피 금리 인상에도 상승 마감"),
            ]
        )
        self.assertEqual(len(kept), 1)

    def test_keeps_distinct_stories(self):
        kept = dedupe.dedupe(
            [
                make("코스피 금리 인상에도 상승 마감"),
                make("CJ그룹 하반기 신입 공채 확대"),
            ]
        )
        self.assertEqual(len(kept), 2)

    def test_first_category_wins_across_categories(self):
        grouped = {
            "market": [make("삼성전자 반도체 수출 증가")],
            "industry": [make("삼성전자 반도체 수출 증가세 지속")],
        }
        result = dedupe.dedupe_across(grouped, ["market", "industry"])
        self.assertEqual(len(result["market"]), 1)
        self.assertEqual(len(result["industry"]), 0)


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.rules = filters.FilterRules.from_raw(
            {
                "min_title_length": 8,
                "exclude_sources": ["네이버 블로그"],
                "exclude_title_patterns": [
                    "특징주",
                    "(부친상|모친상)",
                    "[:：]\\s*네이버 블로그\\s*$",
                ],
            }
        )

    def test_blocks_excluded_source(self):
        article = make("반도체 수출 증가세 뚜렷하다", source="네이버 블로그")
        self.assertIsNotNone(self.rules.rejects(article))

    def test_blocks_pattern(self):
        self.assertIsNotNone(self.rules.rejects(make("[美특징주]레나, 실적 부진")))
        self.assertIsNotNone(self.rules.rejects(make("한광수 딜로이트 회계사 부친상")))
        self.assertIsNotNone(self.rules.rejects(make("8월 수출 급감 : 네이버 블로그")))

    def test_blocks_short_title(self):
        self.assertIsNotNone(self.rules.rejects(make("짧음")))

    def test_allows_normal_article(self):
        self.assertIsNone(self.rules.rejects(make("SK온, 엘앤에프와 공급 계약 체결")))

    def test_apply_returns_survivors(self):
        articles = [
            make("SK온, 엘앤에프와 공급 계약 체결"),
            make("[美특징주]레나, 실적 부진"),
        ]
        self.assertEqual(len(filters.apply(articles, self.rules)), 1)


if __name__ == "__main__":
    unittest.main()
