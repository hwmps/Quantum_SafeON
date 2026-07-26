# -*- coding: utf-8 -*-
"""QRC2026 센서 최적 배치 — 전체 파이프라인 실행

데이터(Data/) → 위험 점수 → QUBO → 베이스라인 4종 + QAOA(p=1,2) → 민감도 분석(low/nominal/high)
결과: results/experiment_results.json, results/실험결과_요약.md

주의(발표 반영):
- 레이아웃·후보점은 research_derived_synthetic (실도면 아님)
- 감지 반경은 제품 사양이 아닌 민감도 분석 가정값 → low/nominal/high 3종 실행
- 비용은 공개 장비가만 (시공비 NA)
- '양자 이득' 주장 금지 — 근사비/최적해 확률 중심 해석
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_loader as dl
from risk_model import zone_risk_scores, hard_cover_zones, feature_weights
from qubo import N, build_qubo, all_energies, true_metrics
from baselines import solve_exact, solve_greedy, solve_sa, solve_random
from qaoa_sim import run_qaoa
import weather_kma

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
K_SENSORS = 6  # 센서 수 제한 (예산 가정 — PM 확정 필요)
HARD_TAU = 0.27  # hard 제약 커버율 임계값 (PM 지시 2026-07-26: low 시나리오 Z10 구조적 미충족(최대 0.283) 해소 위해 0.3→0.27 하향)


def run_scenario(scenario, zones, candidates, incidents, costs, radii, weather=None):
    # 2026-07-26: Codex 부분면적 커버리지 행렬 v1 사용 (기존 이진 행렬은 dl.coverage_matrix로 유지)
    a = dl.load_fractional_coverage(candidates, scenario)
    risk = zone_risk_scores(zones, incidents, weather=weather)
    hard = hard_cover_zones(zones)
    cand_costs = [dl.candidate_cost(c, costs) for c in candidates]

    Q, const, notes = build_qubo(zones, candidates, a, risk, cand_costs, hard,
                                 K=K_SENSORS, hard_tau=HARD_TAU)
    E, _ = all_energies(Q, const)

    res = {"scenario": scenario, "qubo_notes": notes, "risk_scores": {k: round(v, 4) for k, v in risk.items()}}

    # 베이스라인 4종
    sols = [solve_exact(Q, const), solve_greedy(Q, const), solve_sa(Q, const), solve_random(Q, const)]
    e_opt = sols[0]["energy"]
    for s in sols:
        s["true_metrics"] = true_metrics(zones, a, risk, cand_costs, hard, s["x"], hard_tau=HARD_TAU)
        s["gap_to_exact"] = round(s["energy"] - e_opt, 6)
        s["time_s"] = round(s["time_s"], 4)
    res["baselines"] = sols

    # QAOA p=1, p=2 (Ideal Simulator)
    qaoa = []
    for p in (1, 2):
        q = run_qaoa(E, p=p, shots=2048)
        q["best_sampled_true_metrics"] = true_metrics(zones, a, risk, cand_costs, hard, q["best_sampled_x"], hard_tau=HARD_TAU)
        q["best_sampled_gap_to_exact"] = round(q["best_sampled_energy"] - e_opt, 6)
        q["time_s"] = round(q["time_s"], 2)
        qaoa.append(q)
    res["qaoa_ideal"] = qaoa

    # 정합성 검증: QAOA 샘플 최적해가 Exact와 일치하는가
    res["validation"] = {
        "qaoa_p1_found_exact": qaoa[0]["best_sampled_energy"] == e_opt,
        "qaoa_p2_found_exact": qaoa[1]["best_sampled_energy"] == e_opt,
        "exact_solution_x": sols[0]["x"],
        "exact_selected_candidates": [candidates[j]["id"] for j in range(N) if sols[0]["x"][j]],
    }
    return res


def main():
    zones = dl.load_zones()
    candidates = dl.load_candidates()
    incidents = dl.load_incidents()
    costs, radii = dl.load_sensor_costs()
    weather = weather_kma.load_cached_weather()  # 캐시 없으면 None → 보정 없이 실행

    out = {
        "meta": {
            "problem": "반도체 건설현장 안전 센서 최적 배치 (QUBO, 변수 12)",
            "K_sensors": K_SENSORS,
            "hard_tau": HARD_TAU,
            "weather": weather or "미반영 (Data/06_weather 캐시 없음 — src/weather_kma.py 로 수집)",
            "data_status": "레이아웃/후보점 synthetic, 반경은 민감도 가정값, 비용은 공개 장비가만",
            "coverage_source": "Data/01_layout/coverage_matrix_fractional_excel_utf8.csv (부분면적 v1, 합성 파생: 원∩사각형 면적비, 벽·공조 미반영)",
            "feature_weights": {k: round(v, 4) for k, v in feature_weights(incidents).items()},
        },
        "scenarios": {},
    }
    for sc in ("low", "nominal", "high"):
        print(f"=== 시나리오: {sc} ===")
        out["scenarios"][sc] = run_scenario(sc, zones, candidates, incidents, costs, radii, weather=weather)
        v = out["scenarios"][sc]["validation"]
        print("  Exact 선택:", v["exact_selected_candidates"])
        print("  QAOA p=1 최적해 발견:", v["qaoa_p1_found_exact"], "| p=2:", v["qaoa_p2_found_exact"])

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "experiment_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    write_summary(out)
    print("\n저장 완료: results/experiment_results.json, results/실험결과_요약.md")


def write_summary(out):
    L = ["# 실험 결과 요약 — 센서 최적 배치 (QUBO + QAOA Ideal)",
         "",
         f"- 문제: {out['meta']['problem']}, 센서 수 제한 K={out['meta']['K_sensors']}, "
         f"hard 커버율 임계값 τ={out['meta']['hard_tau']} (PM 확정 2026-07-26)",
         f"- 기상 보정: {out['meta']['weather']}",
         f"- 데이터 상태: {out['meta']['data_status']}",
         "- 해석 원칙: '양자 이득' 주장 없음. Ideal Simulator에서 QUBO 정식화의 정합성 검증이 목적.",
         ""]
    for sc, r in out["scenarios"].items():
        L.append(f"## 반경 시나리오: {sc}")
        L.append("")
        L.append("| 방법 | 에너지 | Exact 대비 격차 | 커버리지(가중) | 비용(원) | 센서 수 | hard 충족 | 시간(s) |")
        L.append("|---|---|---|---|---|---|---|---|")
        for s in r["baselines"]:
            m = s["true_metrics"]
            L.append(f"| {s['method']} | {s['energy']:.3f} | {s['gap_to_exact']:.3f} | "
                     f"{m['weighted_coverage']:.3f} | {m['total_cost_krw']:,} | {m['n_sensors']} | "
                     f"{'O' if m['hard_constraints_ok'] else 'X'} | {s['time_s']} |")
        for q in r["qaoa_ideal"]:
            m = q["best_sampled_true_metrics"]
            L.append(f"| QAOA p={q['p']} (best of {q['shots']} shots) | {q['best_sampled_energy']:.3f} | "
                     f"{q['best_sampled_gap_to_exact']:.3f} | {m['weighted_coverage']:.3f} | "
                     f"{m['total_cost_krw']:,} | {m['n_sensors']} | "
                     f"{'O' if m['hard_constraints_ok'] else 'X'} | {q['time_s']} |")
        L.append("")
        for q in r["qaoa_ideal"]:
            L.append(f"- QAOA p={q['p']}: 근사비 {q['approx_ratio']}, 최적해 확률 {q['prob_optimal']} "
                     f"(균등 샘플링 대비 {q['prob_optimal_vs_uniform']}배 증폭)")
        v = r["validation"]
        L.append(f"- Exact 최적 배치: {', '.join(v['exact_selected_candidates'])}")
        rz = r["qubo_notes"].get("hard_relaxed_zones", [])
        if rz:
            L.append(f"- ⚠ hard 완화 구역: {', '.join(rz)} — 이 시나리오에서는 어떤 조합으로도 "
                     f"커버율 τ={out['meta']['hard_tau']} 도달 불가(최대 가능 커버율 < τ). 센서 추가·반경 재검토 필요 사항으로 보고.")
        L.append("")
    with open(os.path.join(RESULTS_DIR, "실험결과_요약.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
