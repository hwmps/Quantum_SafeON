import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import weather_kma  # noqa: E402


class ParseSfcdd3Tests(unittest.TestCase):
    def test_parses_numbered_official_help_header(self):
        response = """#START7777
#  1. TM            : 관측일 (KST)
#  2. STN           : 국내 지점번호
#  3. WS_AVG        : 일 평균 풍속 (m/s)
#  4. WR_DAY        : 일 풍정 (m)
#  5. WD_MAX        : 최대풍향
#  6. WS_MAX        : 최대풍속 (m/s)
20260720 108 2.1 181440 270 5.4
"""

        rows, error = weather_kma.parse_sfcdd3(response)

        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tm"], "20260720")
        self.assertEqual(rows[0]["stn"], "108")
        self.assertEqual(rows[0]["ws_avg_ms"], 2.1)
        self.assertEqual(rows[0]["ws_max_ms"], 5.4)
        self.assertEqual(rows[0]["wd_max_deg"], 270.0)
        self.assertEqual(rows[0]["_ncols"], 6)

    def test_keeps_support_for_single_line_header(self):
        response = """# TM STN WS_AVG WR_DAY WD_MAX WS_MAX
20260720 108 2.1 181440 270 5.4
"""

        rows, error = weather_kma.parse_sfcdd3(response)

        self.assertIsNone(error)
        self.assertEqual(rows[0]["ws_avg_ms"], 2.1)
        self.assertEqual(rows[0]["ws_max_ms"], 5.4)
        self.assertEqual(rows[0]["wd_max_deg"], 270.0)

    def test_rejects_response_without_auditable_header(self):
        rows, error = weather_kma.parse_sfcdd3("20260720 108 2.1 181440 270 5.4")

        self.assertIsNone(rows)
        self.assertIn("컬럼명 헤더", error)


if __name__ == "__main__":
    unittest.main()
