# -*- coding: utf-8 -*-
"""Qiskit QAOA 회로 생성 (실기 QPU 제출용 — qiskit 설치 환경에서 사용)

용도:
- 대회 IonQ API 키 수령 후: qiskit-ionq provider로 이 회로를 제출.
- Transpile 후 지표(큐비트 수, depth, 2Q 게이트 수)를 기록해 실행 가능성 판단 (워크플로우 3-3).
- 로컬 검증은 qaoa_sim.py (수학적으로 동일) 사용.

설치: pip install qiskit qiskit-ionq
"""
import numpy as np

from qubo import N


def qubo_to_ising(Q, const):
    """QUBO(x∈{0,1}) → Ising(z∈{-1,1}), x=(1-z)/2. 반환 h, J, offset."""
    Qu = np.triu(Q)
    h = np.zeros(N)
    J = {}
    offset = const
    for i in range(N):
        offset += Qu[i, i] / 2.0
        h[i] -= Qu[i, i] / 2.0
        for j in range(i + 1, N):
            q = Qu[i, j]
            if q == 0:
                continue
            offset += q / 4.0
            h[i] -= q / 4.0
            h[j] -= q / 4.0
            J[(i, j)] = q / 4.0
    return h, J, offset


def build_qaoa_circuit(Q, const, gammas, betas):
    """QAOA 회로 (측정 포함). qiskit 필요."""
    from qiskit import QuantumCircuit
    h, J, _ = qubo_to_ising(Q, const)
    qc = QuantumCircuit(N, N)
    qc.h(range(N))
    for g, b in zip(gammas, betas):
        for i in range(N):
            if h[i] != 0:
                qc.rz(2.0 * g * h[i], i)
        for (i, j), Jij in J.items():
            qc.rzz(2.0 * g * Jij, i, j)
        qc.rx(2.0 * b, range(N))
    qc.measure(range(N), range(N))
    return qc


def transpile_metrics(qc, backend=None, optimization_level=3):
    """Transpile 후 회로 지표 추출 (워크플로우 3-3 요구사항)."""
    from qiskit import transpile
    tqc = transpile(qc, backend=backend, optimization_level=optimization_level)
    ops = tqc.count_ops()
    two_q = sum(v for k, v in ops.items() if k in ("rzz", "cx", "cz", "zz", "ms", "ecr"))
    return {
        "num_qubits": tqc.num_qubits,
        "depth": tqc.depth(),
        "two_qubit_gates": int(two_q),
        "ops": {k: int(v) for k, v in ops.items()},
        "optimization_level": optimization_level,
    }
