# -*- coding: utf-8 -*-
"""IonQ 실기 QPU 실험 — Ideal Simulator에서 최적화된 (γ,β)로 QAOA 회로를 제출.

연결 테스트(ionq_connect_test.py)와 달리 experiment_results.json 의 최적 파라미터를 사용한다.
QPU 파라미터 최적화 루프는 돌리지 않는다(비용 절약 — 고정 파라미터 제출이 NISQ 표준 관행).

사용법 (.venv 에서):
  python src/run_qpu_experiment.py                     # 클라우드 시뮬레이터 검증 (무료)
  python src/run_qpu_experiment.py --qpu aria-1        # 실제 QPU 제출 (유료, YES 확인)
  python src/run_qpu_experiment.py --fetch             # 이전 제출 job 결과 회수·분석
옵션: --scenarios nominal (기본) | low,nominal,high  /  --p 1,2 (기본)  /  --shots 1024 (기본)

결과: results/qpu_results.json, results/QPU실험_요약.md
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_loader  # noqa: F401
import data_loader as dl
from risk_model import zone_risk_scores, hard_cover_zones
from qubo import build_qubo, energy, N
from baselines import solve_exact
from run_experiment import K_SENSORS, HARD_TAU
from qaoa_qiskit import build_qaoa_circuit
import weather_kma

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
IDEAL_PATH = os.path.join(RESULTS, "experiment_results.json")
OUT_PATH = os.path.join(RESULTS, "qpu_results.json")
PENDING_PATH = os.path.join(RESULTS, "qpu_pending_jobs.json")
SUMMARY_PATH = os.path.join(RESULTS, "QPU실험_요약.md")


def build_problem(scenario):
    zones = dl.load_zones()
    candidates = dl.load_candidates()
    incidents = dl.load_incidents()
    costs, _ = dl.load_sensor_costs()
    weather = weather_kma.load_cached_weather()
    a = dl.load_fractional_coverage(candidates, scenario)
    risk = zone_risk_scores(zones, incidents, weather=weather)
    hard = hard_cover_zones(zones)
    cand_costs = [dl.candidate_cost(c, costs) for c in candidates]
    Q, const, _ = build_qubo(zones, candidates, a, risk, cand_costs, hard,
                             K=K_SENSORS, hard_tau=HARD_TAU)
    return Q, const


def ideal_params(scenario, p):
    d = json.load(open(IDEAL_PATH, encoding="utf-8"))
    for rec in d["scenarios"][scenario]["qaoa_ideal"]:
        if rec["p"] == p:
            g, b = rec["params"][:p], rec["params"][p:]
            return g, b, rec
    raise KeyError(f"{scenario} p={p} 파라미터 없음 — run_experiment.py 먼저 실행")


def analyze(counts, Q, const, e_opt, shots):
    """counts(qiskit 비트열, clbit0=오른쪽) → 에너지 분포·최적해 확률·근사비."""
    total = sum(counts.values())
    e_min, e_best_x, p_opt, e_sum = None, None, 0.0, 0.0
    for bstr, c in counts.items():
        x = [int(ch) for ch in bstr[::-1]]  # little-endian → x[0..N-1]
        e = energy(Q, const, x)
        e_sum += e * c
        if abs(e - e_opt) < 1e-9:
            p_opt += c / total
        if e_min is None or e < e_min:
            e_min, e_best_x = e, x
    e_mean = e_sum / total
    # 근사비: E_max 대비 (ideal과 동일 정의: (E_max - <E>) / (E_max - E_min_exact))
    return {"shots": shots, "sampled_min_energy": round(e_min, 6),
            "sampled_best_x": e_best_x, "mean_energy": round(e_mean, 6),
            "prob_optimal": round(p_opt, 6),
            "prob_optimal_vs_uniform": round(p_opt / (1 / 2 ** N), 2) if p_opt else 0.0,
            "optimal_found": abs(e_min - e_opt) < 1e-9}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qpu", default=None, help="실제 QPU 백엔드 (예: aria-1). 미지정 시 클라우드 시뮬레이터.")
    ap.add_argument("--fetch", action="store_true", help="pending job 결과 회수")
    ap.add_argument("--scenarios", default="nominal")
    ap.add_argument("--p", default="1,2")
    ap.add_argument("--shots", type=int, default=1024)
    args = ap.parse_args()

    from qiskit_ionq import IonQProvider
    key = os.environ.get("IONQ_API_KEY")
    if not key:
        sys.exit("IONQ_API_KEY 없음 — .env 확인")
    provider = IonQProvider(key)

    scenarios = args.scenarios.split(",")
    ps = [int(v) for v in args.p.split(",")]

    if args.fetch:
        pend = json.load(open(PENDING_PATH, encoding="utf-8"))
        backend = provider.get_backend(pend["backend_name"])
        out = json.load(open(OUT_PATH, encoding="utf-8")) if os.path.exists(OUT_PATH) else {"runs": []}
        for jb in pend["jobs"]:
            job = backend.retrieve_job(jb["job_id"])
            st = str(job.status())
            print(f"{jb['scenario']} p={jb['p']} [{jb['job_id']}]: {st}")
            if "DONE" in st.upper():
                counts = job.result().get_counts()
                Q, const = build_problem(jb["scenario"])
                e_opt = solve_exact(Q, const)["energy"]
                res = analyze(counts, Q, const, e_opt, jb["shots"])
                out["runs"].append({**jb, "status": "done", "analysis": res,
                                    "counts_top10": sorted(counts.items(), key=lambda kv: -kv[1])[:10]})
        json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"저장: {OUT_PATH}")
        return

    if args.qpu:
        backend_name = f"ionq_qpu.{args.qpu}"
        print(f"⚠ 실제 QPU '{args.qpu}' 제출: {len(scenarios) * len(ps)}개 회로 × {args.shots}샷 — 비용 발생.")
        if input("계속하려면 'YES' 입력: ").strip() != "YES":
            sys.exit("취소됨")
    else:
        backend_name = "ionq_simulator"
    backend = provider.get_backend(backend_name)

    out = {"executed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "backend": backend_name,
           "K": K_SENSORS, "hard_tau": HARD_TAU, "runs": []}
    pending = {"backend_name": backend_name, "jobs": []}

    for sc in scenarios:
        Q, const = build_problem(sc)
        e_opt = solve_exact(Q, const)["energy"]
        for p in ps:
            g, b, ideal = ideal_params(sc, p)
            qc = build_qaoa_circuit(Q, const, gammas=g, betas=b)
            job = backend.run(qc, shots=args.shots)
            jid = job.job_id()
            print(f"제출: {sc} p={p} → job {jid}")
            rec = {"scenario": sc, "p": p, "shots": args.shots, "job_id": jid,
                   "params_gamma": g, "params_beta": b,
                   "ideal_ref": {k: ideal[k] for k in ("approx_ratio", "prob_optimal", "sampled_optimal_found")}}
            if args.qpu:
                pending["jobs"].append(rec)  # QPU는 큐 대기 가능 → job_id 저장 후 --fetch로 회수
            else:
                counts = job.result().get_counts()
                rec.update({"status": "done", "analysis": analyze(counts, Q, const, e_opt, args.shots),
                            "counts_top10": sorted(counts.items(), key=lambda kv: -kv[1])[:10]})
            out["runs"].append(rec)

    os.makedirs(RESULTS, exist_ok=True)
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if pending["jobs"]:
        json.dump(pending, open(PENDING_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"QPU 큐 대기 중 — 잠시 후 `python src/run_qpu_experiment.py --fetch` 로 회수. job 목록: {PENDING_PATH}")
    else:
        lines = [f"# QPU/클라우드 실험 요약 — {backend_name}", ""]
        for r in out["runs"]:
            a = r["analysis"]
            lines.append(f"- {r['scenario']} p={r['p']}: 최적해 발견 {a['optimal_found']}, "
                         f"P(최적해) {a['prob_optimal']} (균등 대비 {a['prob_optimal_vs_uniform']}배), "
                         f"최소 에너지 {a['sampled_min_energy']} | Ideal 참조 근사비 {r['ideal_ref']['approx_ratio']}")
        open(SUMMARY_PATH, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"저장: {OUT_PATH}, {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
