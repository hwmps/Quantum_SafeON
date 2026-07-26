# -*- coding: utf-8 -*-
"""CubiCasa5K REC-008 UI↔QUBO 전체 흐름 검증 (Codex 2026-07-26 21:13 후속 조치 이행)

검증 항목 (PNG 업로드→센서 배치→JSON 내보내기→부분면적 커버리지→QUBO 최적화):
V1. REC-008 PNG(F1_scaled.png) 존재·정상 열기 (UI 업로드 단계 대체 검증)
V2. UI 내보내기 JSON(cubicasa5k_ui_example.json)의 센서 좌표가
    파이프라인 후보점(cubicasa5k_demo_layout.json candidates)과 일치
V3. 커버리지 행렬 재계산 대조 — zones 기하에서 nominal 커버리지를 독립 재계산하여
    저장된 coverage['nominal']과 허용오차 내 일치 확인
V4. UI JSON → QUBO(N=12, hard_tau=0.27) → 베이스라인 4종(Exact/Greedy/SA/Random)
    실행, Exact 최적해 대비 각 해의 에너지 검증 (Exact ≤ 나머지)
V5. 정본 매니페스트 정합 — plan_manifest에서 REC-008 계획(5570)이
    ml_recommended=TRUE 인지, 공식 분할 4200/400/400 유지 확인
V6. data_status=residential_public_dataset 표기 유지 확인

주의: 주거 평면도 합성 축척 데모 — 위험도는 구역 면적 비례의 '합성 위험도'로만
설정(실제 위험 근거 아님). 실제 파이프라인에서는 risk_model 점수를 사용한다.
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qubo import build_qubo, energy
from baselines import solve_exact, solve_greedy, solve_sa, solve_random
from cubicasa5k_ingest import ASSUMED_LONG_SIDE_M
from structured3d_ingest import GRID_STEP, SCENARIO_RADII, point_in_polygon

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(BASE, "results")
INV = os.path.join(BASE, "Data", "10_cubicasa5k_inventory_20260726", "tables")

HARD_TAU = 0.27  # PM 확정 2026-07-26
N = 12
K = 6
TOL = 0.02  # 커버리지 재계산 허용오차 (격자 샘플링 오차)

report = {"target": "REC-008 (high_quality_architectural/5570)", "checks": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "pass": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + detail if detail else ""))
    return ok


def main():
    layout = json.load(open(os.path.join(RES, "cubicasa5k_demo_layout.json"), encoding="utf-8"))
    ui = json.load(open(os.path.join(RES, "cubicasa5k_ui_example.json"), encoding="utf-8"))

    # V1: PNG 존재·열기
    png = os.path.join(BASE, layout["image_path"])
    ok_open = os.path.isfile(png)
    detail = f"{layout['image_path']} ({os.path.getsize(png)} bytes)" if ok_open else "파일 없음"
    if ok_open:
        try:
            from PIL import Image
            with Image.open(png) as im:
                im.verify()
            detail += " | PIL verify OK"
        except ImportError:
            with open(png, "rb") as f:
                ok_open = f.read(8)[:4] == b"\x89PNG"
            detail += " | PNG 시그니처 OK"
        except Exception as e:
            ok_open = False
            detail += f" | 열기 실패: {e}"
    check("V1 PNG 존재·정상 열기", ok_open, detail)

    # V2: UI 센서 좌표 == 후보점 좌표
    cands = layout["candidates"]
    sensors = ui["sensors"]
    ok2 = len(sensors) == len(cands) == N and all(
        abs(s["x_m"] - c["x"]) < 1e-6 and abs(s["y_m"] - c["y"]) < 1e-6
        for s, c in zip(sensors, cands))
    check("V2 UI JSON 센서 = 파이프라인 후보점", ok2,
          f"센서 {len(sensors)}개, 반경 {ui['auto_radius_m']} m")

    # V3: nominal 커버리지 독립 재계산 대조
    r_nom = SCENARIO_RADII["nominal"]
    zones = layout["zones"]
    cov_stored = layout["coverage"]["nominal"]
    max_err, n_cells = 0.0, 0
    for zid, z in zones.items():
        poly = [tuple(p) for p in z["boundary_m"]]
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        pts = []
        gx = np.arange(min(xs) + GRID_STEP / 2, max(xs), GRID_STEP)
        gy = np.arange(min(ys) + GRID_STEP / 2, max(ys), GRID_STEP)
        for x in gx:
            for y in gy:
                if point_in_polygon(x, y, poly):
                    pts.append((x, y))
        if not pts:
            continue
        for c in cands:
            inside = sum(1 for (x, y) in pts
                         if (x - c["x"]) ** 2 + (y - c["y"]) ** 2 <= r_nom ** 2)
            recomputed = inside / len(pts)
            stored = cov_stored[c["id"]][zid]
            max_err = max(max_err, abs(recomputed - stored))
            n_cells += 1
    check("V3 커버리지 재계산 대조", max_err <= TOL,
          f"{n_cells}쌍, 최대 오차 {max_err:.4f} (허용 {TOL})")

    # V4: UI JSON → QUBO → 베이스라인 4종
    zids = sorted(zones.keys())
    zmap = {z: i for i, z in enumerate(zids)}
    a = {z: [cov_stored[cands[j]["id"]][z] for j in range(N)] for z in zids}
    areas = np.array([zones[z]["area_m2"] for z in zids])
    risk = {z: round(float(areas[zmap[z]] / areas.max()), 4) for z in zids}  # 합성 위험도(면적 비례)
    costs = [1.0] * N
    hard = [zids[int(np.argmax(areas))]]  # 최대 면적 구역 1개를 hard 예시로
    Q, const, notes = build_qubo(zones, cands, a, risk, costs, hard,
                                 K=K, hard_tau=HARD_TAU)
    sols = {"Exact": solve_exact(Q, const), "Greedy": solve_greedy(Q, const),
            "SA": solve_sa(Q, const), "Random": solve_random(Q, const)}
    ens = {}
    for name, s in sols.items():
        x = np.array(s[0] if isinstance(s, tuple) else s["x"] if isinstance(s, dict) else s)
        ens[name] = round(float(energy(Q, const, x)), 4)
    e_exact = ens["Exact"]
    ok4 = all(e_exact <= e + 1e-9 for e in ens.values())
    check("V4 QUBO+베이스라인 4종 (hard_tau=0.27)", ok4,
          " / ".join(f"{k}={v}" for k, v in ens.items()))
    report["qubo"] = {"K": K, "hard_tau": HARD_TAU, "hard_zones": hard,
                      "energies": ens, "risk_note": "합성 위험도(면적 비례) — 데모 전용"}

    # V5: 정본 매니페스트 정합
    with open(os.path.join(INV, "plan_manifest.csv"), encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    splits = {}
    rec_row = None
    for r in rows:
        splits[r["split"]] = splits.get(r["split"], 0) + 1
        if r["plan_id"] == "5570" and r.get("variant") == "high_quality_architectural":
            rec_row = r
    ml_ok = rec_row is not None and str(rec_row.get("ml_recommended", "")).upper() == "TRUE"
    split_ok = splits.get("train") == 4200 and splits.get("val") == 400 and splits.get("test") == 400
    check("V5 정본 정합 (ml_recommended·분할)", ml_ok and split_ok,
          f"REC-008 ml_recommended={rec_row.get('ml_recommended') if rec_row else '행 없음'}, "
          f"분할 {splits}")

    # V6: data_status 표기
    ok6 = layout.get("data_status") == "residential_public_dataset" and all(
        z.get("data_status") == "residential_public_dataset" for z in zones.values())
    check("V6 residential_public_dataset 표기", ok6)

    report["all_pass"] = all(c["pass"] for c in report["checks"])
    out = os.path.join(RES, "cubicasa5k_e2e_verification.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(("\n전체 결과: " + ("ALL PASS" if report["all_pass"] else "FAIL 존재")) +
          f" | 저장: {out}")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
