# -*- coding: utf-8 -*-
"""QRC2026 센서 최적 배치 — 데이터 로더
Data/ 폴더의 Codex 제공 CSV(utf-8-sig)를 읽어 표준 자료구조로 변환한다.
정본: Data/00_master/QRC2026_detailed_research_data.xlsx (코드 경로는 _excel_utf8.csv 보조본 사용)
"""
import csv
import math
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data")


def _read_csv(relpath):
    path = os.path.join(DATA_DIR, relpath)
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_zones():
    """구역 12개: id, 이름, 유형, 중심좌표, 인접, 주요위험. data_status=synthetic 명시."""
    rows = _read_csv("01_layout/zone_graph_excel_utf8.csv")
    zones = {}
    for r in rows:
        zid = r["zone_id"]
        zones[zid] = {
            "name": r["zone_name"],
            "type": r["zone_type"],
            "cx": float(r["x_m"]) + float(r["width_m"]) / 2.0,
            "cy": float(r["y_m"]) + float(r["height_m"]) / 2.0,
            "adjacent": [a for a in r["adjacent_zone_ids"].split(";") if a],
            "hazard": r["primary_hazard"],
            "data_status": r["data_status"],  # research_derived_synthetic
        }
    return zones


def load_candidates():
    """센서 후보점 12개 (QUBO 이진 변수와 1:1 대응)."""
    rows = _read_csv("01_layout/sensor_candidates_12_excel_utf8.csv")
    return [
        {
            "id": r["candidate_id"],
            "zone_id": r["zone_id"],
            "x": float(r["x_m"]),
            "y": float(r["y_m"]),
            "family": r["preferred_sensor_family"],
            "data_status": r["data_status"],  # synthetic_candidate
        }
        for r in rows
    ]


# 후보 센서 계열 → 대표 장비 구성 매핑 (가정: 발표 자료에 명시할 것)
# 비용은 Codex 정리 공개가(장비만, 시공비 NA) 기준.
FAMILY_TO_SENSORS = {
    "smoke_or_multi": ["S01"],
    "gas_and_smoke": ["S01", "S03"],
    "silane_hydrogen_point": ["S04"],
    "gas_and_flame": ["S03"],
    "smoke_heat_flame": ["S01"],   # 2151T 상당은 상세본에만 있어 S01로 보수적 대체
    "smoke_heat": ["S01"],
    "smoke_sampling": ["S01"],
    "toxic_gas": ["S02"],
    "smoke_co": ["S01", "S02"],
    "gas_smoke": ["S01", "S03"],
}


def load_sensor_costs():
    """센서별 장비가(원, 계산값). 설치비는 NA → 제외하고 '장비가 기준'임을 명시."""
    rows = _read_csv("02_sensor_spec_cost/sensor_spec_cost_excel_utf8.csv")
    costs, radii = {}, {}
    for r in rows:
        sid = r["sensor_id"]
        costs[sid] = float(r["equipment_cost_krw_approx"])
        radii[sid] = {
            "low": float(r["qbo_radius_low_m"]),
            "nominal": float(r["qbo_radius_nominal_m"]),
            "high": float(r["qbo_radius_high_m"]),
        }
    return costs, radii


def candidate_cost(cand, costs):
    return sum(costs[s] for s in FAMILY_TO_SENSORS[cand["family"]])


def candidate_radius(cand, radii, scenario="nominal"):
    """후보 구성 장비 중 최대 반경 사용 (반경은 제품 사양이 아닌 민감도 분석 가정값)."""
    return max(radii[s][scenario] for s in FAMILY_TO_SENSORS[cand["family"]])


def coverage_matrix(zones, candidates, radii, scenario="nominal"):
    """a[z][j] = 후보 j가 구역 z 중심을 커버하면 1. 평면 직선거리 기준(한계: 벽·공조 미반영)."""
    zids = sorted(zones.keys())
    a = {z: [0] * len(candidates) for z in zids}
    for j, c in enumerate(candidates):
        r = candidate_radius(c, radii, scenario)
        for z in zids:
            d = math.hypot(c["x"] - zones[z]["cx"], c["y"] - zones[z]["cy"])
            if d <= r or c["zone_id"] == z:
                # 후보점은 해당 구역 감시 목적으로 선정됨 → 자기 구역은 커버로 간주
                a[z][j] = 1
    return a


def load_fractional_coverage(candidates, scenario="nominal"):
    """Codex 제공 부분면적 커버리지 행렬 v1 (2026-07-26 Claude 요청 #1 반영분).

    a[z][j] ∈ [0,1] = (후보 j 반경 원 ∩ 구역 z 사각형 면적) / 구역 면적 — 합성 파생값.
    한계(원자료 명시): 2D 평면·등방성 원형 반경 가정, 벽·높이·공조·가스 물성 미반영.
    candidates 리스트 순서에 맞춰 인덱스를 정렬한다.
    """
    rows = _read_csv("01_layout/coverage_matrix_fractional_excel_utf8.csv")
    col = {"low": "cover_low_계산", "nominal": "cover_nominal_계산", "high": "cover_high_계산"}[scenario]
    idx = {c["id"]: j for j, c in enumerate(candidates)}
    a = {}
    for r in rows:
        z = r["zone_id"]
        if z not in a:
            a[z] = [0.0] * len(candidates)
        a[z][idx[r["candidate_id"]]] = float(r[col])
    return a


def load_incidents():
    rows = _read_csv("03_incident_scenarios/incident_scenarios_detailed_excel_utf8.csv")
    return rows


def load_legal():
    rows = _read_csv("04_legal_criteria/legal_criteria_detailed_excel_utf8.csv")
    return rows


def load_ionq_noise():
    return _read_csv("05_ionq_noise/ionq_hardware_noise_parameters_excel_utf8.csv")
