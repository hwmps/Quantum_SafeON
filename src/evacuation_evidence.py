# -*- coding: utf-8 -*-
"""대피 경로 QUBO 근거 상수 로더 (Codex 정본: Data/12_evacuation_evidence_20260727)

- D1 법규기준  : 최대 보행거리, 통로·출입구 폭, 출구 수 (건축법 시행령 등)
- D2 보행유동  : 자유류 보행속도, 밀도-속도 관계식, 단위폭 최대 유동률, 유효폭 차감
- D4 가스물성  : 상대밀도·센서 높이 지침 (센서 배치 해설·발표용 메타)
- D6 현장인원  : 공개 프로젝트 피크 인원 + 합성 시나리오(toy/데모/확장성)

원칙: 이 파일은 수치를 '생성'하지 않는다. 정본 CSV에서 읽고, 못 읽으면 명시적 폴백 상수를
쓰되 meta에 fallback=True를 기록한다. 모든 수치는 출처·단위와 함께 결과 JSON에 남긴다.
"""
import csv
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data")
EV_DIR = os.path.join(DATA_DIR, "12_evacuation_evidence_20260727", "tables")

# 정본을 읽지 못할 때만 쓰는 폴백 (값·출처는 정본과 동일, 근거 추적 위해 명시)
FALLBACK = {
    "walk_distance_limit_m": 30.0,      # D1-LAW-001 건축법 시행령 제34조제1항
    "corridor_width_main_m": 1.5,       # D1-LAW-009 거실 양옆 복도
    "corridor_width_other_m": 1.2,      # D1-LAW-010 기타 복도
    "min_exits": 2,                     # D1-LAW-005 직통계단 2개소 이상
    "free_speed_ms": 1.19,              # D2-FLOW-001 NIST TN 1471
    "density_speed_a": 1.4,             # D2-FLOW-002 S = 1.4 - 0.37 D
    "density_speed_b": 0.37,            # D2-FLOW-003
    "density_valid_lo": 0.54,           # D2-FLOW-002 적용 하한 (persons/m^2)
    "density_valid_hi": 3.8,            # D2-FLOW-002 적용 상한
    "max_specific_flow": 1.3,           # D2-FLOW-004 persons/(m*s) of effective width
    "boundary_layer_m": 0.15,           # D2-FLOW-005 측벽 유효폭 차감 (편측)
}


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _num(v, default=None):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def load_evidence():
    """반환: dict(constants, gas, workforce, scenarios, sources, meta)"""
    law = _read(os.path.join(EV_DIR, "법규기준_excel_utf8.csv"))
    flow = _read(os.path.join(EV_DIR, "보행유동_excel_utf8.csv"))
    gas = _read(os.path.join(EV_DIR, "가스물성_excel_utf8.csv"))
    wf = _read(os.path.join(EV_DIR, "현장인원_excel_utf8.csv"))
    syn = _read(os.path.join(EV_DIR, "합성시나리오_excel_utf8.csv"))

    law_by_id = {r.get("record_id"): r for r in law}
    flow_by_id = {r.get("record_id"): r for r in flow}
    fallback_used = []

    def pick(table, rid, key, fb_key):
        row = table.get(rid)
        v = _num(row.get("clean_value")) if row else None
        if v is None:
            fallback_used.append(fb_key)
            return FALLBACK[fb_key], None
        return v, {
            "record_id": rid,
            "name": row.get("criterion_name") or row.get("metric"),
            "unit": row.get("unit"),
            "source": row.get("source_name"),
            "url": row.get("source_url"),
        }

    c, src = {}, {}
    spec = [
        ("walk_distance_limit_m", law_by_id, "D1-LAW-001"),
        ("corridor_width_main_m", law_by_id, "D1-LAW-009"),
        ("corridor_width_other_m", law_by_id, "D1-LAW-010"),
        ("min_exits", law_by_id, "D1-LAW-005"),
        ("free_speed_ms", flow_by_id, "D2-FLOW-001"),
        ("density_valid_lo", flow_by_id, "D2-FLOW-002"),
        ("density_speed_b", flow_by_id, "D2-FLOW-003"),
        ("max_specific_flow", flow_by_id, "D2-FLOW-004"),
        ("boundary_layer_m", flow_by_id, "D2-FLOW-005"),
    ]
    for key, table, rid in spec:
        c[key], s = pick(table, rid, "clean_value", key)
        if s:
            src[key] = s
    # 관계식 상수 a(=1.4)와 상한(3.8)은 formula_or_range 문자열에만 존재 → 폴백 상수 사용
    c["density_speed_a"] = FALLBACK["density_speed_a"]
    c["density_valid_hi"] = FALLBACK["density_valid_hi"]

    gases = [{
        "name": r.get("gas_name"), "formula": r.get("formula"),
        "relative_density_air": _num(r.get("relative_gas_density_air_1")),
        "detector_height": r.get("detector_height_guidance"),
        "source": r.get("source_name"),
    } for r in gas]

    workforce = [{
        "project": r.get("project"), "value": _num(r.get("clean_value")),
        "unit": r.get("unit"), "source": r.get("source_name"),
        "restriction": r.get("use_restriction"),
    } for r in wf]

    scenarios = [{
        "id": r.get("scenario_id"), "name": r.get("scenario_name"),
        "worker_count": int(_num(r.get("worker_count"), 0)),
        "definition": r.get("definition"), "limitation": r.get("limitation"),
    } for r in syn]

    return {
        "constants": c,
        "sources": src,
        "gas": gases,
        "workforce": workforce,
        "synthetic_scenarios": scenarios,
        "meta": {
            "origin": "Data/12_evacuation_evidence_20260727 (Codex 정본, 2026-07-27)",
            "fallback_used": sorted(set(fallback_used)),
            "note": ("현장인원 공개값은 전체 현장 일일 인원이므로 구역 동시밀도로 사용 금지. "
                     "대피 실험의 작업자 수는 합성 시나리오(D6-SYN-*)를 사용한다."),
        },
    }


def effective_width(physical_width_m, sides=2, boundary_m=None):
    """유효폭 = 물리폭 - 경계층 차감 (D2-FLOW-005). 음수 방지."""
    b = FALLBACK["boundary_layer_m"] if boundary_m is None else boundary_m
    return max(physical_width_m - sides * b, 0.1)


def edge_capacity(physical_width_m, constants=None):
    """통로 용량 c_e [persons/s] = 최대 단위폭 유동률 × 유효폭 (D2-FLOW-004)."""
    c = constants or FALLBACK
    return c["max_specific_flow"] * effective_width(physical_width_m,
                                                    boundary_m=c["boundary_layer_m"])


def speed_at_density(density, constants=None):
    """밀도-속도 관계 S = a - b·D (D2-FLOW-002/003). 정의역 밖은 외삽하지 않고 절단."""
    c = constants or FALLBACK
    if density <= c["density_valid_lo"]:
        return c["free_speed_ms"]
    d = min(density, c["density_valid_hi"])
    return max(c["density_speed_a"] - c["density_speed_b"] * d, 0.1)


if __name__ == "__main__":
    import json
    ev = load_evidence()
    print(json.dumps({"constants": ev["constants"], "meta": ev["meta"],
                      "n_gas": len(ev["gas"]), "scenarios": ev["synthetic_scenarios"]},
                     ensure_ascii=False, indent=2))
