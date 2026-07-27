# -*- coding: utf-8 -*-
"""대피 경로 QUBO 실험 (파트 2-B) + 센서 결합 A + 기상 민감도

파이프라인:
  Data/01_layout(구역) + Data/03(사고사례) + Data/06_weather(기상 실측)
    → r_z (풍향 방향성 반영)  → 구역 그래프 → 간선 위험 w_e
    → [결합 A] 센서 배치 결과(results/experiment_results.json)의 커버리지로 미관측 구역 위험 상향
    → 대피 QUBO(12변수) → 베이스라인 4종 + 도메인 2종 + QAOA(p=1,2)

결과: results/evacuation_results.json, results/대피실험_요약.md

주의(발표 반영):
- 레이아웃·작업자 배치는 합성(synthetic). EX2 비상구는 법정 출구 수 요건 충족용 합성 노드.
- '양자 이득' 주장 금지 — 근사비·최적해 확률과 오류 요인 중심으로 해석.
- 밀도-속도·용량은 문헌 수리모델(D2) 적용 범위 안에서만 사용하고 외삽하지 않는다.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_loader as dl
import weather_kma
from baselines import solve_exact, solve_greedy, solve_sa, solve_random
from evacuation_evidence import load_evidence
from evacuation_qubo import build_qubo, build_variables, decode, true_metrics
from qaoa_sim import run_qaoa
from qubo import all_energies
from risk_model import edge_risks, zone_risk_scores
from zone_graph import build_graph

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "results")

# ── 모델링 가정 (모두 발표 자료에 명시) ──────────────────────────────────────
SOURCE_ZONE = "Z04"        # 누출·발화 가정 지점: 특수가스 캐비닛·VMB 구역 (최고 위험 유형)
KAPPA_UNOBSERVED = 0.30    # 결합 A: 미관측 구역 위험 상향 계수 (보수적 취급)
# 작업자 그룹: 합성 배치 (D6-SYN-00x 인원을 4개 작업조로 균등 분할)
GROUP_ORIGINS = [
    ("W1", "Z01", "클린룸 시공 서측 작업조"),
    ("W2", "Z03", "서브팹·유틸리티 작업조"),
    ("W3", "Z06", "용접·화기 작업조"),
    ("W4", "Z09", "팬데크·공조 작업조"),
]
# 인원 규모 시나리오 — 혼잡 이차항이 언제 지배적이 되는지(교차점)를 보기 위해 2종 실행
WORKER_SCENARIOS = [
    {"id": "D6-SYN-002", "name": "중형 데모 24명", "total": 24},
    {"id": "D6-SYN-003", "name": "확장성 분석 60명", "total": 60},
    {"id": "파생-320", "name": "혼잡 지배 구간 320명(파생 가정)", "total": 320,
     "note": ("교차점 분석에서 독립 최단경로가 최적이 아니게 되는 구간. D6-SYN 표에 없는 "
              "파생 가정치이며, 현장 전체 인원(D6-WF-001 4,200명·D6-WF-002 6,000명)의 "
              "한 대피 섹터 규모로 해석한다. 실측 아님.")},
]
K_ROUTES = 3               # 그룹당 후보 경로 수 → 변수 4×3 = 12


def make_groups(total):
    n = total // len(GROUP_ORIGINS)
    return [{"id": gid, "origin": o, "n": n, "desc": d} for gid, o, d in GROUP_ORIGINS]


def sensor_coverage_fraction(zones, candidates, scenario="nominal", results_path=None):
    """센서 배치 최적해로부터 구역별 union 커버율을 계산 (결합 A 입력)."""
    path = results_path or os.path.join(RESULTS_DIR, "experiment_results.json")
    if not os.path.exists(path):
        return None, {"source": None, "note": "센서 실험 결과 없음 — 결합 A 미적용"}
    with open(path, encoding="utf-8") as f:
        res = json.load(f)
    sc = res["scenarios"][scenario]
    exact = next(b for b in sc["baselines"] if b["method"].startswith("Exact"))
    x = exact["x"]
    a = dl.load_fractional_coverage(candidates, scenario)
    cover = {}
    for z in sorted(zones.keys()):
        miss = 1.0
        for j, xi in enumerate(x):
            if xi and a[z][j] > 0:
                miss *= (1.0 - a[z][j])
        cover[z] = round(1.0 - miss, 4)
    return cover, {
        "source": "results/experiment_results.json (센서 QUBO Exact 최적해)",
        "scenario": scenario, "sensor_x": x,
        "note": "커버율 = 1 − Π(1 − a_zj x_j), 부분면적 커버리지 v1 기준",
    }


def apply_coupling_A(risk, cover, kappa=KAPPA_UNOBSERVED):
    """결합 A: 센서로 관측되지 않는 구역일수록 위험을 보수적으로 상향.

    r_z_eff = r_z × (1 + κ·(1 − cover_z))
    커버율 1.0이면 그대로, 0이면 최대 +κ. 정규화는 다시 하지 않는다(해석 유지).
    """
    if not cover:
        return dict(risk), {"applied": False}
    eff = {z: round(risk[z] * (1.0 + kappa * (1.0 - cover.get(z, 0.0))), 4) for z in risk}
    return eff, {
        "applied": True, "kappa": kappa,
        "formula": "r_eff = r × (1 + κ(1 − 커버율))",
        "rationale": "센서가 보지 못하는 구역은 위험 관측 신뢰도가 낮으므로 대피 계산에서 보수적으로 취급",
        "uplift": {z: round(eff[z] / risk[z], 3) for z in risk},
    }


def domain_baselines(graph, variables, w_edge, evidence):
    """도메인 베이스라인 2종 — 고전 최단경로 방식 (그룹별 독립 선택)."""
    v_free = evidence["constants"]["free_speed_ms"]
    out = []
    for name, key in (("독립 최단경로(Dijkstra 대응)", "len"),
                      ("위험가중 최단경로", "risk")):
        x = [0] * 12
        for gi in sorted({v["w"] for v in variables}):
            cands = [v for v in variables if v["w"] == gi]
            if key == "len":
                best = min(cands, key=lambda v: v["len_m"])
            else:
                def score(v):
                    t = v["len_m"] / v_free
                    r = sum(w_edge[e] * graph["edges"][e]["length_m"] / v_free for e in v["edges"])
                    return t + r
                best = min(cands, key=score)
            x[best["index"]] = 1
        out.append({"method": name, "x": x})
    return out


def crossover_sweep(graph, risk, weather, evidence, totals=(24, 60, 120, 200, 320, 480)):
    """인원 규모 스윕 — 혼잡 이차항이 언제 고전 최단경로 분해를 깨는지(교차점) 탐색.

    근거: 혼잡항은 n_w·n_w'로 이차 증가하고 이동시간은 n_w로 선형 증가하므로, 인원이 늘면
    반드시 어느 지점에서 결합이 지배적이 된다. 인원 규모의 산업적 맥락은 D6-WF-001(4,200명)·
    D6-WF-002(6,000명) 공개값이지만, 아래 값은 '한 대피 섹터'의 합성 가정치다(실측 아님).
    """
    w_edge = edge_risks(graph["nodes"], risk, graph["edges"], weather=weather,
                        source_zone=SOURCE_ZONE)
    rows = []
    for total in totals:
        variables, _ = build_variables(graph, make_groups(total), k=K_ROUTES)
        Q, const, notes = build_qubo(graph, variables, w_edge, evidence=evidence)
        ex = solve_exact(Q, const)
        indep = domain_baselines(graph, variables, w_edge, evidence)[0]
        x = np.array(indep["x"], float)
        e_indep = float(x @ np.triu(Q) @ x + const)
        tm_ex = true_metrics(graph, variables, w_edge, ex["x"], evidence)
        tm_in = true_metrics(graph, variables, w_edge, indep["x"], evidence)
        rows.append({
            "total_workers": total, "per_group": total // 4,
            "exact_energy": round(ex["energy"], 2),
            "independent_shortest_energy": round(e_indep, 2),
            "gap_person_s": round(e_indep - ex["energy"], 2),
            "independent_is_optimal": bool(abs(e_indep - ex["energy"]) < 1e-6),
            "mean_congestion_person_s": notes["mean_congestion_person_s"],
            "mean_time_person_s": notes["mean_time_person_s"],
            "exact_makespan_s": tm_ex["makespan_s"],
            "independent_makespan_s": tm_in["makespan_s"],
            "exact_routes": {g: v["path"] for g, v in tm_ex["groups"].items()},
        })
    first = next((r["total_workers"] for r in rows if not r["independent_is_optimal"]), None)
    return {
        "rows": rows,
        "crossover_total_workers": first,
        "interpretation": (
            "혼잡 이차항은 인원 제곱으로 커지므로 임계 인원 이상에서 '작업조별 독립 최단경로'가 "
            "전체 최적이 아니게 된다. 이 결합 구조가 QUBO/QAOA 적용의 정당한 근거이며, "
            "임계 이하 규모에서는 고전 최단경로로 충분하다는 점도 함께 보고한다."
            if first else
            "본 합성 레이아웃에서는 시험한 인원 범위에서 독립 최단경로가 계속 최적이었다. "
            "대체 경로가 지나치게 길어 혼잡 비용을 상쇄하지 못하기 때문이며, 과장 없이 그대로 보고한다."),
        "basis": "D6-WF-001/002는 현장 전체 인원 공개값(산업적 맥락)이고, 여기 값은 섹터 단위 합성 가정치다.",
    }


def run_case(label, zones, graph, risk, weather, variables, evidence, coupling_meta):
    w_edge = edge_risks(graph["nodes"], risk, graph["edges"], weather=weather, source_zone=SOURCE_ZONE)
    Q, const, notes = build_qubo(graph, variables, w_edge, evidence=evidence)
    E, _ = all_energies(Q, const)

    # SA 온도는 에너지 스케일에 맞춘다 (센서 QUBO와 에너지 단위가 달라 기본값이 과소)
    T0 = max(float(np.std(E)), 1.0)
    sols = [solve_exact(Q, const), solve_greedy(Q, const),
            solve_sa(Q, const, T0=T0, T1=T0 / 500.0), solve_random(Q, const)]
    e_opt = sols[0]["energy"]

    for s in domain_baselines(graph, variables, w_edge, evidence):
        x = np.array(s["x"], float)
        s["energy"] = float(x @ np.triu(Q) @ x + const)
        s["time_s"] = 0.0
        sols.append(s)

    for s in sols:
        s["true_metrics"] = true_metrics(graph, variables, w_edge, s["x"], evidence)
        s["gap_to_exact"] = round(s["energy"] - e_opt, 6)
        s["time_s"] = round(s["time_s"], 4)
        sel, _ = decode(variables, s["x"])
        s["routes"] = {variables[[v["index"] for v in variables if v["w"] == gi][0]]["group"]:
                       ("→".join(c[0]["path"]) if len(c) == 1 else "invalid")
                       for gi, c in sel.items()}

    qaoa = []
    for p in (1, 2):
        q = run_qaoa(E, p=p, shots=2048)
        q["best_sampled_true_metrics"] = true_metrics(graph, variables, w_edge,
                                                      q["best_sampled_x"], evidence)
        q["best_sampled_gap_to_exact"] = round(q["best_sampled_energy"] - e_opt, 6)
        q["time_s"] = round(q["time_s"], 2)
        qaoa.append(q)

    # 혼잡 이차항 지배 여부 — '독립 최단경로 ≠ 전체 최적'이 실제로 발생하는지 확인
    ex, indep = sols[0], next(s for s in sols if s["method"].startswith("독립"))
    analysis = {
        "independent_shortest_is_optimal": bool(abs(indep["energy"] - ex["energy"]) < 1e-6),
        "independent_gap_person_s": round(indep["energy"] - ex["energy"], 2),
        "mean_congestion_person_s": notes["mean_congestion_person_s"],
        "max_congestion_person_s": notes["max_congestion_person_s"],
        "mean_time_person_s": notes["mean_time_person_s"],
        "note": ("혼잡 이차항 크기가 이동시간 대비 작으면 독립 최단경로가 그대로 최적이 된다. "
                 "인원이 늘어 이차항이 커지면 결합이 생겨 고전 최단경로 분해가 깨진다 — "
                 "이 교차점이 양자 최적화 적용의 정당한 근거다."),
    }

    return {
        "label": label,
        "weather": weather,
        "coupling": coupling_meta,
        "congestion_analysis": analysis,
        "risk_scores": {k: round(v, 4) for k, v in risk.items()},
        "edge_risks": {f"{u}-{v}": round(val, 4) for (u, v), val in sorted(w_edge.items())},
        "qubo_notes": notes,
        "energy_stats": {"min": float(E.min()), "max": float(E.max()),
                         "mean": round(float(E.mean()), 3)},
        "baselines": sols,
        "qaoa": qaoa,
    }


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    evidence = load_evidence()
    zones = dl.load_zones()
    candidates = dl.load_candidates()
    incidents = dl.load_incidents()
    weather = weather_kma.representative_weather()  # 시계열 대표값 우선 (2026-07-27)

    graph = build_graph(zones, evidence)
    cover, cover_meta = sensor_coverage_fraction(zones, candidates)
    risk_base = zone_risk_scores(zones, incidents, weather=weather, source_zone=SOURCE_ZONE)
    risk_A, meta_A0 = apply_coupling_A(risk_base, cover)

    cases = []
    routes = None
    for ws in WORKER_SCENARIOS:
        groups = make_groups(ws["total"])
        variables, routes = build_variables(graph, groups, k=K_ROUTES)

        # (1) 기준: 실측 기상 + 결합 A 미적용 (센서 정보 없이 대피만 최적화)
        cases.append(run_case(f"[{ws['name']}] 기준(센서 결합 없음)", zones, graph, risk_base,
                              weather, variables, evidence,
                              {"applied": False, "note": "위험 관측 신뢰도 균일 가정",
                               "worker_scenario": ws, "groups": groups}))

        # (2) 결합 A: 센서 커버리지로 미관측 구역 보수적 상향
        meta_A = dict(meta_A0)
        meta_A.update(cover_meta)
        meta_A["coverage"] = cover
        meta_A["worker_scenario"] = ws
        meta_A["groups"] = groups
        cases.append(run_case(f"[{ws['name']}] 결합 A(센서 커버리지 반영)", zones, graph, risk_A,
                              weather, variables, evidence, meta_A))

    # 기상 민감도는 중형 데모(마지막 variables 아님) 기준으로 고정
    variables, _ = build_variables(graph, make_groups(WORKER_SCENARIOS[0]["total"]), k=K_ROUTES)

    # (3) 기상 민감도: 무풍 / 강풍 4방위 (풍향 방향성 모델 검증)
    sens = []
    for label, w in [("무풍(하위호환 검증)", None),
                     ("강풍 북풍 10 m/s", {"wd_deg": 0.0, "ws_ms": 10.0}),
                     ("강풍 동풍 10 m/s", {"wd_deg": 90.0, "ws_ms": 10.0}),
                     ("강풍 남풍 10 m/s", {"wd_deg": 180.0, "ws_ms": 10.0}),
                     ("강풍 서풍 10 m/s", {"wd_deg": 270.0, "ws_ms": 10.0})]:
        r = zone_risk_scores(zones, incidents, weather=w, source_zone=SOURCE_ZONE)
        rA, _ = apply_coupling_A(r, cover)
        w_edge = edge_risks(graph["nodes"], rA, graph["edges"], weather=w, source_zone=SOURCE_ZONE)
        Q, const, _ = build_qubo(graph, variables, w_edge, evidence=evidence)
        ex = solve_exact(Q, const)
        tm = true_metrics(graph, variables, w_edge, ex["x"], evidence)
        sens.append({
            "weather": label, "params": w,
            "risk_scores": {k: round(v, 4) for k, v in r.items()},
            "optimal_routes": {g: v["path"] for g, v in tm["groups"].items()},
            "makespan_s": tm["makespan_s"], "risk_exposure": tm["risk_exposure"],
            "total_person_seconds": tm["total_person_seconds"],
        })

    out = {
        "meta": {
            "problem": "반도체 건설현장 대피 경로 최적화 (QUBO, 변수 12 = 작업조 4 × 후보경로 3)",
            "part": "파트 2-B (워크플로우_파트1_위험인자.md), 결합 A",
            "source_zone": SOURCE_ZONE,
            "group_origins": [{"id": g, "origin": o, "desc": d} for g, o, d in GROUP_ORIGINS],
            "worker_scenarios": WORKER_SCENARIOS,
            "scenario_basis": ("D6-SYN-002(24명)·D6-SYN-003(60명) 합성 시나리오를 4개 작업조로 "
                               "균등 분할 — 실제 구역별 동시인원 실측 아님"),
            "weather_observed": weather,
            "graph_meta": graph["meta"],
            "evidence_constants": evidence["constants"],
            "evidence_sources": evidence["sources"],
            "evidence_meta": evidence["meta"],
            "gas_reference": evidence["gas"],
            "route_candidates": {g: [{"path": p, "len_m": round(sum(
                graph["edges"][tuple(sorted((p[i], p[i + 1])))]["length_m"]
                for i in range(len(p) - 1)), 2)} for p in ps] for g, ps in routes.items()},
            "limitations": [
                "구역·작업자 배치는 합성 데이터이며 실제 현장 측정치가 아니다.",
                "EX2 비상구는 D1-LAW-005(출구 2개소 이상) 충족을 위한 합성 노드다.",
                "간선장은 구역 중심 간 직선거리 근사이며 실제 통행 경로장이 아니다.",
                "혼잡은 이차항 1차 근사이며 시간 전개형 인파 시뮬레이션·CFD가 아니다.",
                "풍향 보정은 코사인 방향 가중 근사이며 확산 해석이 아니다.",
            ],
        },
        "cases": cases,
        "weather_sensitivity": sens,
        "congestion_crossover": crossover_sweep(graph, risk_A, weather, evidence),
    }

    path = os.path.join(RESULTS_DIR, "evacuation_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("저장:", path)
    write_summary(out)


def write_summary(out):
    L = []
    L.append("# 대피 경로 QUBO 실험 결과 요약 (파트 2-B + 결합 A)\n")
    m = out["meta"]
    L.append(f"- 문제: {m['problem']}")
    L.append(f"- 누출·발화 가정 지점: {m['source_zone']} (특수가스 캐비닛·VMB)")
    L.append(f"- 작업자 시나리오: {m['scenario_basis']}")
    L.append(f"- 관측 기상: {m['weather_observed']}")
    L.append(f"- 근거 상수: 보행속도 {m['evidence_constants']['free_speed_ms']} m/s, "
             f"보행거리 상한 {m['evidence_constants']['walk_distance_limit_m']} m, "
             f"단위폭 유동률 {m['evidence_constants']['max_specific_flow']} persons/(m·s)\n")

    for case in out["cases"]:
        L.append(f"\n## {case['label']}\n")
        L.append("| 방법 | 에너지 | Exact 대비 | 대피시간(makespan, s) | 총 인·초 | 위험노출 | 유효 |")
        L.append("|---|---|---|---|---|---|---|")
        for b in case["baselines"]:
            tm = b["true_metrics"]
            if tm.get("valid"):
                L.append(f"| {b['method']} | {b['energy']:.2f} | {b['gap_to_exact']:.2f} | "
                         f"{tm['makespan_s']} | {tm['total_person_seconds']} | "
                         f"{tm['risk_exposure']} | O |")
            else:
                L.append(f"| {b['method']} | {b['energy']:.2f} | {b['gap_to_exact']:.2f} | - | - | - | X(one-hot 위반) |")
        for q in case["qaoa"]:
            tm = q["best_sampled_true_metrics"]
            ok = "O" if tm.get("valid") else "X"
            L.append(f"| QAOA p={q['p']} (최빈 샘플) | {q['best_sampled_energy']:.2f} | "
                     f"{q['best_sampled_gap_to_exact']:.2f} | "
                     f"{tm.get('makespan_s', '-')} | {tm.get('total_person_seconds', '-')} | "
                     f"{tm.get('risk_exposure', '-')} | {ok} |")
        L.append("")
        for q in case["qaoa"]:
            L.append(f"- QAOA p={q['p']}: 근사비 {q['approx_ratio']}, 최적해 확률 {q['prob_optimal']} "
                     f"(균등 대비 {q['prob_optimal_vs_uniform']}배), 최적해 샘플 포함 "
                     f"{'예' if q.get('sampled_optimal_found') else '아니오'}")
        ex = case["baselines"][0]
        L.append(f"- Exact 최적 경로: {ex['routes']}")
        ca = case["congestion_analysis"]
        L.append(f"- 혼잡 이차항: 평균 {ca['mean_congestion_person_s']} 인·초 / 최대 "
                 f"{ca['max_congestion_person_s']} 인·초 (선형 이동시간 평균 "
                 f"{ca['mean_time_person_s']} 인·초 대비)")
        if ca["independent_shortest_is_optimal"]:
            L.append("- 독립 최단경로 = 전체 최적 (이 규모에서는 혼잡항이 지배적이지 않음 — 과장 금지)")
        else:
            L.append(f"- **독립 최단경로 ≠ 전체 최적** (고전 분해 대비 +{ca['independent_gap_person_s']} 인·초 손해) "
                     "→ 혼잡 이차항 결합이 실제로 작동하는 구간")

    co = out.get("congestion_crossover")
    if co:
        L.append("\n## 혼잡 이차항 교차점 분석 (양자 최적화 정당성)\n")
        L.append("| 총 인원(합성) | 조당 | Exact 에너지 | 독립 최단경로 | 차이(인·초) | 독립=최적? |")
        L.append("|---|---|---|---|---|---|")
        for r in co["rows"]:
            L.append(f"| {r['total_workers']} | {r['per_group']} | {r['exact_energy']} | "
                     f"{r['independent_shortest_energy']} | {r['gap_person_s']} | "
                     f"{'예' if r['independent_is_optimal'] else '**아니오**'} |")
        cx = co["crossover_total_workers"]
        L.append(f"\n- 교차점: {'총 ' + str(cx) + '명 구간부터 독립 최단경로가 최적이 아님' if cx else '시험 범위에서 교차점 없음'}")
        L.append(f"- 해석: {co['interpretation']}")
        L.append(f"- 근거: {co['basis']}")

    L.append("\n## 기상 민감도 (풍향 방향성 모델 검증)\n")
    L.append("| 기상 | makespan(s) | 위험노출 | 최적 경로 요약 |")
    L.append("|---|---|---|---|")
    for s in out["weather_sensitivity"]:
        routes = "; ".join(f"{k}:{v}" for k, v in s["optimal_routes"].items())
        L.append(f"| {s['weather']} | {s['makespan_s']} | {s['risk_exposure']} | {routes} |")

    L.append("\n## 한계 (발표 시 반드시 명시)\n")
    for lim in m["limitations"]:
        L.append(f"- {lim}")
    L.append("- 본 결과는 '양자 이득' 주장을 하지 않는다. QAOA는 Ideal 시뮬레이터 기준 근사비·"
             "최적해 확률로만 해석하며, 실기 QPU 결과는 노이즈·회로 깊이 오류 분석 프레임으로 다룬다.")

    path = os.path.join(RESULTS_DIR, "대피실험_요약.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("저장:", path)


if __name__ == "__main__":
    main()
