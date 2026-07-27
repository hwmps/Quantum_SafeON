# -*- coding: utf-8 -*-
"""대피 경로 선택 QUBO (파트 2-B) — 변수 12개 (작업자 그룹 4 × 후보 경로 3)

min f(y) = Σ_{w,p} y_{w,p} [ T_{w,p} + λ_R·R_{w,p} + λ_D·V_{w,p} ]        (선형)
         + κ Σ_{(w,p)≠(w',p')} S_{(w,p),(w',p')} y_{w,p} y_{w',p'}        (혼잡 이차항)
         + λ_1 Σ_w ( Σ_p y_{w,p} − 1 )²                                    (그룹당 경로 1개)

단위는 모두 **인·초(person-seconds)** 로 통일한다.
- T   = n_w × (경로장 / 자유류 보행속도)                     ← D2-FLOW-001 (1.19 m/s)
- R   = n_w × Σ_e w_e × (간선장 / 보행속도)   (위험 노출)     ← w_e = risk_model.edge_risks
- V   = 법정 보행거리 상한 초과분 비율                        ← D1-LAW-001 (30 m)
- S   = Σ_{공유 간선 e} (n_w × n_w') / c_e                    ← D2-FLOW-004 용량 c_e[persons/s]

★ 혼잡 이차항 S가 이 문제의 양자 최적화 정당성이다: 각 작업자 그룹이 독립적으로
  최단·최저위험 경로를 고르면(고전 Dijkstra) 공유 통로가 겹쳐 전체 최적이 아니게 된다.
  결합(coupling)이 있는 이차 비용은 그래프 최단경로로 분해되지 않는다.

한계: 시간 전개(큐 형성·역류)를 이차항 1차 근사로 대체했고, 밀도-속도 관계는 정확 평가
(true_metrics)에서만 사용한다. CFD·인파 시뮬레이터가 아니다.
"""
import itertools

import numpy as np

from evacuation_evidence import load_evidence, speed_at_density
from zone_graph import path_edges, path_length

N = 12  # 센서 QUBO와 동일한 변수 수 (baselines.py / qaoa_sim.py 그대로 재사용)


def build_variables(graph, groups, k=3):
    """groups: [{"id","origin","n"}] → 변수 리스트 [{"w","p","group","path","edges","len_m"}]"""
    from zone_graph import k_shortest_routes
    variables, routes_by_group = [], {}
    for gi, g in enumerate(groups):
        routes = k_shortest_routes(graph, g["origin"], k=k)
        if len(routes) < k:
            raise ValueError(f"{g['origin']}: 후보 경로 {len(routes)}개 (<{k}) — 그래프 확인 필요")
        routes_by_group[g["id"]] = routes
        for pi, path in enumerate(routes):
            variables.append({
                "index": len(variables), "w": gi, "p": pi, "group": g["id"],
                "origin": g["origin"], "n": g["n"], "path": path,
                "edges": path_edges(path), "len_m": round(path_length(graph, path), 2),
                "exit": path[-1],
            })
    if len(variables) != N:
        raise ValueError(f"변수 수 {len(variables)} ≠ {N}")
    return variables, routes_by_group


def build_qubo(graph, variables, w_edge, lam_risk=1.0, kappa=1.0, lam_dist=None,
               lam_one=None, evidence=None, balance_risk=True):
    """반환: Q(12×12 상삼각), const, notes

    balance_risk=True이면 λ_R를 '시간항과 위험항의 평균 크기가 같아지는 값 × lam_risk'로
    자동 보정한다. 위험 점수 r_z가 [0.1,1.0] 정규화 값이라 원단위 비교가 불가능하기 때문이며,
    이 경우 lam_risk=1.0은 "안전(위험노출) 대 신속(대피시간) 동일 비중"을 의미한다.
    """
    ev = evidence or load_evidence()
    c = ev["constants"]
    v_free = c["free_speed_ms"]
    limit = c["walk_distance_limit_m"]

    Q = np.zeros((N, N))
    const = 0.0
    lin = np.zeros(N)
    viol = {}

    # 1) 선형항: 이동시간 + 위험노출 + 법정 보행거리 초과 벌점
    T, R = {}, {}
    for v in variables:
        T[v["index"]] = v["n"] * v["len_m"] / v_free
        R[v["index"]] = v["n"] * sum(
            w_edge[e] * graph["edges"][e]["length_m"] / v_free for e in v["edges"])
        viol[v["index"]] = round(max(v["len_m"] - limit, 0.0) / limit, 4)

    lam_risk_eff = lam_risk
    if balance_risk:
        mt = float(np.mean(list(T.values())))
        mr = float(np.mean(list(R.values()))) or 1.0
        lam_risk_eff = lam_risk * mt / mr

    for v in variables:
        j = v["index"]
        lin[j] = T[j] + lam_risk_eff * R[j]
        Q[j, j] += lin[j]

    # λ_D: 법정 상한 초과 벌점 스케일 — 선형항 최대치와 같은 크기로 두어 초과 경로를 억제
    if lam_dist is None:
        lam_dist = float(lin.max())
    for v in variables:
        Q[v["index"], v["index"]] += lam_dist * viol[v["index"]]

    # 2) 혼잡 이차항: 서로 다른 그룹의 두 경로가 간선을 공유하면 큐잉 지연 (인·초)
    shared_detail = {}
    for v1, v2 in itertools.combinations(variables, 2):
        if v1["w"] == v2["w"]:
            continue
        common = set(v1["edges"]) & set(v2["edges"])
        if not common:
            continue
        s = 0.0
        for e in common:
            cap = graph["edges"][e]["capacity_pps"]
            s += (v1["n"] * v2["n"]) / max(cap, 1e-6)
        Q[v1["index"], v2["index"]] += kappa * s
        shared_detail[f"{v1['index']}-{v2['index']}"] = {
            "edges": [f"{a}-{b}" for a, b in sorted(common)], "cost_person_s": round(s, 2)}

    # 3) 그룹당 경로 정확히 1개: λ_1 (Σ_p y − 1)²
    if lam_one is None:
        lam_one = 2.0 * float(np.abs(np.diag(Q)).max())
    for gi in {v["w"] for v in variables}:
        idx = [v["index"] for v in variables if v["w"] == gi]
        for j in idx:
            Q[j, j] += lam_one * (1.0 - 2.0)     # x_j² - 2x_j
        for j, k2 in itertools.combinations(idx, 2):
            Q[j, k2] += 2.0 * lam_one
        const += lam_one

    notes = {
        "unit": "person-seconds (인·초)",
        "free_speed_ms": v_free,
        "walk_distance_limit_m": limit,
        "lam_risk": lam_risk, "lam_risk_effective": round(lam_risk_eff, 4),
        "lam_risk_balanced": balance_risk, "kappa": kappa,
        "mean_time_person_s": round(float(np.mean(list(T.values()))), 2),
        "mean_risk_term_person_s": round(float(np.mean(list(R.values()))), 2),
        "mean_congestion_person_s": round(
            float(np.mean([d["cost_person_s"] for d in shared_detail.values()]))
            if shared_detail else 0.0, 2),
        "max_congestion_person_s": round(
            max((d["cost_person_s"] for d in shared_detail.values()), default=0.0), 2),
        "lam_dist": round(lam_dist, 3), "lam_one": round(lam_one, 3),
        "distance_violation_ratio": viol,
        "congestion_pairs": shared_detail,
        "evidence": {
            "T": "D2-FLOW-001 자유류 보행속도 1.19 m/s (NIST TN 1471)",
            "S": "D2-FLOW-004 최대 단위폭 유동률 1.3 persons/(m·s) × 유효폭(D2-FLOW-005)",
            "V": "D1-LAW-001 건축법 시행령 제34조제1항 보행거리 30 m",
        },
    }
    return Q, const, notes


def decode(variables, x):
    """해 벡터 → 그룹별 선택 경로. one-hot 위반 여부도 반환."""
    sel, invalid = {}, []
    for gi in sorted({v["w"] for v in variables}):
        chosen = [v for v in variables if v["w"] == gi and x[v["index"]] == 1]
        if len(chosen) != 1:
            invalid.append(variables[[v["index"] for v in variables if v["w"] == gi][0]]["group"])
        sel[gi] = chosen
    return sel, invalid


def true_metrics(graph, variables, w_edge, x, evidence=None):
    """QUBO 근사가 아닌 실제 지표 — 밀도-속도 관계(D2-FLOW-002/003)로 재계산.

    각 간선의 동시 이용 인원으로 밀도 D = n_e / (길이×유효폭)을 구하고 S(D)=1.4−0.37D로
    감속시킨 뒤 그룹별 대피시간을 계산한다(정의역 밖은 절단, 외삽 금지).
    """
    ev = evidence or load_evidence()
    c = ev["constants"]
    limit = c["walk_distance_limit_m"]
    sel, invalid = decode(variables, x)
    if invalid:
        return {"valid": False, "one_hot_violation": invalid}

    chosen = [v[0] for v in sel.values()]
    load = {}
    for v in chosen:
        for e in v["edges"]:
            load[e] = load.get(e, 0) + v["n"]

    edge_speed, over_cap = {}, []
    for e, n_e in load.items():
        info = graph["edges"][e]
        area = info["length_m"] * info["eff_width_m"]
        dens = n_e / area if area > 0 else 0.0
        edge_speed[e] = speed_at_density(dens, c)
        if n_e / max(info["length_m"] / c["free_speed_ms"], 1e-6) > info["capacity_pps"]:
            over_cap.append(f"{e[0]}-{e[1]}")

    total_ps, worst, exposure = 0.0, 0.0, 0.0
    per_group = {}
    for v in chosen:
        t = sum(graph["edges"][e]["length_m"] / edge_speed[e] for e in v["edges"])
        r = sum(w_edge[e] * graph["edges"][e]["length_m"] / edge_speed[e] for e in v["edges"])
        per_group[v["group"]] = {
            "path": "→".join(v["path"]), "len_m": v["len_m"],
            "time_s": round(t, 1), "risk_exposure": round(r, 3), "n": v["n"],
            "exit": v["exit"],
            "distance_ok": v["len_m"] <= limit,
        }
        total_ps += v["n"] * t
        exposure += v["n"] * r
        worst = max(worst, t)

    return {
        "valid": True,
        "total_person_seconds": round(total_ps, 1),
        "makespan_s": round(worst, 1),
        "risk_exposure": round(exposure, 2),
        "shared_edges": sum(1 for e, n in load.items() if n > min(v["n"] for v in chosen)),
        "over_capacity_edges": sorted(set(over_cap)),
        "distance_limit_ok": all(g["distance_ok"] for g in per_group.values()),
        "groups": per_group,
    }
