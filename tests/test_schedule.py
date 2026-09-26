"""아침 여러 회차 실행에 관한 회귀 테스트.

06:00 / 06:20 / 06:40 / 07:00 네 번 돌면서 '오늘 것을 이미 보냈는지'를
문서 제목으로 판단한다. 그래서 제목은 어디서 부르든 똑같아야 한다.
"""

from __future__ import annotations

import locale
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import Digest, digest_title  # noqa: E402

TZ = ZoneInfo("Asia/Seoul")


class TitleTest(unittest.TestCase):
    def test_known_weekday(self):
        # 2026-09-24 는 목요일
        self.assertEqual(
            digest_title(datetime(2026, 9, 24, tzinfo=TZ)),
            "뉴스 다이제스트 2026-09-24 (목)",
        )

    def test_all_weekdays_are_korean(self):
        # 2026-09-21(월) ~ 2026-09-27(일)
        expected = ["월", "화", "수", "목", "금", "토", "일"]
        for offset, day in enumerate(expected):
            title = digest_title(datetime(2026, 9, 21 + offset, tzinfo=TZ))
            self.assertTrue(title.endswith(f"({day})"), title)

    def test_stable_regardless_of_locale(self):
        """strftime('%a') 는 로케일에 따라 Thu/목/木 으로 갈린다.

        회차마다 제목이 달라지면 중복 판단이 깨져 하루에 여러 번 발송된다.
        """
        when = datetime(2026, 9, 24, tzinfo=TZ)
        baseline = digest_title(when)
        for candidate in ("C", "en_US.UTF-8", "ko_KR.UTF-8", ""):
            try:
                locale.setlocale(locale.LC_TIME, candidate)
            except locale.Error:
                continue
            self.assertEqual(digest_title(when), baseline)
        locale.setlocale(locale.LC_TIME, "C")

    def test_same_day_different_times_match(self):
        """앞 회차(06:00)와 마지막 회차(07:00)가 같은 제목을 봐야 한다."""
        morning = digest_title(datetime(2026, 9, 24, 6, 0, tzinfo=TZ))
        later = digest_title(datetime(2026, 9, 24, 7, 0, tzinfo=TZ))
        self.assertEqual(morning, later)

    def test_digest_property_matches_helper(self):
        when = datetime(2026, 9, 24, tzinfo=TZ)
        self.assertEqual(Digest(date=when).title, digest_title(when))

    def test_title_has_no_characters_that_break_drive_query(self):
        """드라이브 검색 질의에 작은따옴표가 섞이면 질의가 깨진다."""
        self.assertNotIn("'", digest_title(datetime(2026, 9, 24, tzinfo=TZ)))


if __name__ == "__main__":
    unittest.main()
