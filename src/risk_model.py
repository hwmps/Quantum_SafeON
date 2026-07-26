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


def zone_risk_scores(zones, incidents, weather=None):
    """구역별 위험 점수 r_z ∈ [0.1, 1.0]. weather(기상청 풍속·풍향) 있으면 보정 반영."""
    fw = feature_weights(incidents)
    raw = {}
    for zid, z in zones.items():
        feats = ZONE_FEATURES.get(z["type"], {})
        s = sum(fw[f] * v for f, v in feats.items())
        if z["type"] == "main_corridor":
            s *= CORRIDOR_BONUS
        s *= wind_multiplier(feats, weather)
        raw[zid] = s
    lo, hi = min(raw.values()), max(raw.values())
    span = (hi - lo) or 1.0
    return {zid: 0.1 + 0.9 * (raw[zid] - lo) / span for zid in raw}


def hard_cover_zones(zones):
    return sorted(z for z, v in zones.items() if v["type"] in HARD_COVER_ZONE_TYPES)
