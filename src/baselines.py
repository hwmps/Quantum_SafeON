# -*- coding: utf-8 -*-
"""고전 베이스라인 4종 (멘토링: 4개 이상 유지, 비교군 줄이지 말 것)
① Exact (전수조사 2^12) ② Greedy ③ Simulated Annealing ④ Random
공통 인터페이스: solve(Q, const) → dict(x, energy, time_s)
"""
import itertools
import time

import numpy as np

from qubo import N, all_energies, energy


def solve_exact(Q, const):
    t0 = time.perf_counter()
    E, xs = all_energies(Q, const)
    i = int(np.argmin(E))
    return {"method": "Exact(brute-force)", "x": xs[i].astype(int).tolist(),
            "energy": float(E[i]), "time_s": time.perf_counter() - t0}


def solve_greedy(Q, const):
    """빈 해에서 시작해 에너지 감소가 최대인 변수를 하나씩 켠다 (감소 없으면 중단)."""
    t0 = time.perf_counter()
    x = np.zeros(N)
    e = energy(Q, const, x)
    while True:
        best_j, best_e = None, e
        for j in range(N):
            if x[j] == 0:
                x[j] = 1
                e2 = energy(Q, const, x)
                x[j] = 0
                if e2 < best_e:
                    best_j, best_e = j, e2
        if best_j is None:
            break
        x[best_j] = 1
        e = best_e
    return {"method": "Greedy", "x": x.astype(int).tolist(),
            "energy": float(e), "time_s": time.perf_counter() - t0}


def solve_sa(Q, const, n_sweeps=2000, T0=5.0, T1=0.01, seed=42):
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    x = rng.integers(0, 2, N).astype(float)
    e = energy(Q, const, x)
    best_x, best_e = x.copy(), e
    Ts = T0 * (T1 / T0) ** (np.arange(n_sweeps) / max(n_sweeps - 1, 1))
    for T in Ts:
        for j in rng.permutation(N):
            x[j] = 1 - x[j]
            e2 = energy(Q, const, x)
            if e2 <= e or rng.random() < np.exp(-(e2 - e) / T):
                e = e2
                if e < best_e:
                    best_x, best_e = x.copy(), e
            else:
                x[j] = 1 - x[j]
    return {"method": "SimulatedAnnealing", "x": best_x.astype(int).tolist(),
            "energy": float(best_e), "time_s": time.perf_counter() - t0}


def solve_random(Q, const, n_samples=4096, seed=7):
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    best_x, best_e = None, np.inf
    for _ in range(n_samples):
        x = rng.integers(0, 2, N).astype(float)
        e = energy(Q, const, x)
        if e < best_e:
            best_x, best_e = x, e
    return {"method": f"Random(best of {n_samples})", "x": best_x.astype(int).tolist(),
            "energy": float(best_e), "time_s": time.perf_counter() - t0}
