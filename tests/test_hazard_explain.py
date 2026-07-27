# -*- coding: utf-8 -*-
"""hazard_explain 회귀 테스트 (PM 지시 2026-07-27 1·2순위 구현분)

핵심 검증 3가지
1) 하위 호환: 재해 발생원이 없으면 위험도가 정확히 기준값(0.5)이고 배수가 1.0이다.
2) 풍향 방향성: 풍하측 구역만 가중되고 풍상측은 ×1.0 그대로다.
3) 대피 경로: 발생원 반경 안 출구는 후보에서 제외되고, 위험 가중 최소 경로가 선택된다.

실행: python tests/test_hazard_explain.py   (unittest, 외부 의존 없음)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import hazard_explain as hx  # noqa: E402

WEATHER = {"wd_deg": 33.8, "ws_ms": 3.8, "출처": "테스트", "평균_풍속_m_s": 2.54,
           "최대_풍속_m_s": 4.3, "stn": "108", "n": 25}


def grid(rows, cols, w=30.0, h=20.0):
    zw, zh = w / cols, h / rows
    return [{"id": f"G{r * cols + c + 1}", "x0": c * zw, "y0": r * zh,
             "x1": (c + 1) * zw, "y1": (r + 1) * zh}
            for r in range(rows) for c in range(cols)]


class TestCompass(unittest.TestCase):
    def test_16방위_경계(self):
        self.assertEqual(hx.compass_name(0), "북")
        self.assertEqual(hx.compass_name(90), "동")
        self.assertEqual(hx.compass_name(180), "남")
        self.assertEqual(hx.compass_name(270), "서")
        self.assertEqual(hx.compass_name(33.8), "북동")      # 22.5~45 구간
        self.assertEqual(hx.compass_name(213.8), "남서")     # 풍하 방향
        self.assertEqual(hx.compass_name(359.9), "북")       # 순환
        self.assertIsNone(hx.compass_name(None))

    def test_풍속_등급_경계(self):
        self.assertEqual(hx.wind_grade(0.0), "무풍")
        self.assertEqual(hx.wind_grade(1.9), "정온")
        self.assertEqual(hx.wind_grade(2.0), "보통")
        self.assertEqual(hx.wind_grade(8.0), "강풍")


class TestWindContext(unittest.TestCase):
    def test_관측없음(self):
        wc = hx.wind_context(None)
        self.assertFalse(wc["있음"])
        self.assertTrue(wc["설명"])

    def test_관측있음_이동방향은_풍향의_반대(self):
        wc = hx.wind_context(WEATHER)
        self.assertTrue(wc["있음"])
        self.assertEqual(wc["풍향_방위"], "북동")
        self.assertEqual(wc["이동_방위"], "남서")
        self.assertAlmostEqual(wc["이동_방위_deg"], 213.8, places=6)
        # 3.8/10 × 35% = 13.3%
        self.assertAlmostEqual(wc["최대_풍하측_가중_pct"], 13.3, places=1)
        self.assertIn("한계", wc)

    def test_무풍은_방향보정_안내(self):
        wc = hx.wind_context({"wd_deg": 90.0, "ws_ms": 0.2})
        self.assertEqual(wc["등급"], "무풍")
        self.assertTrue(any("무풍" in s for s in wc["설명"]))


class TestZoneRisk(unittest.TestCase):
    def test_발생원_없으면_기준값_유지(self):
        centers = [(1.0, 1.0), (10.0, 10.0)]
        risk, detail = hx.zone_hazard_risk(centers, [], weather=WEATHER, base=0.5)
        self.assertEqual(risk, [0.5, 0.5])
        self.assertEqual(detail, [])

    def test_풍하측만_추가가중(self):
        # 발생원 (15,10). 풍향 33.8° → 이동 방향 남서(x-, y-... 방위 213.8°)
        src = [{"id": "F1", "kind": "fire", "x_m": 15.0, "y_m": 10.0,
                "radius_m": 3.0, "intensity": 1.0}]
        # 방위 213.8° = 남남서~남서: 동성분 sin(213.8°)<0, 북성분 cos(213.8°)<0
        down = (15.0 - 6.0, 10.0 - 7.5)   # 서·남 쪽 = 풍하측
        up = (15.0 + 9.0, 10.0 + 7.5)     # 동·북 쪽 = 풍상측
        risk, detail = hx.zone_hazard_risk([down, up], src, weather=WEATHER)
        self.assertTrue(detail[0]["풍하측"], "풍하측 구역은 등방보다 커야 한다")
        self.assertFalse(detail[1]["풍하측"], "풍상측 구역은 보정하지 않는다")
        self.assertGreater(detail[0]["배수"], detail[0]["등방_배수"])
        self.assertAlmostEqual(detail[1]["배수"], detail[1]["등방_배수"], places=6)

    def test_다중발생원은_최대값_사용(self):
        a = {"id": "F1", "kind": "fire", "x_m": 0.0, "y_m": 0.0, "radius_m": 5.0, "intensity": 1.0}
        b = {"id": "F2", "kind": "fire", "x_m": 1.0, "y_m": 0.0, "radius_m": 5.0, "intensity": 1.0}
        one, _ = hx.zone_hazard_risk([(0.5, 0.0)], [a], weather=None)
        two, _ = hx.zone_hazard_risk([(0.5, 0.0)], [a, b], weather=None)
        self.assertEqual(one, two, "발생원을 더해도 합산되지 않고 지배 발생원 값이어야 한다")


class TestSensorEffect(unittest.TestCase):
    SENSORS = [{"id": "S1", "x_m": 10.0, "y_m": 10.0, "radius_m": 5.0},
               {"id": "S2", "x_m": 28.0, "y_m": 2.0, "radius_m": 5.0}]
    HAZ = [{"id": "F1", "kind": "gas_leak", "x_m": 11.0, "y_m": 10.0,
            "radius_m": 4.0, "intensity": 1.0}]

    def test_재해없으면_계산안함(self):
        eff = hx.sensor_hazard_effect(self.SENSORS, [], weather=WEATHER)
        self.assertFalse(eff["S1"]["재해_적용"])

    def test_가까운센서는_감지기여_있고_먼센서는_없다(self):
        eff = hx.sensor_hazard_effect(self.SENSORS, self.HAZ, weather=WEATHER)
        self.assertTrue(eff["S1"]["재해_적용"])
        self.assertGreater(eff["S1"]["감지_기여_pct"], 50.0)
        self.assertTrue(eff["S1"]["반경내"])
        self.assertEqual(eff["S2"]["감지_기여_pct"], 0.0)
        self.assertGreater(eff["S2"]["여유_거리_m"], 0.0)
        for v in eff.values():
            self.assertTrue(v["설명"])

    def test_원_교차_면적비(self):
        # 완전 포함: 발생원(r=1)이 센서 커버(r=5) 안 → 1.0
        self.assertAlmostEqual(hx._circle_overlap_ratio(0, 0, 5, 0, 0, 1), 1.0, places=9)
        # 완전 분리 → 0.0
        self.assertEqual(hx._circle_overlap_ratio(0, 0, 2, 10, 0, 2), 0.0)
        # 중심 일치·센서가 더 작음 → 면적비 (r1/r2)^2
        self.assertAlmostEqual(hx._circle_overlap_ratio(0, 0, 1, 0, 0, 2), 0.25, places=9)
        # 반쯤 겹침 → 0과 1 사이
        r = hx._circle_overlap_ratio(0, 0, 3, 3, 0, 3)
        self.assertTrue(0.0 < r < 1.0)


class TestEvacuation(unittest.TestCase):
    def test_발생원_반경안_출구는_제외(self):
        zones = grid(3, 4)                      # 구역 12개, 출구 기본 G1·G4·G9·G12
        haz = [{"id": "F1", "kind": "fire", "x_m": 3.75, "y_m": 3.33,
                "radius_m": 6.0, "intensity": 1.0}]   # G1 중심 위
        risk, _ = hx.zone_hazard_risk(
            [((z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2) for z in zones], haz, weather=WEATHER)
        out = hx.evacuation_demo(zones, 3, 4, risk, hazards=haz, weather=WEATHER)
        self.assertTrue(out["active"])
        blocked = [e for e in out["exits"] if not e["usable"]]
        self.assertTrue(blocked, "발생원 반경 안 출구가 폐쇄로 표시되어야 한다")
        self.assertEqual(blocked[0]["zone"], "G1")
        self.assertNotEqual(out["exit"], blocked[0]["id"], "폐쇄된 출구를 선택하면 안 된다")
        self.assertTrue(any("폐쇄 출구" in s for s in out["설명"]))
        self.assertGreaterEqual(len(out["polyline"]), 2)

    def test_재해없으면_경로계산은_되고_위험도는_균일(self):
        zones = grid(3, 4)
        risk = [0.5] * 12
        out = hx.evacuation_demo(zones, 3, 4, risk, hazards=[], weather=None)
        self.assertTrue(out["active"])
        self.assertEqual(out["지표"]["최대_통과_위험도"], 0.5)
        self.assertTrue(all(e["usable"] for e in out["exits"]))

    def test_법정_보행거리_초과_판정(self):
        # 가로 200 m 현장을 1×3 격자로 두고 맨 오른쪽 끝에만 출구를 두면 보행거리가 30 m를 넘는다
        zones = grid(1, 3, w=200.0, h=20.0)
        out = hx.evacuation_plan(zones, 1, 3, [0.5] * 3,
                                 exits=[{"id": "EX1", "x_m": 200.0, "y_m": 10.0}],
                                 origins=[{"id": "W1", "x_m": 2.0, "y_m": 10.0, "n": 10}])
        self.assertTrue(out["active"])
        r = out["routes"][0]
        self.assertTrue(r["지표"]["법정_보행거리_초과"])
        self.assertGreater(r["지표"]["초과_m"], 0.0)
        self.assertTrue(any("초과" in s for s in out["설명"]))

    def test_격자불일치는_비활성(self):
        out = hx.evacuation_demo(grid(3, 4), 2, 2, [0.5] * 12)
        self.assertFalse(out["active"])


class TestEvacuationPlan(unittest.TestCase):
    """출구 입력값 + 출발 위치별 경로 서술 + 통로 공유(혼잡) — PM 지시 2026-07-27."""

    ZONES = grid(3, 4)          # 30 m × 20 m, 구역 12개

    def test_출구_입력이_없으면_가정으로_표기(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12)
        self.assertTrue(out["active"])
        self.assertFalse(out["출구_입력"])
        self.assertTrue(any("가정" in s for s in out["설명"]))
        self.assertEqual(len(out["exits"]), 4)

    def test_입력한_출구_좌표를_그대로_사용(self):
        exits = [{"id": "정문", "x_m": 29.0, "y_m": 10.0},
                 {"id": "후문", "x_m": 1.0, "y_m": 1.0}]
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12, exits=exits)
        self.assertTrue(out["출구_입력"])
        self.assertEqual([e["id"] for e in out["exits"]], ["정문", "후문"])
        self.assertEqual(out["exits"][0]["x_m"], 29.0)
        # 출구가 속한 구역이 좌표로부터 확정된다
        self.assertEqual(out["exits"][1]["zone"], "G1")
        # 모든 경로의 도착 출구는 입력한 두 곳 중 하나다
        for r in out["routes"]:
            self.assertIn(r["exit"], ("정문", "후문"))

    def test_출발_지정이_없으면_전_구역_자동(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0}])
        self.assertFalse(out["출발_입력"])
        # 출구 구역(G8)을 제외한 11개 구역이 출발점
        self.assertEqual(len(out["routes"]), 11)
        self.assertTrue(all(r["지표"]["거리_m"] > 0 for r in out["routes"]))

    def test_작업자_위치_지정시_그_지점만(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0},
                                        {"id": "EX2", "x_m": 1.0, "y_m": 18.0}],
                                 origins=[{"id": "W1", "x_m": 5.0, "y_m": 5.0, "n": 12},
                                          {"id": "W2", "x_m": 25.0, "y_m": 15.0, "n": 8}])
        self.assertTrue(out["출발_입력"])
        self.assertEqual([r["origin"] for r in out["routes"]], ["W1", "W2"])
        self.assertEqual(out["routes"][0]["n"], 12.0)
        # 출발 지점 좌표가 경로 폴리라인의 첫 점이다
        self.assertEqual(out["routes"][0]["polyline"][0], {"x_m": 5.0, "y_m": 5.0})
        # 출발 위치별 서술 문장이 존재하고 출구 선택 근거를 담는다
        for r in out["routes"]:
            self.assertTrue(r["설명"])
            self.assertTrue(any("출구 선택 근거" in s for s in r["설명"]))

    def test_위험구역_회피로_먼_출구를_고른다(self):
        # 오른쪽 열(G4·G8·G12)만 매우 위험 → 오른쪽 출구가 가까워도 왼쪽 출구를 택해야 한다
        risk = [0.1] * 12
        for i in (3, 7, 11):
            risk[i] = 1.0
        out = hx.evacuation_plan(self.ZONES, 3, 4, risk,
                                 exits=[{"id": "R", "x_m": 29.5, "y_m": 10.0},
                                        {"id": "L", "x_m": 0.5, "y_m": 10.0}],
                                 origins=[{"id": "W1", "x_m": 20.0, "y_m": 10.0, "n": 5}])
        r = out["routes"][0]
        self.assertEqual(r["exit"], "L", "위험 가중을 반영하면 먼 왼쪽 출구가 선택되어야 한다")
        self.assertEqual(r["최단거리_대안"]["exit"], "R")
        self.assertTrue(any("가까운 문" in s for s in r["설명"]))

    def test_통로_공유_구간과_지연_계산(self):
        # 출구 1곳뿐이면 여러 출발점이 같은 통로로 몰린다
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0}],
                                 origins=[{"id": "W1", "x_m": 2.0, "y_m": 10.0, "n": 30},
                                          {"id": "W2", "x_m": 10.0, "y_m": 10.0, "n": 30}])
        c = out["혼잡"]
        self.assertGreater(c["공유_구간_수"], 0)
        top = c["공유_구간"][0]
        self.assertEqual(top["출발점_수"], 2)
        self.assertEqual(top["인원"], 60.0)
        self.assertGreater(top["통과_소요_s"], 0)
        self.assertAlmostEqual(top["용량_인당s"], round(hx.EDGE_CAPACITY_PS, 2), places=2)
        self.assertTrue(any("통로 공유" in s for s in c["설명"]))

    def test_인원_미입력이면_지연초는_계산하지_않는다(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0}])
        c = out["혼잡"]
        if c["공유_구간"]:
            self.assertNotIn("지연_s", c["공유_구간"][0])
            self.assertTrue(any("인원 미입력" in s for s in c["설명"]))

    def test_분산_대안_제시(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0},
                                        {"id": "EX2", "x_m": 29.0, "y_m": 1.0}],
                                 origins=[{"id": "W1", "x_m": 2.0, "y_m": 10.0, "n": 40},
                                          {"id": "W2", "x_m": 10.0, "y_m": 10.0, "n": 40}])
        c = out["혼잡"]
        if c["공유_구간_수"]:
            self.assertIsNotNone(c["분산_대안"])
            self.assertNotEqual(c["분산_대안"]["대안_출구"], c["분산_대안"]["현재_출구"])
            self.assertTrue(any("분산 대안" in s for s in c["설명"]))

    def test_폐쇄_출구_처리와_요약(self):
        haz = [{"id": "F1", "kind": "fire", "x_m": 29.0, "y_m": 10.0,
                "radius_m": 5.0, "intensity": 1.0}]
        risk, _ = hx.zone_hazard_risk(
            [((z["x0"] + z["x1"]) / 2, (z["y0"] + z["y1"]) / 2) for z in self.ZONES],
            haz, weather=WEATHER)
        out = hx.evacuation_plan(self.ZONES, 3, 4, risk,
                                 exits=[{"id": "EX1", "x_m": 29.0, "y_m": 10.0},
                                        {"id": "EX2", "x_m": 1.0, "y_m": 1.0}],
                                 origins=[{"id": "W1", "x_m": 15.0, "y_m": 10.0, "n": 20}],
                                 hazards=haz, weather=WEATHER)
        self.assertEqual(out["요약"]["폐쇄_출구"], ["EX1"])
        self.assertEqual(out["routes"][0]["exit"], "EX2")
        self.assertIn("최장_대피", out["요약"])
        self.assertTrue(any("폐쇄 출구" in s for s in out["설명"]))

    def test_격자밖_좌표는_가장_가까운_구역에_붙는다(self):
        out = hx.evacuation_plan(self.ZONES, 3, 4, [0.5] * 12,
                                 exits=[{"id": "EX1", "x_m": 60.0, "y_m": 40.0}],
                                 origins=[{"id": "W1", "x_m": -5.0, "y_m": -5.0}])
        self.assertTrue(out["active"])
        self.assertEqual(out["exits"][0]["zone"], "G12")
        self.assertEqual(out["routes"][0]["origin_zone"], "G1")


class TestHazardContext(unittest.TestCase):
    def test_미적용_문구(self):
        hc = hx.hazard_context([], WEATHER)
        self.assertFalse(hc["active"])
        self.assertTrue(any("적용하지 않았습니다" in s for s in hc["설명"]))

    def test_다중유형_요약(self):
        haz = [{"id": "F1", "kind": "fire", "x_m": 1.0, "y_m": 1.0, "radius_m": 5.0, "intensity": 1.0},
               {"id": "F2", "kind": "gas_leak", "x_m": 9.0, "y_m": 9.0, "radius_m": 4.0, "intensity": 0.8}]
        hc = hx.hazard_context(haz, WEATHER)
        self.assertEqual(hc["n"], 2)
        self.assertEqual(len(hc["목록"]), 2)
        self.assertTrue(any("화재" in s and "가스 누출" in s for s in hc["설명"]))
        self.assertTrue(any("예시 설정값" in s for s in hc["설명"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
