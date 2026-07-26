# -*- coding: utf-8 -*-
"""CubiCasa5K 인벤토리(Codex, Data/10_cubicasa5k_inventory_20260726) 인제스트 모듈

목적 (Communication 2026-07-26 20:40 '다음 단계' 이행):
1) Codex 권장 샘플(recommended_samples.csv)에서 데모 적합 평면도 1개를 자동 선정한다
   (SVG 공간 수가 QUBO N=12에 가장 가까운 평면도 — 결정적 선택).
2) model.svg의 Space 폴리곤(공식 정답 주석, A-002)을 파싱해 zones + 센서 후보점
   (최대 12개, QUBO N=12 정합)을 생성한다.
3) 시나리오별(low/nominal/high) 부분면적 커버리지 행렬을 격자 샘플링으로 계산한다.
4) 산출물 2종:
   - results/cubicasa5k_demo_layout.json : 파이프라인 호환(zones/candidates/coverage) 데모 레이아웃
   - results/cubicasa5k_ui_example.json  : src/ui/index.html 내보내기와 동일 스키마의 UI 연동 예시

주의 (Codex assumptions_and_limits.csv 준수 — 발표 반영):
- A-001: 주거 평면도 — 반도체 현장 대표성 없음. data_status=residential_public_dataset 명시.
- A-003: SVG 좌표를 실제 미터로 해석하지 않는다. 아래 ASSUMED_LONG_SIDE_M은
  '명시적 합성 축척' 가정값이며(도면 긴 변 = 30 m 가정), 실측·법규 근거로 쓸 수 없다.
- A-005: CC BY-NC 4.0 — 데이터 파일을 제출물·공개 데모에 직접 포함하지 않고
  파생 결과(JSON 좌표·커버리지)만 사용, 출처 URL 인용.
"""
import csv
import json
import os
import re
import xml.etree.ElementTree as ET

from structured3d_ingest import (
    N_CANDIDATES, GRID_STEP, SCENARIO_RADII,
    point_in_polygon, sample_polygon, interior_centroid,
)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_DIR = os.path.join(BASE, "Data", "10_cubicasa5k_inventory_20260726", "tables")
RESULTS_DIR = os.path.join(BASE, "results")

# 명시적 '합성 축척' 가정 (A-003): 도면 viewBox 긴 변을 30 m로 간주.
# 실제 치수 아님 — UI·파이프라인 연동 데모 전용.
ASSUMED_LONG_SIDE_M = 30.0

SOURCE_NOTE = ("CubiCasa5K (CC BY-NC 4.0, https://github.com/CubiCasa/CubiCasa5k, "
               "https://zenodo.org/records/2613548) — 주거 평면도, 내부 개발 전용")


def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def polygon_area(poly):
    """Shoelace 절대 면적."""
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def pick_demo_plan():
    """권장 샘플 중 SVG 보유 + 공간 수가 N=12에 가장 가까운 평면도. 동률이면 sample_id 순."""
    rows = _read_csv(os.path.join(INV_DIR, "recommended_samples.csv"))
    ok = [r for r in rows if r.get("svg_path", "").strip() and r.get("svg_space_count", "").strip()]
    if not ok:
        raise RuntimeError("SVG 보유 권장 샘플이 없음 — recommended_samples.csv 확인 필요")
    return min(ok, key=lambda r: (abs(int(r["svg_space_count"]) - N_CANDIDATES), r["sample_id"]))


# ---------- SVG 파싱 ----------

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _class_tokens(el):
    return (el.get("class") or "").split()


def _parse_points(txt):
    nums = re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", txt or "")
    return [[float(nums[i]), float(nums[i + 1])] for i in range(0, len(nums) - 1, 2)]


def load_space_polygons(svg_abs_path):
    """class 토큰 'Space'를 가진 요소의 대표 폴리곤 목록과 viewBox (px)."""
    tree = ET.parse(svg_abs_path)
    root = tree.getroot()
    vb = (root.get("viewBox") or "").split()
    if len(vb) == 4:
        vb_w, vb_h = float(vb[2]), float(vb[3])
    else:
        vb_w = float(re.sub(r"[^\d.]", "", root.get("width", "0")) or 0)
        vb_h = float(re.sub(r"[^\d.]", "", root.get("height", "0")) or 0)
    spaces = []
    for el in root.iter():
        if "Space" not in _class_tokens(el):
            continue
        space_type = next((t for t in _class_tokens(el) if t != "Space"), "Space")
        best = None
        for sub in el.iter():
            if _local(sub.tag) != "polygon":
                continue
            pts = _parse_points(sub.get("points"))
            if len(pts) >= 3:
                a = polygon_area(pts)
                if best is None or a > best[0]:
                    best = (a, pts)
        if best and best[0] > 0:
            spaces.append({"space_type": space_type, "poly_px": best[1], "area_px2": best[0]})
    return spaces, vb_w, vb_h


# ---------- 변환 ----------

def build_layout(rec):
    svg_rel = rec["svg_path"]          # 예: Data/cubicasa5k/colorful/12202/model.svg
    svg_abs = os.path.join(BASE, svg_rel.replace("/", os.sep))
    spaces, vb_w, vb_h = load_space_polygons(svg_abs)
    if not spaces:
        raise RuntimeError(f"{svg_rel}: Space 폴리곤이 없음")

    # 명시적 합성 축척 (A-003) + SVG y축(하향)을 수학 좌표(상향)로 반전
    scale = ASSUMED_LONG_SIDE_M / max(vb_w, vb_h)
    for s in spaces:
        s["poly"] = [[round(x * scale, 3), round((vb_h - y) * scale, 3)] for x, y in s["poly_px"]]
        s["area_m2"] = polygon_area(s["poly"])
    spaces.sort(key=lambda s: -s["area_m2"])

    zones = {}
    samples_by_zone = {}
    for i, sp in enumerate(spaces):
        zid = f"Z{i+1:02d}"
        samples = sample_polygon(sp["poly"])
        samples_by_zone[zid] = samples
        cx, cy = interior_centroid(sp["poly"], samples)
        zones[zid] = {
            "name": sp["space_type"],
            "cx": round(cx, 3), "cy": round(cy, 3),
            "area_m2": round(sp["area_m2"], 2),
            "boundary_m": sp["poly"],
            "data_status": "residential_public_dataset",  # A-001: 주거 공개 데이터 — 실측 아님
        }

    # 후보점: 큰 공간부터 중심점 1개씩, 12개 초과 공간은 후보 없이 커버리지 대상만 유지.
    # 12개 미달이면 큰 공간에 제2후보(중심 최원거리 내부점) 추가 — structured3d_ingest와 동일 규칙.
    cands = []
    zone_ids = list(zones.keys())
    for zid in zone_ids:
        if len(cands) >= N_CANDIDATES:
            break
        z = zones[zid]
        cands.append({"id": f"C{len(cands)+1:02d}", "zone_id": zid,
                      "x": z["cx"], "y": z["cy"], "kind": "space_centroid"})
    zi = 0
    while len(cands) < N_CANDIDATES and zi < len(zone_ids):
        z = zones[zone_ids[zi]]
        samples = samples_by_zone[zone_ids[zi]]
        if len(samples) > 1:
            fx, fy = max(samples, key=lambda p: (p[0] - z["cx"]) ** 2 + (p[1] - z["cy"]) ** 2)
            if (fx - z["cx"]) ** 2 + (fy - z["cy"]) ** 2 > 1.0:
                cands.append({"id": f"C{len(cands)+1:02d}", "zone_id": zone_ids[zi],
                              "x": round(fx, 3), "y": round(fy, 3), "kind": "space_secondary"})
        zi += 1

    coverage = {}
    for scen, r in SCENARIO_RADII.items():
        r2 = r * r
        mat = {}
        for c in cands:
            row = {}
            for zid in zone_ids:
                pts = samples_by_zone[zid]
                hit = sum(1 for (px, py) in pts
                          if (px - c["x"]) ** 2 + (py - c["y"]) ** 2 <= r2)
                row[zid] = round(hit / len(pts), 4)
            mat[c["id"]] = row
        coverage[scen] = mat

    return {
        "source": "Data/10_cubicasa5k_inventory_20260726 (Codex 인벤토리 정본) + " + SOURCE_NOTE,
        "sample_id": rec["sample_id"],
        "plan_id": rec["plan_id"],
        "variant": rec["variant"],
        "split": rec["split"],
        "image_path": rec["image_path"],   # UI 업로드용 PNG (동일 평면도)
        "svg_path": svg_rel,
        "data_status": "residential_public_dataset",
        "usage_note": ("주거 평면도 데모 — UI 업로드→센서 배치→JSON 내보내기→커버리지 연동 검증 전용. "
                       f"좌표는 '긴 변 {ASSUMED_LONG_SIDE_M:.0f} m' 합성 축척 가정(A-003)이며 실측 아님. "
                       "CC BY-NC 4.0 — 데이터 원본은 제출물에 미포함(A-005)."),
        "assumed_long_side_m": ASSUMED_LONG_SIDE_M,
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
        "source_scene": f"cubicasa5k:{layout['variant']}:{layout['plan_id']}",
        "sensors": [{"id": f"S{i+1}", "x_m": c["x"], "y_m": c["y"],
                     "radius_m": SCENARIO_RADII["nominal"]}
                    for i, c in enumerate(layout["candidates"])],
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    rec = pick_demo_plan()
    layout = build_layout(rec)

    p1 = os.path.join(RESULTS_DIR, "cubicasa5k_demo_layout.json")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    p2 = os.path.join(RESULTS_DIR, "cubicasa5k_ui_example.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(export_ui_example(layout), f, ensure_ascii=False, indent=2)

    nz, nc = len(layout["zones"]), len(layout["candidates"])
    cov_n = layout["coverage"]["nominal"]
    self_cov = [cov_n[c["id"]][c["zone_id"]] for c in layout["candidates"]]
    total_area = sum(z["area_m2"] for z in layout["zones"].values())
    print(f"평면도: {layout['sample_id']} ({layout['variant']}/{layout['plan_id']}, {layout['split']})"
          f" | 공간 {nz}개, 후보 {nc}개, 총면적(합성 축척) {total_area:.1f} m2")
    print(f"nominal 자기구역 커버율 min/max: {min(self_cov):.3f} / {max(self_cov):.3f}")
    print(f"저장: {p1}")
    print(f"저장: {p2}")


if __name__ == "__main__":
    main()
