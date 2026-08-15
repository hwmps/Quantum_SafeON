# -*- coding: utf-8 -*-
"""재해·기상·대피 경로 해설 모듈 — PM 지시 2026-07-27 (1순위)

PM 지적 사항 3건을 UI에서 해소하기 위한 계산·문장 생성 계층이다.
  (1) UI에 대피 경로 설명이 없다      → evacuation_demo()
  (2) 풍속·풍향·재해 설명이 없다       → wind_context(), hazard_context()
  (3) 센서가 재해에 끼치는 영향값 설명이 없다 → sensor_hazard_effect()

설계 원칙
---------
- 계산과 한국어 문장 생성을 이 모듈에 모으고, server.py 는 조립·전달만 한다
  (UI 표시 문구를 코드 한 곳에서 관리 → 발표 자료와 문구 불일치 방지).
- 재해 발생원이 없고 기상 데이터가 없으면 모든 보정 계수가 정확히 1.0 이다.
  즉 기존 실험 결과와 수치가 완전히 동일하다(하위 호환).
- 확산·대피 모델은 CFD·인파 시뮬레이터가 아니라 1차 근사다. 반환 dict 의
  "한계" 키에 그 사실을 항상 담아 UI·발표 자료가 같은 문구를 쓰게 한다.

의존: fire_scenario(발생원 표준형·거리 감쇠), risk_model(풍향 방향성 보정).
      두 모듈은 이 모듈을 import 하지 않으므로 순환 참조가 없다.
"""
import heapq
import math

import fire_scenario
from risk_model import (WIND_DIR_MAX_GAIN, WIND_MIN_SPEED_MS, WIND_REF_SPEED_MS,
                        downwind_weight)

KIND_KO = {"fire": "Fire", "gas_leak": "Gas Leak", "smoke": "Smoke"}

# 16방위 한글 이름 (기상청 관례: 0°=북, 시계방향)
DIR16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
         "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

# 대피 경로 계산 상수 (출처를 문장에 함께 표기한다)
FREE_SPEED_MS = 1.19        # D2-FLOW-001 자유류 보행속도
WALK_LIMIT_M = 30.0         # D1-LAW-001 법정 보행거리 상한
RISK_PENALTY = 2.0          # 위험 노출 1단위를 거리 몇 배로 볼지 (모델링 가정)
DOWNWIND_THRESHOLD = 1.02   # 이 배수 이상이면 '풍하측'으로 표시


# ── 기상 해설 ────────────────────────────────────────────────────────────────
def compass_name(deg):
    """방위각(도) → 16방위 한글 이름."""
    if deg is None:
        return None
    return DIR16[int((float(deg) % 360.0) / 22.5 + 0.5) % 16]


def wind_grade(ws):
    """풍속 etc.급 (위험 보정 규칙의 분기점과 같은 경계를 쓴다)."""
    if ws is None:
        return "No observation"
    if ws < WIND_MIN_SPEED_MS:
        return "Calm"
    if ws < 2.0:
        return "Light wind"
    if ws < 8.0:
        return "Moderate wind"
    return "Strong wind"


def wind_context(weather):
    """풍향·풍속과 그것이 위험도·센서 배치에 주는 영향을 한국어로 설명한다.

    weather: weather_kma.representative_weather() 반환형 또는 None.
    """
    if not weather or weather.get("ws_ms") is None:
        return {"있음": False, "설명": ["Weather observations are unavailable, so no directional wind adjustment was applied "
                                     "(isotropic dispersion assumption)."],
                "한계": "Results do not include weather adjustment."}

    ws = float(weather.get("ws_ms"))
    wd = weather.get("wd_deg")
    from_name = compass_name(wd)
    to_deg = None if wd is None else (float(wd) + 180.0) % 360.0
    to_name = compass_name(to_deg)
    grade = wind_grade(ws)
    max_gain_pct = WIND_DIR_MAX_GAIN * min(ws / WIND_REF_SPEED_MS, 1.0) * 100.0

    설명 = []
    if wd is not None:
        설명.append(f"Wind direction: {wd:.1f}° — wind originates from {from_name}. "
                   f"Smoke and gas are therefore modeled as dispersing toward {to_name} ({to_deg:.1f}°).")
    설명.append(f"Wind speed: {ws:.1f} m/s ({grade})"
               + (f" · observed mean {weather['평균_풍속_m_s']} m/s, maximum {weather['최대_풍속_m_s']} m/s"
                  if weather.get("평균_풍속_m_s") is not None else "")
               + ". The representative value uses the 90th percentile as a conservative design input.")
    if wd is not None and ws >= WIND_MIN_SPEED_MS:
        설명.append(f"Downwind zones toward {to_name} receive increased dispersion exposure, with risk weighted by up to "
                   f"+{max_gain_pct:.0f}% (cosine directional weighting × wind-speed factor). "
                   f"Upwind zones receive no additional directional weighting (×1.0).")
        설명.append(f"Placement implication: at equal distance, sensors covering zones toward {to_name} "
                   f"contribute more to risk-weighted coverage. Evacuation routing also penalizes travel through this direction.")
    else:
        설명.append(f"Wind speed is below {WIND_MIN_SPEED_MS} m/s, so directional adjustment is disabled "
                   f"(isotropic dispersion).")
    if ws < 2.0:
        설명.append("Low-wind condition: enclosed zones handling gas receive a retention adjustment because gas may accumulate, "
                   "increasing risk by ×1.10.")
    elif ws >= 8.0:
        설명.append("Strong-wind condition: open zones containing ignition or combustible sources receive a ×1.10 risk adjustment for potential ember spread.")

    out = {"있음": True, "wd_deg": wd, "ws_ms": ws, "풍향_방위": from_name,
           "이동_방위": to_name, "이동_방위_deg": to_deg, "등급": grade,
           "최대_풍하측_가중_pct": round(max_gain_pct, 1),
           "설명": 설명,
           "한계": ("This is a first-order approximation using directional cosine and wind speed. Wall shielding, ceiling height, local turbulence, and HVAC effects are "
                  "not modeled; this is not a CFD simulation.")}
    for k in ("출처", "기간", "stn", "n", "평균_풍속_m_s", "최대_풍속_m_s"):
        if k in weather:
            out[k] = weather[k]
    return out


# ── 재해(발생원) 해설 ────────────────────────────────────────────────────────
def hazard_context(hazards, weather=None):
    """발생원 목록을 UI 표시용 한국어 설명으로 바꾼다 (다중 발생원·다중 유형 지원)."""
    if not hazards:
        return {"active": False, "n": 0, "목록": [],
                "설명": ["No hazard scenario is active — all zones use the uniform risk baseline (0.5)."],
                "한계": "Baseline case without hazard adjustment."}

    wc = wind_context(weather)
    kinds = []
    목록 = []
    for h in hazards:
        ko = KIND_KO.get(h.get("kind"), h.get("kind"))
        kinds.append(ko)
        kg = fire_scenario.KIND_GAIN.get(h.get("kind"), 1.0)
        inten = float(h.get("intensity", 1.0))
        peak = fire_scenario.MAX_GAIN * inten * kg * 100.0
        목록.append({
            "id": h.get("id"), "kind": h.get("kind"), "유형": ko,
            "x_m": h.get("x_m"), "y_m": h.get("y_m"),
            "radius_m": h.get("radius_m"), "intensity": inten,
            "origin": h.get("origin", "manual"),
            "설명": (f"{h.get('id')} {ko} — location ({h.get('x_m')}, {h.get('y_m')}) m, "
                    f"impact radius {h.get('radius_m')} m, intensity {inten}. "
                    f"zones within the impact radius receive up to +{peak:.0f}% additional risk weighting; outside the radius, the effect decays as (R/distance)²"
                    f"(hazard-type coefficient: {ko} ×{kg}).")})

    설명 = [f"Hazard sources active: {len(hazards)} — " + ", ".join(sorted(set(kinds))) + "."]
    설명.append("When multiple hazard sources overlap, their weights are not summed; the maximum contribution from the dominant source is used — "
               "this avoids overestimating risk in overlapping regions.")
    if wc.get("있음") and wc.get("이동_방위"):
        설명.append(f"Downwind zones toward {wc['이동_방위']} receive up to an additional "
                   f"+{wc['최대_풍하측_가중_pct']:.0f}% risk weighting.")
    설명.append("Current hazard inputs are manually configured demo values and are not live physical sensor measurements "
               "(the same interface could later accept live sensor feeds).")
    return {"active": True, "n": len(hazards), "목록": 목록, "설명": 설명,
            "한계": ("Hazard propagation uses a first-order distance-decay approximation. Gas properties, ventilation rates, and wall shielding are "
                   "not modeled, and radius/intensity values are demo assumptions.")}


def zone_hazard_risk(zone_centers, hazards, weather=None, base=0.5):
    """구역 중심 좌표 목록 → (위험도 리스트, 구역별 상세).

    발생원이 없으면 모든 값이 base 로 기존 데모와 동일하다.
    """
    if not hazards:
        return [base] * len(zone_centers), []
    dw = (lambda s, t: downwind_weight(s, t, weather)) if weather else None
    risk, detail = [], []
    for c in zone_centers:
        m = fire_scenario.hazard_multiplier(c, hazards, dir_weight=dw)
        m_iso = fire_scenario.hazard_multiplier(c, hazards)
        risk.append(base * m)
        # 풍하측 판정은 '추가 가중분(m-1)'끼리 비교한다. 배수 전체로 비교하면 기준 1.0에
        # 희석돼 약하게 영향받는 구역이 전부 풍상측으로 잘못 표시된다.
        detail.append({"배수": round(m, 3), "등방_배수": round(m_iso, 3),
                       "풍하측": bool(m_iso > 1.0
                                   and (m - 1.0) > (m_iso - 1.0) * DOWNWIND_THRESHOLD)})
    return risk, detail


# ── 센서 ↔ 재해 영향값 해설 ──────────────────────────────────────────────────
def sensor_hazard_effect(sensors, hazards, weather=None):
    """센서별로 '재해에 어떤 영향값을 끼치는가'를 계산·설명한다.

    반환: {sensor_id: {거리_m, 담당_재해, 반경내, 풍하측, 감지_기여_pct, 설명}}
    감지_기여_pct: 그 센서 커버 원 안에서 발생원 반경이 겹치는 정도를 면적 근사로 계산한
    '초기 감지 가능성' 지표(0~100). 원-원 교차 면적 / 발생원 반경 면적.
    """
    out = {}
    wc = wind_context(weather)
    to_name = wc.get("이동_방위")
    for s in sensors:
        sid = s.get("id")
        sx, sy, sr = float(s["x_m"]), float(s["y_m"]), float(s["radius_m"])
        if not hazards:
            out[sid] = {"재해_적용": False,
                        "설명": "No hazard scenario is active — hazard-detection contribution is not evaluated for this sensor."}
            continue
        best = None
        for h in hazards:
            hx, hy, hr = float(h["x_m"]), float(h["y_m"]), float(h["radius_m"])
            d = math.hypot(sx - hx, sy - hy)
            overlap = _circle_overlap_ratio(sx, sy, sr, hx, hy, hr)
            dwv = downwind_weight((hx, hy), (sx, sy), weather) if weather else 1.0
            cand = {"h": h, "d": d, "overlap": overlap, "dw": dwv, "hr": hr}
            # 담당 발생원: 감지 기여가 큰 쪽, 같으면 가까운 쪽
            if best is None or (overlap, -d) > (best["overlap"], -best["d"]):
                best = cand
        h = best["h"]
        ko = KIND_KO.get(h.get("kind"), h.get("kind"))
        inside = best["d"] <= best["hr"]
        downwind = best["dw"] > DOWNWIND_THRESHOLD
        pct = best["overlap"] * 100.0
        # 확산이 센서 커버 경계에 닿기까지의 여유 거리 (반경 밖일 때만 의미)
        gap = max(0.0, best["d"] - best["hr"] - sr)

        parts = [f"{h.get('id')} {ko} is {best['d']:.1f} m away"]
        if pct >= 1.0:
            parts.append(f"Covers {pct:.0f}% of the hazard impact area — contributes to early detection")
        else:
            parts.append("Does not overlap the hazard impact area — no direct early-detection contribution")
        if inside:
            parts.append("The sensor lies within the hazard impact radius and may itself be exposed; resilience or redundancy should be considered")
        elif gap > 0:
            parts.append(f"An additional {gap:.1f} m of propagation would reach this sensor's coverage boundary")
        if downwind and to_name:
            parts.append(f"Located downwind toward {to_name}, giving this sensor higher priority along the modeled dispersion path")
        elif weather and wc.get("있음") and to_name:
            parts.append("Located upwind, so it has lower priority along the modeled dispersion path")

        out[sid] = {"재해_적용": True, "담당_재해": h.get("id"), "담당_재해_유형": ko,
                    "거리_m": round(best["d"], 2), "반경내": bool(inside),
                    "풍하측": bool(downwind), "풍하측_배수": round(best["dw"], 3),
                    "감지_기여_pct": round(pct, 1), "여유_거리_m": round(gap, 2),
                    "설명": " · ".join(parts)}
    return out


def _circle_overlap_ratio(x1, y1, r1, x2, y2, r2):
    """원1(센서 커버)과 원2(발생원 영향권)의 교차 면적 / 원2 면적 ∈ [0,1]."""
    if r1 <= 0 or r2 <= 0:
        return 0.0
    d = math.hypot(x1 - x2, y1 - y2)
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return 1.0 if r1 >= r2 else (r1 * r1) / (r2 * r2)
    a1 = r1 * r1 * math.acos(min(1.0, max(-1.0, (d * d + r1 * r1 - r2 * r2) / (2 * d * r1))))
    a2 = r2 * r2 * math.acos(min(1.0, max(-1.0, (d * d + r2 * r2 - r1 * r1) / (2 * d * r2))))
    a3 = 0.5 * math.sqrt(max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return (a1 + a2 - a3) / (math.pi * r2 * r2)


# ── 대피 계획: 출구 입력 + 위치별 최적 경로 + 통로 공유(혼잡) ────────────────
# PM 지시 2026-07-27: 출구를 입력값으로 받고, "어떤 위치에서 출구까지 어떤 방식이
# 효과적인지"를 서술한다. 출발점은 작업자 위치를 지정하면 그 지점, 없으면 전 구역.
def _neighbors(idx, rows, cols):
    r, c = divmod(idx, cols)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < rows and 0 <= cc < cols:
            yield rr * cols + cc


def _centers(zones):
    return [((z["x0"] + z["x1"]) / 2.0, (z["y0"] + z["y1"]) / 2.0) for z in zones]


def _point_zone(zones, x, y):
    """좌표가 속한 구역 index. 격자 밖이면 가장 가까운 구역으로 붙인다."""
    for i, z in enumerate(zones):
        if z["x0"] - 1e-9 <= x <= z["x1"] + 1e-9 and z["y0"] - 1e-9 <= y <= z["y1"] + 1e-9:
            return i
    cs = _centers(zones)
    return min(range(len(zones)), key=lambda i: math.hypot(cs[i][0] - x, cs[i][1] - y))


def _norm_exits(zones, rows, cols, exits_in):
    """사용자 입력 출구 → 표준형. 입력이 없으면 격자 네 모서리로 가정한다(가정 표기)."""
    cs = _centers(zones)
    if exits_in:
        out = []
        for k, e in enumerate(exits_in):
            x, y = float(e["x_m"]), float(e["y_m"])
            zi = _point_zone(zones, x, y)
            out.append({"id": e.get("id") or f"EX{k + 1}", "x_m": round(x, 2), "y_m": round(y, 2),
                        "zone": zones[zi]["id"], "zone_idx": zi, "입력": True,
                        "name": e.get("name")})
        return out, True
    corners = sorted({0, cols - 1, (rows - 1) * cols, rows * cols - 1})
    return ([{"id": f"EX{k + 1}", "x_m": round(cs[c][0], 2), "y_m": round(cs[c][1], 2),
              "zone": zones[c]["id"], "zone_idx": c, "입력": False, "name": None}
             for k, c in enumerate(corners)], False)


def _norm_origins(zones, origins_in, exit_zone_idx):
    """작업자 위치 입력 → 표준형. 없으면 출구 구역을 뺀 전 구역을 출발점으로 본다."""
    cs = _centers(zones)
    if origins_in:
        out = []
        for k, o in enumerate(origins_in):
            x, y = float(o["x_m"]), float(o["y_m"])
            zi = _point_zone(zones, x, y)
            npeople = o.get("n")
            out.append({"id": o.get("id") or f"W{k + 1}", "x_m": round(x, 2), "y_m": round(y, 2),
                        "zone": zones[zi]["id"], "zone_idx": zi,
                        "n": (float(npeople) if npeople else None), "입력": True})
        return out, True
    idx = [i for i in range(len(zones)) if i not in exit_zone_idx] or list(range(len(zones)))
    return ([{"id": zones[i]["id"], "x_m": round(cs[i][0], 2), "y_m": round(cs[i][1], 2),
              "zone": zones[i]["id"], "zone_idx": i, "n": None, "입력": False} for i in idx], False)


def evacuation_plan(zones, rows, cols, risk, exits=None, origins=None,
                    hazards=None, weather=None):
    """출구 입력값을 받아 출발 위치별 최적 대피 경로와 그 근거를 계산한다.

    exits   : [{id?, x_m, y_m, name?}] — 사용자가 지정한 출구. 없으면 격자 모서리 가정.
    origins : [{id?, x_m, y_m, n?}]    — 작업자 위치(인원). 없으면 전 구역을 출발점으로.
    risk    : 구역별 위험도(재해·풍향 보정 후).

    경로 선택 비용 = Σ 구간거리 × (1 + RISK_PENALTY × 도착구역 위험도).
    즉 '가까운 출구'가 아니라 '위험을 덜 지나며 빠른 출구'를 고른다. 비교용으로
    거리만 최소화한 경로도 함께 구해 두 방식의 차이를 서술한다.

    혼잡: 서로 다른 출발점의 경로가 같은 구간을 공유하면 통로 용량으로 통과시간을
    계산해 지연을 표시하고, 한 그룹을 다른 출구로 돌리는 분산 대안을 제시한다.
    (정식 최적화는 파트 2-B 대피 QUBO의 혼잡 이차항이 담당 — 여기서는 근거 서술용)
    """
    n = len(zones)
    if n == 0 or rows * cols != n:
        return {"active": False, "설명": ["Evacuation routes could not be computed because the zone grid is unavailable."]}
    cs = _centers(zones)
    ex, ex_input = _norm_exits(zones, rows, cols, exits)

    # 발생원 impact radius 안 출구는 폐쇄로 본다 (법정 2개소 이상 확보 취지)
    for e in ex:
        e["usable"], e["blocked_by"], e["blocked_dist_m"] = True, None, None
        for h in hazards or []:
            d = math.hypot(e["x_m"] - float(h["x_m"]), e["y_m"] - float(h["y_m"]))
            if d <= float(h["radius_m"]):
                e.update({"usable": False, "blocked_by": h.get("id"),
                          "blocked_dist_m": round(d, 1)})
                break
    usable = [e for e in ex if e["usable"]]
    all_blocked = not usable
    if all_blocked:            # 전부 폐쇄면 계산은 계속하되 경고를 남긴다
        usable = list(ex)
    ori, ori_input = _norm_origins(zones, origins, {e["zone_idx"] for e in usable})

    def dijkstra(start, weighted):
        dist, prev = {start: 0.0}, {}
        pq = [(0.0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, math.inf) + 1e-12:
                continue
            for v in _neighbors(u, rows, cols):
                step = math.hypot(cs[v][0] - cs[u][0], cs[v][1] - cs[u][1])
                w = step * (1.0 + RISK_PENALTY * risk[v]) if weighted else step
                if d + w < dist.get(v, math.inf) - 1e-12:
                    dist[v], prev[v] = d + w, u
                    heapq.heappush(pq, (d + w, v))
        return dist, prev

    def zone_path(prev, start, goal):
        p = [goal]
        while p[-1] != start:
            if p[-1] not in prev:
                return None
            p.append(prev[p[-1]])
        return list(reversed(p))

    def polyline(o, zpath, e):
        pts = [(o["x_m"], o["y_m"])] + [cs[i] for i in zpath] + [(e["x_m"], e["y_m"])]
        ded = [pts[0]]
        for p in pts[1:]:
            if math.hypot(p[0] - ded[-1][0], p[1] - ded[-1][1]) > 1e-6:
                ded.append(p)
        return ded

    def metrics(pts, zpath):
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        # 위험 노출 = Σ 구간거리 × 그 구간이 지나는 구역 위험도 (상대 지표)
        expo, zs = 0.0, [zpath[0]] + zpath
        for k, (a, b) in enumerate(zip(pts, pts[1:])):
            zi = zpath[min(k, len(zpath) - 1)]
            expo += math.hypot(b[0] - a[0], b[1] - a[1]) * risk[zi]
        peak = max(risk[i] for i in zpath)
        return {"거리_m": round(length, 1), "예상_소요_s": round(length / FREE_SPEED_MS, 1),
                "위험노출": round(expo, 2), "최대_통과_위험도": round(peak, 3),
                "법정_보행거리_초과": bool(length > WALK_LIMIT_M),
                "초과_m": round(max(0.0, length - WALK_LIMIT_M), 1)}

    # ── 출발점별 전체 출구 후보 평가 ──────────────────────────────────────────
    routes = []
    for o in ori:
        dw, pw = dijkstra(o["zone_idx"], True)
        dd, pd = dijkstra(o["zone_idx"], False)
        leg_in = math.hypot(o["x_m"] - cs[o["zone_idx"]][0], o["y_m"] - cs[o["zone_idx"]][1])
        cands = []
        for e in usable:
            zi = e["zone_idx"]
            if zi not in dw:
                continue
            leg_out = math.hypot(e["x_m"] - cs[zi][0], e["y_m"] - cs[zi][1])
            cost = (dw[zi] + leg_in * (1 + RISK_PENALTY * risk[o["zone_idx"]])
                    + leg_out * (1 + RISK_PENALTY * risk[zi]))
            zp = zone_path(pw, o["zone_idx"], zi)
            if zp is None:
                continue
            pts = polyline(o, zp, e)
            cands.append({"exit": e["id"], "cost": round(cost, 2), "zone_path": zp,
                          "polyline": pts, "지표": metrics(pts, zp)})
        if not cands:
            continue
        cands.sort(key=lambda c: c["cost"])
        best = cands[0]
        # 거리만 최소화했을 때의 대안 (방식 비교용)
        short = None
        cand_d = [(dd.get(e["zone_idx"], math.inf), e) for e in usable]
        cand_d = [(d, e) for d, e in cand_d if d < math.inf]
        if cand_d:
            _, e_d = min(cand_d, key=lambda t: t[0])
            zp_d = zone_path(pd, o["zone_idx"], e_d["zone_idx"])
            if zp_d:
                pts_d = polyline(o, zp_d, e_d)
                short = {"exit": e_d["id"], "zone_path": zp_d, "지표": metrics(pts_d, zp_d)}
        routes.append({"origin": o["id"], "origin_zone": o["zone"], "n": o["n"],
                       "x_m": o["x_m"], "y_m": o["y_m"],
                       "exit": best["exit"], "zone_path": best["zone_path"],
                       "path_zone_ids": [zones[i]["id"] for i in best["zone_path"]],
                       "polyline": [{"x_m": round(p[0], 2), "y_m": round(p[1], 2)}
                                    for p in best["polyline"]],
                       "지표": best["지표"], "cost": best["cost"],
                       "출구_후보": [{"exit": c["exit"], "cost": c["cost"],
                                  "거리_m": c["지표"]["거리_m"]} for c in cands],
                       "최단거리_대안": short})

    if not routes:
        return {"active": False, "exits": ex,
                "설명": ["No reachable route to an exit was found — check the exit locations and zone-grid configuration."]}

    cong = _congestion(routes, zones, cs, risk, usable, ori_input)
    for r in routes:
        r["설명"] = _route_sentences(r, zones, risk, hazards, weather, cong)

    wc = wind_context(weather)
    설명 = []
    설명.append((f"{len(ex)} user-defined exits" if ex_input
                else f"No exits provided; {len(ex)} grid-corner exits are assumed")
               + f" · {len(routes)} evacuation origins"
               + (" (worker-defined)" if ori_input else " (all zones automatically evaluated)") + ".")
    if not ex_input:
        설명.append("Exit locations are assumed in this run. Provide actual floor-plan exits to recompute routes using those coordinates.")
    blocked = [e for e in ex if not e["usable"]]
    if blocked:
        설명.append("Unavailable exits: " + ", ".join(
            f"{e['id']}({e['blocked_by']} within the hazard impact radius, {e['blocked_dist_m']} m)" for e in blocked)
            + (" — all exits are affected, so they remain in the candidate set for warning-mode analysis."
               if all_blocked else " — removed from the candidate set."))
    설명.append("Route-selection objective: rather than minimizing distance alone, "
               f"the selected route minimizes Σ[segment distance × (1 + {RISK_PENALTY:.0f} × zone risk)]. "
               "For routes of similar length, paths through lower-risk zones are preferred.")
    diff = [r for r in routes if r["최단거리_대안"] and r["최단거리_대안"]["exit"] != r["exit"]]
    if diff:
        설명.append(f"{len(diff)} origins select a different exit when risk is included instead of distance alone: "
                   + ", ".join(f"{r['origin']}({r['최단거리_대안']['exit']}→{r['exit']})"
                               for r in diff[:6])
                   + (" etc." if len(diff) > 6 else "")
                   + " — these routes accept additional travel distance to reduce modeled risk exposure.")
    else:
        설명.append("For every origin, the minimum-distance exit and risk-aware exit are identical — "
                   "under the current hazard and weather conditions, distance and modeled risk do not conflict.")
    over = [r for r in routes if r["지표"]["법정_보행거리_초과"]]
    if over:
        설명.append(f"Origins exceeding the configured {WALK_LIMIT_M:.0f} m walking-distance threshold: "
                   f"{len(over)} ("
                   + ", ".join(f"{r['origin']} +{r['지표']['초과_m']} m" for r in over[:6])
                   + (" etc." if len(over) > 6 else "")
                   + ") — consider additional exits or intermediate refuge locations.")
    else:
        설명.append(f"All origins are within the configured {WALK_LIMIT_M:.0f} m walking-distance threshold.")
    if wc.get("있음") and wc.get("이동_방위") and hazards:
        설명.append(f"Because smoke and gas are modeled as dispersing toward {wc['이동_방위']}, zones in that direction receive higher risk weights, "
                   f"so the routing objective tends to avoid them.")
    설명 += cong["설명"]

    worst = max(routes, key=lambda r: r["지표"]["예상_소요_s"])
    총거리 = round(sum(r["지표"]["거리_m"] for r in routes), 1)
    return {"active": True, "출구_입력": ex_input, "출발_입력": ori_input,
            "exits": ex, "routes": routes, "혼잡": cong,
            "요약": {"출발_수": len(routes), "출구_수": len(ex),
                   "폐쇄_출구": [e["id"] for e in blocked],
                   "최장_대피": {"origin": worst["origin"], "exit": worst["exit"],
                              "예상_소요_s": worst["지표"]["예상_소요_s"],
                              "거리_m": worst["지표"]["거리_m"]},
                   "총_이동거리_m": 총거리,
                   "법정초과_출발수": len(over)},
            "설명": 설명,
            "한계": ("The model assumes four-neighbor grid connectivity and straight-line movement between zone centers. Walls, doors, stairs, and time-dependent crowd dynamics "
                   "(including queue formation and counterflow) are not modeled. This is not a crowd simulation; congestion uses "
                   "a first-order corridor-capacity approximation. The separate evacuation QUBO handles assignment optimization "
                   "(4 worker groups × 3 candidate routes with a quadratic congestion term).")}


# 통로 용량 상수 (D2-FLOW: 유효폭 = 통로폭 − 경계층 2×0.15 m, 단위폭 유동률 1.3 인/(m·s))
CORRIDOR_WIDTH_M = 1.2
BOUNDARY_LAYER_M = 0.15
SPECIFIC_FLOW = 1.3
EDGE_CAPACITY_PS = (CORRIDOR_WIDTH_M - 2 * BOUNDARY_LAYER_M) * SPECIFIC_FLOW  # ≈1.17 인/s


def _congestion(routes, zones, cs, risk, usable, has_people):
    """서로 다른 출발점이 공유하는 구간을 찾아 통과시간·지연과 분산 대안을 계산한다."""
    use = {}
    for r in routes:
        zp = r["zone_path"]
        for a, b in zip(zp, zp[1:]):
            key = (min(a, b), max(a, b))
            use.setdefault(key, []).append(r)
    shared = []
    for (a, b), rs in use.items():
        if len(rs) < 2:
            continue
        people = sum(r["n"] for r in rs if r["n"]) if has_people else None
        step = math.hypot(cs[b][0] - cs[a][0], cs[b][1] - cs[a][1])
        item = {"구간": f"{zones[a]['id']}→{zones[b]['id']}", "사용_출발점": [r["origin"] for r in rs],
                "출발점_수": len(rs), "구간거리_m": round(step, 1),
                "자유통과_s": round(step / FREE_SPEED_MS, 1)}
        if people:
            item.update({"인원": people, "용량_인당s": round(EDGE_CAPACITY_PS, 2),
                         "통과_소요_s": round(people / EDGE_CAPACITY_PS, 1),
                         "지연_s": round(max(0.0, people / EDGE_CAPACITY_PS
                                           - step / FREE_SPEED_MS), 1)})
        shared.append(item)
    shared.sort(key=lambda s: (-(s.get("지연_s") or 0), -s["출발점_수"]))

    설명 = []
    대안 = None
    if not shared:
        설명.append("No shared corridor segments were detected, so no modeled congestion occurs — "
                   "each evacuation origin uses a separate path.")
    else:
        top = shared[0]
        설명.append(f"There are {len(shared)} shared corridor segments. The most congested segment is "
                   f"{top['구간']}, used by {top['출발점_수']} evacuation origins"
                   + (f" with {top['인원']} people. With an effective corridor width of "
                      f"{CORRIDOR_WIDTH_M - 2 * BOUNDARY_LAYER_M:.1f} m, the modeled corridor capacity is "
                      f"{EDGE_CAPACITY_PS:.2f} persons/s, giving a traversal time of {top['통과_소요_s']} s, "
                      f"which is {top['지연_s']} s slower than free-flow travel ({top['자유통과_s']} s)."
                      if top.get("인원") else
                      " use this segment. Occupancy was not provided, so congestion delay is not estimated."))
        # 분산 대안: 공유 구간을 쓰는 출발점 중 하나를 다른 출구로 돌릴 때 비용 증가가 가장 작은 안
        best = None
        for r in routes:
            if r["origin"] not in top["사용_출발점"] or len(r["출구_후보"]) < 2:
                continue
            alt = r["출구_후보"][1]
            add = alt["cost"] - r["cost"]
            if best is None or add < best["추가비용"]:
                best = {"origin": r["origin"], "현재_출구": r["exit"], "대안_출구": alt["exit"],
                        "추가비용": round(add, 2),
                        "거리_증가_m": round(alt["거리_m"] - r["지표"]["거리_m"], 1)}
        if best:
            대안 = best
            설명.append(f"Load-balancing alternative: reroute {best['origin']} from {best['현재_출구']} to "
                       f"{best['대안_출구']}. Travel distance changes by "
                       f"{best['거리_증가_m']:+.1f} m, while reducing simultaneous use of the shared corridor. "
                       f"This tradeoff between locally optimal routes and system-level coordination is captured by the evacuation QUBO's "
                       f"quadratic congestion term.")
        else:
            설명.append("No alternative exit is available to avoid the shared corridor — "
                       "adding another evacuation exit would be the primary mitigation.")
    return {"공유_구간": shared[:8], "공유_구간_수": len(shared), "분산_대안": 대안,
            "용량_가정": {"통로폭_m": CORRIDOR_WIDTH_M, "경계층_m": BOUNDARY_LAYER_M,
                      "단위폭_유동률_인_m_s": SPECIFIC_FLOW,
                      "유효_용량_인_s": round(EDGE_CAPACITY_PS, 2),
                      "출처": "D2-FLOW assumption (walking speed 1.19 m/s, specific flow 1.3 persons/(m·s))"},
            "설명": 설명}


def _route_sentences(r, zones, risk, hazards, weather, cong):
    """출발 위치 1곳의 '어디서 어떤 방식으로 나가는가'를 한국어로 서술한다."""
    m = r["지표"]
    ids = r["path_zone_ids"]
    via = " → ".join(ids[1:-1]) if len(ids) > 2 else None
    s = []
    s.append(f"{r['origin']}"
             + (f" ({r['n']:.0f} people)" if r["n"] else "")
             + f" — origin ({r['x_m']}, {r['y_m']}) m, zone {r['origin_zone']}"
             + f" (risk {risk[r['zone_path'][0]]:.2f}) → "
             + (f"via {via} → " if via else "direct → ")
             + f"exit {r['exit']}.")
    s.append(f"Travel distance {m['거리_m']} m · estimated time {m['예상_소요_s']} s (walking speed {FREE_SPEED_MS} m/s) · "
             f"risk exposure {m['위험노출']} · maximum traversed-zone risk {m['최대_통과_위험도']}"
             + (f" · exceeds the configured {WALK_LIMIT_M:.0f} m walking-distance threshold by {m['초과_m']} m"
                if m["법정_보행거리_초과"] else f" · within the configured {WALK_LIMIT_M:.0f} m walking-distance threshold") + ".")
    if len(r["출구_후보"]) > 1:
        others = ", ".join(f"{c['exit']} {c['cost']}" for c in r["출구_후보"][1:4])
        s.append(f"Exit selection rationale: {r['exit']} objective cost {r['cost']} < {others} — "
                 f"it has the lowest combined distance-and-risk objective.")
    alt = r["최단거리_대안"]
    if alt and alt["exit"] != r["exit"]:
        s.append(f"By distance alone, {alt['exit']} is {alt['지표']['거리_m']} m away and "
                 f"{abs(alt['지표']['거리_m'] - m['거리_m']):.1f} m shorter, but its modeled risk exposure is "
                 f"{alt['지표']['위험노출']} versus {m['위험노출']} for the selected route, so it was not chosen. "
                 f"The model therefore prefers a lower-risk exit over the closest exit.")
    elif alt and alt["지표"]["거리_m"] < m["거리_m"] - 0.05:
        s.append(f"For the same exit, the selected path detours from the shortest route ({alt['지표']['거리_m']} m) by "
                 f"{m['거리_m'] - alt['지표']['거리_m']:+.1f} m to reduce travel through higher-risk zones.")
    else:
        s.append("For this origin, the shortest route is also the lowest-risk route.")
    if hazards:
        near = min((math.hypot(p["x_m"] - float(h["x_m"]), p["y_m"] - float(h["y_m"])), h.get("id"))
                   for p in r["polyline"] for h in hazards)
        s.append(f"The route passes within {near[0]:.1f} m of hazard source {near[1]}.")
    wc = wind_context(weather)
    if wc.get("있음") and wc.get("이동_방위") and hazards:
        s.append(f"Modeled smoke dispersion is toward {wc['이동_방위']} — downwind zones receive higher risk weights, "
                 f"so the routing objective tends to avoid them.")
    mine = [c for c in cong["공유_구간"] if r["origin"] in c["사용_출발점"]]
    if mine:
        c = mine[0]
        s.append(f"Congestion warning: segment {c['구간']} is shared with {c['출발점_수'] - 1} other evacuation origins"
                 + (f" ({c['인원']} people total, traversal {c['통과_소요_s']} s)" if c.get("인원") else "")
                 + " — simultaneous evacuation may create congestion on this segment.")
    return s


def evacuation_demo(zones, rows, cols, risk, hazards=None, weather=None,
                    exits=None, origin=None):
    """구버전 단일 경로 API (하위 호환). 내부적으로 evacuation_plan 을 쓴다.

    origin: 출발 구역 index. None이면 위험도가 가장 높은 구역을 쓴다.
    """
    n = len(zones)
    if n == 0 or rows * cols != n:
        return {"active": False, "설명": ["Evacuation routes could not be computed because the zone grid is unavailable."]}
    cs = _centers(zones)
    ex_in = None
    if exits:
        ex_in = [{"id": f"EX{k + 1}", "x_m": cs[i][0], "y_m": cs[i][1]}
                 for k, i in enumerate(exits)] if isinstance(exits[0], int) else exits
    if origin is None:
        ex_tmp, _ = _norm_exits(zones, rows, cols, ex_in)
        skip = {e["zone_idx"] for e in ex_tmp}
        cands = [i for i in range(n) if i not in skip] or list(range(n))
        origin = max(cands, key=lambda i: risk[i])
    plan = evacuation_plan(zones, rows, cols, risk,
                           exits=ex_in,
                           origins=[{"id": zones[origin]["id"],
                                     "x_m": cs[origin][0], "y_m": cs[origin][1]}],
                           hazards=hazards, weather=weather)
    if not plan.get("active"):
        return plan
    r = plan["routes"][0]
    out = dict(plan)
    out.update({"origin": r["origin"], "exit": r["exit"],
                "path_zone_ids": r["path_zone_ids"], "path_indices": r["zone_path"],
                "polyline": r["polyline"], "지표": r["지표"],
                "exits_zone_ids": [e["zone"] for e in plan["exits"]],
                "최단거리_대안": ({"path_zone_ids": [zones[i]["id"] for i in
                                              r["최단거리_대안"]["zone_path"]],
                             "지표": r["최단거리_대안"]["지표"]}
                            if r["최단거리_대안"] else None),
                "설명": r["설명"] + plan["설명"]})
    for e in out["exits"]:
        e.setdefault("cost", None)
    return out


