# -*- coding: utf-8 -*-
"""QAOA Ideal Simulator (numpy statevector, 12큐비트=4096 진폭)

- 워크플로우 Phase 3-1: Qiskit 미설치 환경 대비 자체 statevector 구현.
  대각 해밀토니안(QUBO 에너지 벡터)에 대한 QAOA는 phase 회전 + X-mixer로 정확히 시뮬레이션 가능.
- 로컬 결과는 Qiskit/Braket 구현과 수학적으로 동일 (검증용). 실기 QPU 제출용 Qiskit 회로는
  qaoa_qiskit.py 참고 (qiskit 설치 후 사용).
- 최적화: p=1은 격자 탐색 + 국소 정련, p=2는 p=1 해를 초기값으로 Nelder-Mead(자체 구현).
"""
import time

import numpy as np

from qubo import N


def _mixer_apply(psi, beta):
    """e^{-iβX}를 각 큐비트에 적용. psi shape (2^N,)"""
    c, s = np.cos(beta), -1j * np.sin(beta)
    psi = psi.reshape([2] * N)
    for q in range(N):
        psi0 = np.take(psi, 0, axis=q)
        psi1 = np.take(psi, 1, axis=q)
        new0 = c * psi0 + s * psi1
        new1 = s * psi0 + c * psi1
        psi = np.stack([new0, new1], axis=q)
    return psi.reshape(-1)


def qaoa_state(E, gammas, betas):
    """E: (4096,) 스케일된 에너지 벡터. 반환 |ψ(γ,β)>"""
    psi = np.full(2 ** N, 1.0 / np.sqrt(2 ** N), dtype=complex)
    for g, b in zip(gammas, betas):
        psi = np.exp(-1j * g * E) * psi
        psi = _mixer_apply(psi, b)
    return psi


def expectation(E, params, p):
    psi = qaoa_state(E, params[:p], params[p:])
    return float(np.real(np.vdot(psi, E * psi)))


def _nelder_mead(f, x0, steps=200, alpha=1.0, gamma_c=2.0, rho=0.5, sigma=0.5, init_step=0.15):
    """의존성 없는 소형 Nelder-Mead."""
    n = len(x0)
    simplex = [np.array(x0, dtype=float)]
    for i in range(n):
        v = np.array(x0, dtype=float)
        v[i] += init_step
        simplex.append(v)
    fv = [f(v) for v in simplex]
    for _ in range(steps):
        order = np.argsort(fv)
        simplex = [simplex[i] for i in order]
        fv = [fv[i] for i in order]
        centroid = np.mean(simplex[:-1], axis=0)
        xr = centroid + alpha * (centroid - simplex[-1])
        fr = f(xr)
        if fr < fv[0]:
            xe = centroid + gamma_c * (xr - centroid)
            fe = f(xe)
            simplex[-1], fv[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fv[-2]:
            simplex[-1], fv[-1] = xr, fr
        else:
            xc = centroid + rho * (simplex[-1] - centroid)
            fc = f(xc)
            if fc < fv[-1]:
                simplex[-1], fv[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    simplex[i] = simplex[0] + sigma * (simplex[i] - simplex[0])
                    fv[i] = f(simplex[i])
    i = int(np.argmin(fv))
    return simplex[i], fv[i]


def run_qaoa(E_raw, p=1, shots=2048, seed=42):
    """반환: dict(최적 파라미터, 근사비, 최적해 확률, 샘플 최빈해 등)"""
    t0 = time.perf_counter()
    # 에너지 스케일 정규화 (phase wrap 방지): 평균 0, 표준편차 1
    mu, sd = float(np.mean(E_raw)), float(np.std(E_raw)) or 1.0
    E = (E_raw - mu) / sd

    if p == 1:
        # 격자 탐색 (γ∈[0,2π), β∈[0,π)) 후 Nelder-Mead 정련
        best = (None, np.inf)
        for g in np.linspace(0, 2 * np.pi, 25, endpoint=False):
            for b in np.linspace(0, np.pi, 13, endpoint=False):
                v = expectation(E, np.array([g, b]), 1)
                if v < best[1]:
                    best = (np.array([g, b]), v)
        params, _ = _nelder_mead(lambda q: expectation(E, q, 1), best[0], steps=120)
    else:
        p1 = run_qaoa(E_raw, p=1, shots=0, seed=seed)
        g1, b1 = p1["params"][0], p1["params"][1]
        x0 = np.array([g1 * 0.75, g1, b1, b1 * 0.5])  # p=1 해 기반 보간 초기값
        params, _ = _nelder_mead(lambda q: expectation(E, q, p), x0, steps=300)

    psi = qaoa_state(E, params[:p], params[p:])
    probs = np.abs(psi) ** 2
    probs /= probs.sum()

    i_opt = int(np.argmin(E_raw))
    e_min, e_max = float(E_raw.min()), float(E_raw.max())
    exp_raw = float(np.sum(probs * E_raw))
    approx_ratio = (e_max - exp_raw) / (e_max - e_min)  # 1이면 최적
    p_opt = float(probs[i_opt])

    out = {
        "p": p,
        "params": params.tolist(),
        "expected_energy": exp_raw,
        "approx_ratio": round(approx_ratio, 4),
        "prob_optimal": round(p_opt, 6),
        "prob_optimal_vs_uniform": round(p_opt * 2 ** N, 2),  # 균등 대비 증폭 배수
        "time_s": time.perf_counter() - t0,
    }
    if shots:
        rng = np.random.default_rng(seed)
        samples = rng.choice(2 ** N, size=shots, p=probs)
        counts = np.bincount(samples, minlength=2 ** N)
        i_best_sampled = int(min(np.flatnonzero(counts), key=lambda i: E_raw[i]))
        x = [(i_best_sampled >> j) & 1 for j in range(N)]
        out.update({
            "shots": shots,
            "best_sampled_energy": float(E_raw[i_best_sampled]),
            "best_sampled_x": x,
            "sampled_optimal_found": bool(counts[i_opt] > 0),
        })
    return out
