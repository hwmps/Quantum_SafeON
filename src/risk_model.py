# -*- coding: utf-8 -*-
"""규칙 기반 구역 위험 점수 모듈 (ML 단계의 초기 버전)

Codex 지침 준수: P3 사고 사례표(10행)는 소표본이므로 확률 학습이 아니라
'규칙 기반 초기 위험 점수 + feature 설계 근거'로만 사용한다.

방법:
1) 사고 사례표의 feature 6종(화기, 가연성가스, 독성가스, 가연물, 밀폐, 정비) 각각에 대해
   해당 feature가 1인 사례들의 심각도(사망 2점 + 부상 1점, 미상은 1점) 합을 가중치로 사용.
2) 구역 유형 → feature 노출도 매핑(모델링 가정, 아래 ZONE_FEATURES)을 내적하여 원점수 산출.
3) 주 통로·피난 동선은 법적/피난 중요도 보정 +20% (KOSHA 피난 동선 확보 취지, 가정임을 명시).
4) [0.1, 1.0]로 정규화 → QUBO 커버리지 항의 구역 가중치 r_z.
"""
FEATURES = ["hot_work", "flammable_gas", "toxic_gas", "combustible", "confinement", "maintenance"]

# 구역 유형별 feature 노출도 (0~1, 모델링 가정 — 발표 자료에 근거와 함께 명시)
ZONE_FEATURES = {
    "cleanroom_construction":  {"combustible": 1.0, "flammable_gas": 0.5, "hot_work": 0.5},
    "subfab_utility":          {"maintenance": 1.0, "flammable_gas": 0.5, "confinement": 1.0},
    "special_gas_distribution": {"flammable_gas": 1.0, "toxic_gas": 1.0, "maintenance": 1.0},
    "bulk_gas_chemical_storage": {"flammable_gas": 1.0, "toxic_gas": 0.5, "combustible": 0.5},
    "hot_work":                {"hot_work": 1.0, "combustible": 0.5},
    "material_staging":        {"combustible": 1.0, "hot_work": 0.5, "confinement": 0.5},
    "electrical_room":         {"hot_work": 0.5, "combustible": 0.5, "confinement": 1.0},  # 전기 점화원≈화기 대용
    "fan_deck_hvac":           {"flammable_gas": 0.5, "confinement": 0.5},
    "waste_treatment":         {"toxic_gas": 1.0, "maintenance": 0.5},
    "main_corridor":           {"combustible": 0.5, "confinement": 0.5},
    "loading_entrance":        {"flammable_gas": 0.5, "combustible": 0.5},
}
CORRIDOR_BONUS = 1.2  # 피난 동선 보정 (가정)

# 법적 hard 제약 대상 구역 유형 (L01 제232조: 인화성 가스, L02 제299조: 급성 독성물질)
HARD_COVER_ZONE_TYPES = {"special_gas_distribution", "bulk_gas_chemical_storage", "waste_treatment"}


def _severity(row):
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    d, i = _num(row.get("사망자")), _num(row.get("부상자"))
    if d is None and i is None:
        return 1.0  # 세부 미상 사례
    return 2.0 * (d or 0.0) + 1.0 * (i or 0.0)


def feature_weights(incidents):
    """feature별 가중치 = 해당 feature=1 사례의 심각도 합 (합계 1로 정규화)."""
    w = {f: 0.0 for f in FEATURES}
    for row in incidents:
        sev = _severity(row)
        for f in FEATURES:
            v = row.get("feature_" + f, "")
            try:
                if v != "" and float(v) > 0:
                    w[f] += sev * float(v)
            except ValueError:
                pass
    total = sum(w.values()) or 1.0
    return {f: w[f] / total for f in FEATURES}


def wind_multiplier(feats, weather):
    """기상청 풍속 기반 위험 보정 (모델링 가정 — 발표 자료에 명시).

    - 정온(ws < 2 m/s): 밀폐도 있고 가스 위험이 있는 구역 ×1.10 (가스 체류·축적 위험↑)
    - 강풍(ws >= 8 m/s): 개방(밀폐 0)·화기/가연물 구역 ×1.10 (불티 비산·연소 확산 위험↑)
    - 그 외 또는 기상 데이터 없음: 1.0
    """
    if not weather:
        return 1.0
    ws = weather.get("ws_ms", 0.0)
    gas = feats.get("flammable_gas", 0) + feats.get("toxic_gas", 0)
    conf = feats.get("confinement", 0)
    fire = feats.get("hot_work", 0) + feats.get("combustible", 0)
    if ws < 2.0 and conf >= 0.5 and gas > 0:
        return 1.10
    if ws >= 8.0 and conf == 0 and fire >= 0.5:
        return 1.10
    return 1.0


# ── 풍향 방향성 보정 (P1-4, 2026-07-27 추가) ─────────────────────────────────
# 모델링 가정: 누출·발화 가정 지점에서 풍하측(downwind)에 있는 구역일수록 확산 노출이 크다.
# CFD가 아니라 방향 코사인 × 풍속 계수의 1차 근사이며, 벽 차폐·천장고·공조는 미반영.
WIND_DIR_MAX_GAIN = 0.35   # 정면 풍하측 구역의 최대 가중 (+35%)
WIND_REF_SPEED_MS = 10.0   # 가중이 최대가 되는 기준 풍속 (이상은 절단)
WIND_MIN_SPEED_MS = 0.5    # 이 미만은 무풍으로 간주 → 보정 1.0 (기존 결과 하위 호환)


def downwind_weight(src_xy, tgt_xy, weather):
    """풍하측 방향 가중 ∈ [1.0, 1+WIND_DIR_MAX_GAIN].

    기상청 관례상 wd_deg는 '바람이 불어오는 방향'이므로 연기·가스 이동 방향은 wd_deg+180°.
    방위각 0°=북(+y), 90°=동(+x) 기준으로 이동 단위벡터를 만들고, 누출점→대상점 벡터와의
    코사인 유사도(양수만)에 풍속 계수를 곱한다. 무풍(ws<0.5)이면 1.0을 반환해
    기존 등방 모델과 정확히 동일한 결과를 준다.
    """
    import math
    if not weather:
        return 1.0
    ws = float(weather.get("ws_ms") or 0.0)
    wd = weather.get("wd_deg")
    if wd is None or ws < WIND_MIN_SPEED_MS:
        return 1.0
    theta = math.radians(float(wd) + 180.0)          # 이동(풍하) 방향
    dx_w, dy_w = math.sin(theta), math.cos(theta)     # 동/북 성분
    dx, dy = tgt_xy[0] - src_xy[0], tgt_xy[1] - src_xy[1]
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        return 1.0
    cos_sim = (dx * dx_w + dy * dy_w) / dist
    if cos_sim <= 0:
        return 1.0
    speed_factor = min(ws / WIND_REF_SPEED_MS, 1.0)
    return 1.0 + WIND_DIR_MAX_GAIN * cos_sim * speed_factor


def zone_risk_scores(zones, incidents, weather=None, source_zone=None, fire_sources=None):
    """구역별 위험 점수 r_z ∈ [0.1, 1.0]. weather(기상청 풍속·풍향) 있으면 보정 반영.

    source_zone: 누출·발화 가정 지점 구역 id. 지정하면 풍향 방향성 보정을 추가 적용한다
    (미지정 또는 무풍이면 기존 동작과 동일 — 하위 호환).
    fire_sources: fire_scenario 표준 발생원 리스트(위치·반경·세기). 지정하면 발생원 반경
    기준 거리 감쇠 가중을 곱하고, 풍향 보정도 각 발생원 기준으로 함께 적용한다
    (2026-07-27 PM 지시: 센서 미연동 상태에서 화재 위치·반경을 예시로 설정 가능하게).
    비면 계수가 정확히 1.0 이라 기존 결과와 수치가 동일하다.
    """
    fw = feature_weights(incidents)
    src_xy = None
    if source_zone and source_zone in zones:
        src_xy = (zones[source_zone]["cx"], zones[source_zone]["cy"])
    fire_mult = None
    if fire_sources:
        import fire_scenario
        fire_mult = lambda xy: fire_scenario.hazard_multiplier(  # noqa: E731
            xy, fire_sources, dir_weight=lambda a, b: downwind_weight(a, b, weather))
    raw = {}
    for zid, z in zones.items():
        feats = ZONE_FEATURES.get(z["type"], {})
        s = sum(fw[f] * v for f, v in feats.items())
        if z["type"] == "main_corridor":
            s *= CORRIDOR_BONUS
        s *= wind_multiplier(feats, weather)
        if src_xy is not None:
            s *= downwind_weight(src_xy, (z["cx"], z["cy"]), weather)
        if fire_mult is not None:
            s *= fire_mult((z["cx"], z["cy"]))
        raw[zid] = s
    lo, hi = min(raw.values()), max(raw.values())
    span = (hi - lo) or 1.0
    return {zid: 0.1 + 0.9 * (raw[zid] - lo) / span for zid in raw}


def edge_risks(zones, risk, edges, weather=None, source_zone=None, default_risk=None):
    """간선(통로) 통과 위험 w_e — 대피 QUBO의 신규 입력.

    w_e = (양 끝 구역 위험 평균) × (간선 중점의 풍하측 가중)
    - 구역 위험 r_z는 이미 정규화된 [0.1,1.0] 값을 그대로 사용 (센서 QUBO와 동일 소스).
    - 간선 중점에 방향성 가중을 다시 적용해 '연기가 지나가는 통로'를 벌점화한다.
    edges: {(u,v): {"length_m":..., "width_m":...}} 형태. 반환 {(u,v): w_e}
    """
    src_xy = None
    if source_zone and source_zone in zones:
        src_xy = (zones[source_zone]["cx"], zones[source_zone]["cy"])
    # 구역 위험이 정의되지 않은 노드(예: 합성 비상구 EX2)는 최소 위험으로 취급하고 명시한다.
    if default_risk is None:
        default_risk = min(risk.values()) if risk else 0.1
    out = {}
    for (u, v) in edges:
        base = (risk.get(u, default_risk) + risk.get(v, default_risk)) / 2.0
        if src_xy is None:
            out[(u, v)] = base
            continue
        mx = (zones[u]["cx"] + zones[v]["cx"]) / 2.0
        my = (zones[u]["cy"] + zones[v]["cy"]) / 2.0
        out[(u, v)] = base * downwind_weight(src_xy, (mx, my), weather)
    return out


def hard_cover_zones(zones):
    return sorted(z for z, v in zones.items() if v["type"] in HARD_COVER_ZONE_TYPES)
