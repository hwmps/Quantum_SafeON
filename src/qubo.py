# -*- coding: utf-8 -*-
"""QUBO 정식화 — 센서 배치 12변수

min f(x) = -Σ_j R_j x_j                       (위험 가중 커버리지 보상)
         + w_cost Σ_j c_j x_j                 (설치 비용, 장비가 정규화)
         + Σ_{j<k} O_jk x_j x_k               (중복 커버 패널티 = 이중 계상 보정)
         + λK (Σ_j x_j - K)^2                 (센서 수 제한, soft)
         + λH Σ_{z∈hard} Π_{j∈cov(z)} (1-x_j) (법적 필수 커버 구역, hard)

- R_j = Σ_z r_z a_zj, O_jk = Σ_z r_z a_zj a_zk 로 두면
  -ΣR x + ΣO xx = -Σ_z r_z·(union 커버) 가 커버 후보 2개 이하 구역에서 정확히 성립.
- hard 항은 cov(z) 크기가 1~2이면 정확히 이차식으로 전개, 3 이상이면 이차 절단 근사(주석 기록).
"""
import itertools

import numpy as np

N = 12


def build_qubo(zones, candidates, a, risk, costs_raw, hard_zones,
               K=6, w_cost=0.35, lam_K=None, lam_H=3.0, hard_tau=0.3):
    """반환: Q (N×N 상삼각 numpy), const, 메모 dict

    hard_tau: hard 제약 엄격 기준 — 부분면적 커버율 a_zj >= hard_tau 인 센서만
    법적 필수 구역의 유효 커버 후보로 인정 (PM 확정 2026-07-26: 0.3).
    """
    zids = sorted(zones.keys())
    Q = np.zeros((N, N))
    const = 0.0
    notes = {"K": K, "w_cost": w_cost, "lam_H": lam_H, "hard_zones": hard_zones,
             "hard_tau": hard_tau}

    # 1) 커버리지 보상 + 중복 패널티 (a는 이진 0/1 또는 부분면적 실수 0~1 모두 지원)
    for z in zids:
        r = risk[z]
        cov = [j for j in range(N) if a[z][j] > 0]
        for j in cov:
            Q[j, j] -= r * a[z][j]
        for j, k in itertools.combinations(cov, 2):
            Q[j, k] += r * a[z][j] * a[z][k]

    # 2) 비용 (최대 후보 비용으로 정규화)
    cmax = max(costs_raw) or 1.0
    for j in range(N):
        Q[j, j] += w_cost * costs_raw[j] / cmax

    # 3) 센서 수 제한 (Σx-K)^2 = Σx + 2Σ_{j<k}x_j x_k - 2KΣx + K^2
    if lam_K is None:
        lam_K = float(np.abs(np.diag(Q)).max()) * 2.0  # 선형계수 최대의 2배 (관행적 스케일)
    notes["lam_K"] = lam_K
    for j in range(N):
        Q[j, j] += lam_K * (1.0 - 2.0 * K)
    for j, k in itertools.combinations(range(N), 2):
        Q[j, k] += 2.0 * lam_K
    const += lam_K * K * K

    # 4) 법적 필수 커버 구역 (hard) — Π(1-x_j) 전개
    #    엄격 기준: 커버율 >= hard_tau 인 센서만 유효 후보로 인정.
    #    예외: 단일 센서로 tau 도달 불가한 구역(예: low 시나리오 Z10)은 커버율>0 후보 전체로
    #    완화하여 union 커버를 유도하고 relaxed 목록에 기록 (발표 시 한계로 명시).
    truncated, relaxed = [], []
    for z in hard_zones:
        cov = [j for j in range(N) if a[z][j] >= hard_tau]
        if not cov:
            cov = [j for j in range(N) if a[z][j] > 0]
            if not cov:
                continue
            relaxed.append(z)
        if len(cov) == 1:
            const += lam_H
            Q[cov[0], cov[0]] -= lam_H
        elif len(cov) == 2:
            j, k = cov
            const += lam_H
            Q[j, j] -= lam_H
            Q[k, k] -= lam_H
            Q[j, k] += lam_H
        else:  # 3개 이상 → 이차 절단 (상위항 무시, 패널티 과대 방지 위해 페어 절반만)
            truncated.append(z)
            const += lam_H
            for j in cov:
                Q[j, j] -= lam_H / len(cov) * 2.0
            for j, k in itertools.combinations(cov, 2):
                Q[j, k] += lam_H / len(cov)
    notes["hard_truncated_zones"] = truncated
    notes["hard_relaxed_zones"] = relaxed  # 단일 센서 tau 미달로 완화 적용된 구역
    return Q, const, notes


def energy(Q, const, x):
    x = np.asarray(x, dtype=float)
    return float(x @ np.triu(Q) @ x + const)


def all_energies(Q, const):
    """12큐비트 전수 에너지 벡터 (4096,) — Exact/QAOA 공용."""
    xs = ((np.arange(2 ** N)[:, None] >> np.arange(N)) & 1).astype(float)  # bit j = x_j
    Qu = np.triu(Q)
    return np.einsum("bi,ij,bj->b", xs, Qu, xs) + const, xs


def true_metrics(zones, a, risk, costs_raw, hard_zones, x, hard_tau=0.3):
    """QUBO 근사가 아닌 실제 지표: union 커버리지, 비용, hard 충족.

    a가 부분면적(0~1)이면 구역별 union 커버율 = 1 - Π_j(1 - a_zj x_j).
    a가 이진이면 기존 boolean union과 동일한 값이 된다.
    hard 충족 기준(엄격, PM 확정 2026-07-26): 구역 union 커버율 >= hard_tau(0.3).
    """
    zids = sorted(zones.keys())
    cover_frac = {}
    for z in zids:
        miss = 1.0
        for j in range(N):
            if x[j] and a[z][j] > 0:
                miss *= (1.0 - a[z][j])
        cover_frac[z] = 1.0 - miss
    weighted_cov = sum(risk[z] * cover_frac[z] for z in zids) / sum(risk.values())
    cost = sum(costs_raw[j] for j in range(N) if x[j])
    hard_ok = all(cover_frac[z] >= hard_tau for z in hard_zones)
    return {
        "n_sensors": int(sum(x)),
        "weighted_coverage": round(weighted_cov, 4),
        "zones_covered": sum(1 for z in zids if cover_frac[z] > 0),
        "total_cost_krw": int(cost),
        "hard_constraints_ok": hard_ok,
    }
