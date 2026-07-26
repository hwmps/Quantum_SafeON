# -*- coding: utf-8 -*-
"""IonQ 연결 테스트 — Kevin 로컬(.venv)에서 실행.

사용법:
  1) 프로젝트 루트 .env 에 IONQ_API_KEY=<키> 추가 (파일은 git 제외, 문서에 키 기재 금지)
  2) .venv 활성화 후:
       python src/ionq_connect_test.py            # 1~4단계: 무료 (클라우드 시뮬레이터까지만)
       python src/ionq_connect_test.py --qpu aria-1   # 5단계: 실제 QPU 제출 (유료! 확인 입력 요구)

단계:
  1. API 키 로드 확인 (.env → 환경변수)
  2. IonQProvider 인증 + 사용 가능 백엔드 목록
  3. QAOA 회로(p=1, nominal 시나리오) 생성 + IonQ 백엔드 기준 transpile 지표 기록
  4. ionq_simulator(클라우드, 무료)에 100샷 제출 → 결과 수신 확인
  5. (--qpu 지정 시에만) 실제 QPU에 소량 샷 제출 — 비용 발생, 명시적 확인 필요

결과는 results/ionq_connect_test.json 에 저장.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_loader  # noqa: F401  (.env → 환경변수)
import data_loader as dl
from risk_model import zone_risk_scores, hard_cover_zones
from qubo import build_qubo
from run_experiment import K_SENSORS, HARD_TAU
from qaoa_qiskit import build_qaoa_circuit, transpile_metrics

RESULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "results", "ionq_connect_test.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qpu", default=None, help="실제 QPU 백엔드명 (예: aria-1). 미지정 시 시뮬레이터까지만.")
    ap.add_argument("--shots", type=int, default=100)
    args = ap.parse_args()

    out = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}}

    # 1. API 키
    key = os.environ.get("IONQ_API_KEY")
    if not key:
        print("[1] 실패: IONQ_API_KEY 없음 — .env 에 추가하세요.")
        sys.exit(1)
    out["steps"]["1_api_key"] = "ok (키 존재, 값은 기록 안 함)"
    print("[1] API 키 로드 OK")

    # 2. Provider 인증 + 백엔드 목록
    try:
        from qiskit_ionq import IonQProvider
    except ImportError:
        print("[2] 실패: qiskit_ionq 미설치 — .venv로 실행해야 합니다.\n"
              "  해결: 프로젝트 루트에서\n"
              "    .venv\\Scripts\\activate  (또는 .venv\\Scripts\\python.exe src\\ionq_connect_test.py)\n"
              "  .venv가 없으면: scripts\\setup_quantum_env.cmd 실행")
        sys.exit(1)
    provider = IonQProvider(key)
    backends = [b.name for b in provider.backends()]
    out["steps"]["2_backends"] = backends
    print(f"[2] 인증 OK — 백엔드: {backends}")

    # 3. QAOA 회로 + transpile 지표 (nominal, p=1, 대표 파라미터)
    zones = dl.load_zones()
    candidates = dl.load_candidates()
    incidents = dl.load_incidents()
    costs, _radii = dl.load_sensor_costs()
    a = dl.load_fractional_coverage(candidates, "nominal")
    risk = zone_risk_scores(zones, incidents)
    hard = hard_cover_zones(zones)
    cand_costs = [dl.candidate_cost(c, costs) for c in candidates]
    Q, const, _notes = build_qubo(zones, candidates, a, risk, cand_costs, hard,
                                  K=K_SENSORS, hard_tau=HARD_TAU)
    qc = build_qaoa_circuit(Q, const, gammas=[0.4], betas=[0.6])
    sim_backend = provider.get_backend("ionq_simulator")
    try:
        metrics = transpile_metrics(qc, backend=sim_backend)
        metrics["backend_target"] = "ionq_simulator"
    except Exception as e:
        # qiskit-ionq 시뮬레이터 target의 큐비트 수 오보고 이슈 → 백엔드 무지정 transpile 폴백
        metrics = transpile_metrics(qc, backend=None)
        metrics["backend_target"] = f"generic (ionq_simulator target 실패: {type(e).__name__})"
    out["steps"]["3_transpile"] = metrics
    print(f"[3] Transpile OK — 큐비트 {metrics['num_qubits']}, depth {metrics['depth']}, "
          f"2Q 게이트 {metrics['two_qubit_gates']}")

    # 4. 클라우드 시뮬레이터 제출 (무료)
    job = sim_backend.run(qc, shots=args.shots)
    counts = job.result().get_counts()
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    out["steps"]["4_cloud_simulator"] = {"shots": args.shots, "top3": top, "job_id": job.job_id()}
    print(f"[4] 클라우드 시뮬레이터 OK — 상위 3개 비트열: {top}")

    # 5. 실제 QPU (명시적 요청 시에만)
    if args.qpu:
        print(f"\n⚠ 실제 QPU '{args.qpu}' 제출은 비용이 발생합니다 (샷 {args.shots}).")
        if input("계속하려면 'YES' 입력: ").strip() != "YES":
            print("[5] 취소됨")
            out["steps"]["5_qpu"] = "취소됨"
        else:
            qpu = provider.get_backend(f"ionq_qpu.{args.qpu}")
            qmetrics = transpile_metrics(qc, backend=qpu)
            job = qpu.run(qc, shots=args.shots)
            print(f"[5] QPU 제출 완료 — job_id {job.job_id()} (큐 대기 가능, 결과는 IonQ 콘솔 확인)")
            out["steps"]["5_qpu"] = {"backend": args.qpu, "job_id": job.job_id(),
                                     "transpile": qmetrics, "shots": args.shots}

    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {RESULT_PATH}")


if __name__ == "__main__":
    main()
