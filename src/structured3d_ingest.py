# -*- coding: utf-8 -*-
"""Structured3D 전처리본(Codex, Data/09_structured3d_preprocessed_20260726) 인제스트 모듈

목적 (PM notes 2026-07-26 지시: "코덱스 전처리 후 활용 가능한 데이터 즉시 활용"):
1) Codex 정본 테이블(room_geometry / scene_summary / room_semantic_label_stats)에서
   데모 적합 장면 1개를 자동 선정한다.
2) 실제 방 경계 폴리곤(m 단위)으로 zones + 센서 후보점(최대 12개, QUBO N=12 정합)을 생성한다.
3) 시나리오별(low/nominal/high) 부분면적 커버리지 행렬을 격자 샘플링으로 계산한다.
4) 산출물 2종:
   - results/structured3d_demo_layout.json  : 파이프라인 호환(zones/candidates/coverage) 데모 레이아웃
   - results/structured3d_ui_example.json   : src/ui/index.html 내보내기와 동일 스키마의 UI 연동 예시

주의(발표 반영):
- Structured3D는 합성 '주거 실내' 데이터다. 반도체 건설현장 실측이 아니며,
  본 산출물은 '실기하 기반 파이프라인 검증 + UI 예시' 용도로만 사용한다 (data_status 명시).
- semantic 비율은 원근 뷰 픽셀 빈도이므로 위험 점수 근거가 아닌 'ML feature 예시'로만 첨부한다.
- 이용조건: Structured3D Terms of Use (내부 연구·대회 개발용, 외부 재배포 전 재확인).
"""
import csv
import json
import math
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_DIR = os.path.join(BASE, "Data", "09_structured3d_preprocessed_20260726", "tables")
RESULTS_DIR = os.path.join(BASE, "results")

N_CANDIDATES = 12  # QUBO 이진 변수 수와 1:1
GRID_STEP = 0.25   # 폴리곤 격자 샘플링 간격 (m)
# UI(src/ui/index.html) 자동 반경 가정과 동일 (제품 사양 아님 — 민감도 분석 가정값)
SCENARIO_RADII = {"low": 3.0, "nominal": 5.0, "high": 8.0}


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------- 기하 유틸 ----------

def point_in_polygon(x, y, poly):
    """레이 캐스팅. poly=[[x,y],...] (닫힘 불필요)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def sample_polygon(poly, step=GRID_STEP):
    """폴리곤 내부 격자점 목록. 소형 방도 최소 1점 확보(무게중심 폴백)."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    pts = []
    x = min(xs) + step / 2.0
    while x < max(xs):
        y = min(ys) + step / 2.0
        while y < max(ys):
            if point_in_polygon(x, y, poly):
                pts.append((x, y))
            y += step
        x += step
    if not pts:
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        pts.append((cx, cy))
    return pts


def interior_centroid(poly, samples):
    """무게중심이 폴리곤 밖이면(오목) 가장 가까운 내부 샘플점으로 스냅."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    if point_in_polygon(cx, cy, poly):
        return cx, cy
    return min(samples, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)


# ---------- 데이터 로드 ----------

def pick_demo_scene(scene_rows):
    """검수 통과(미해결 면적 0, 리뷰 필요 0) 장면 중 방 수가 12에 가장 가까운 장면.
    동률이면 총면적 큰 쪽. 결정적(재현 가능) 선택."""
    ok = [r for r in scene_rows
          if r["rooms_with_unresolved_area"] == "0" and r["rooms_requiring_review"] == "0"]
    if not ok:
        raise RuntimeError("검수 통과 장면이 없음 — quality_report 확인 필요")
    return min(ok, key=lambda r: (abs(int(r["room_count"]) - N_CANDIDATES),
                                  -float(r["floor_area_total_m2"]),
                                  r["scene_id"]))


def load_scene_rooms(scene_id):
    rows = _read_csv(os.path.join(PRE_DIR, "room_geometry.csv"))
    rooms = []
    for r in rows:
        if r["scene_id"] != scene_id or r["geometry_status"] != "ok":
            continue
        if r["recommended_for_ml"].strip().lower() != "true":
            continue
        rooms.append({
            "room_key": r["room_key"],
            "room_id": r["room_id"],
            "room_type": r["room_type"],
            "area_m2": float(r["area_m2"]),
            "poly": json.loads(r["boundary_vertices_m_json"]),
        })
    return rooms


def load_room_semantic_top(scene_id, top_k=3):
    """방별 상위 semantic 라벨(픽셀 비율) — ML feature 예시용. void/background 제외."""
    rows = _read_csv(os.path.join(PRE_DIR, "room_semantic_label_stats.csv"))
    per_room = {}
    for r in rows:
        if r["scene_id"] != scene_id or r["label_id"] == "0":
            continue
        per_room.setdefault(r["room_id"], []).append(
            {"label": r["label_name"], "pixel_share": round(float(r["pixel_share"]), 4)})
    return {rid: sorted(v, key=lambda d: -d["pixel_share"])[:top_k] for rid, v in per_room.items()}


# ---------- 변환 ----------

def build_layout(scene_row):
    scene_id = scene_row["scene_id"]
    rooms = load_scene_rooms(scene_id)
    if not rooms:
        raise RuntimeError(f"{scene_id}: 사용 가능한 방이 없음")
    rooms.sort(key=lambda r: -r["area_m2"])
    sem_top = load_room_semantic_top(scene_id)

    # zones: 방 1개 = 구역 1개
    zones = {}
    samples_by_room = {}
    for i, rm in enumerate(rooms):
        samples = sample_polygon(rm["poly"])
        samples_by_room[rm["room_key"]] = samples
        cx, cy = interior_centroid(rm["poly"], samples)
        zones[f"Z{i+1:02d}"] = {
            "room_key": rm["room_key"],
            "name": rm["room_type"],
            "cx": round(cx, 3), "cy": round(cy, 3),
            "area_m2": round(rm["area_m2"], 2),
            "boundary_m": rm["poly"],
            "semantic_top_labels": sem_top.get(rm["room_id"], []),
            "data_status": "synthetic_structured3d",  # 주거 합성 — 실측 아님
        }

    # 후보점: 큰 방부터 중심점 1개씩, 12개 미달이면 큰 방에 제2후보(중심에서 최원거리 내부점) 추가
    cands = []
    zone_ids = list(zones.keys())
    for zid in zone_ids:
        if len(cands) >= N_CANDIDATES:
            break
        z = zones[zid]
        cands.append({"id": f"C{len(cands)+1:02d}", "zone_id": zid,
                      "x": z["cx"], "y": z["cy"], "kind": "room_centroid"})
    zi = 0
    while len(cands) < N_CANDIDATES and zi < len(zone_ids):
        z = zones[zone_ids[zi]]
        samples = samples_by_room[z["room_key"]]
        if len(samples) > 1:
            fx, fy = max(samples, key=lambda p: (p[0] - z["cx"]) ** 2 + (p[1] - z["cy"]) ** 2)
            if (fx - z["cx"]) ** 2 + (fy - z["cy"]) ** 2 > 1.0:  # 1m 이상 떨어질 때만
                cands.append({"id": f"C{len(cands)+1:02d}", "zone_id": zone_ids[zi],
                              "x": round(fx, 3), "y": round(fy, 3), "kind": "room_secondary"})
        zi += 1

    # 시나리오별 부분면적 커버리지 a[c][z] = 반경 r 원이 덮는 방 샘플점 비율
    coverage = {}
    for scen, r in SCENARIO_RADII.items():
        r2 = r * r
        mat = {}
        for c in cands:
            row = {}
            for zid, z in zones.items():
                pts = samples_by_room[z["room_key"]]
                hit = sum(1 for (px, py) in pts
                          if (px - c["x"]) ** 2 + (py - c["y"]) ** 2 <= r2)
                row[zid] = round(hit / len(pts), 4)
            mat[c["id"]] = row
        coverage[scen] = mat

    return {
        "source": "Data/09_structured3d_preprocessed_20260726 (Codex 전처리 정본)",
        "scene_id": scene_id,
        "scene_floor_area_total_m2": float(scene_row["floor_area_total_m2"]),
        "data_status": "synthetic_structured3d",
        "usage_note": "합성 주거 실내 — 실기하 기반 파이프라인 검증·UI 예시 전용. 반도체 현장 아님.",
        "scenario_radii_m": SCENARIO_RADII,
        "grid_step_m": GRID_STEP,
        "zones": zones,
        "candidates": cands,
        "coverage": coverage,
    }


def export_ui_example(layout):
    """src/ui/index.html '센서 좌표 JSON 다운로드'와 동일 스키마 — UI↔파이프라인 연동 예시."""
    return {
        "radius_mode": "auto",
        "auto_radius_m": SCENARIO_RADII["nominal"],
        "source_scene": layout["scene_id"],
        "sensors": [{"id": f"S{i+1}", "x_m": c["x"], "y_m": c["y"],
                     "radius_m": SCENARIO_RADII["nominal"]}
                    for i, c in enumerate(layout["candidates"])],
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    scene_rows = _read_csv(os.path.join(PRE_DIR, "scene_summary.csv"))
    scene = pick_demo_scene(scene_rows)
    layout = build_layout(scene)

    p1 = os.path.join(RESULTS_DIR, "structured3d_demo_layout.json")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    p2 = os.path.join(RESULTS_DIR, "structured3d_ui_example.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(export_ui_example(layout), f, ensure_ascii=False, indent=2)

    nz, nc = len(layout["zones"]), len(layout["candidates"])
    cov_n = layout["coverage"]["nominal"]
    # 검증 출력: nominal에서 후보별 자기 구역 커버율
    self_cov = [cov_n[c["id"]][c["zone_id"]] for c in layout["candidates"]]
    print(f"장면: {layout['scene_id']} | 구역 {nz}개, 후보 {nc}개, 총면적 {layout['scene_floor_area_total_m2']:.1f} m2")
    print(f"nominal 자기구역 커버율 min/max: {min(self_cov):.3f} / {max(self_cov):.3f}")
    print(f"저장: {p1}")
    print(f"저장: {p2}")


if __name__ == "__main__":
    main()
