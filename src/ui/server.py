# -*- coding: utf-8 -*-
"""QRC2026 UI 결합 테스트본 로컬 서버 (무료 범위 전용)

- UI(index.html)에서 배치한 센서 후보를 받아 QUBO 최적화를 실행하고 선택 결과를 돌려준다.
- 백엔드: ideal(자체 statevector, 기본) 또는 ionq_sim(IonQ 클라우드 시뮬레이터, 무료, .env 키 필요).
  실제 QPU는 이 서버에서 호출하지 않는다 (비용 발생 경로 차단).
- 데모 전제(응답 notes에도 포함): 구역은 균일 격자, 위험도는 균일(0.5), 비용은 균일 —
  실제 파이프라인(run_experiment.py)의 위험 점수·법적 hard 제약·실비용과 다른 데모 구성이다.

실행 (.venv): python src/ui/server.py  →  http://localhost:8788
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC)
import env_loader  # noqa: F401
import qubo as qubo_mod
import baselines as bl
import qaoa_sim as qs
import fire_scenario
import hazard_explain as hx
import weather_kma

UI_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
PORT = 8788
MAX_N = 14  # 전수조사·statevector 한도 (2^14)

# 기본 데모 도면: CubiCasa5K plan 5570 (REC-008, E2E 검증 완료, residential_public_dataset)
# 배포본(Data/demo_plan)과 전체 데이터셋 경로(Data/cubicasa5k) 양쪽을 지원
_DEMO_CANDIDATES = [
    os.path.join(ROOT, "Data", "demo_plan", "F1_scaled.png"),
    os.path.join(ROOT, "Data", "cubicasa5k", "high_quality_architectural", "5570", "F1_scaled.png"),
]
DEMO_PNG = next((p for p in _DEMO_CANDIDATES if os.path.exists(p)), _DEMO_CANDIDATES[0])
DEMO_SENSORS = os.path.join(ROOT, "results", "cubicasa5k_ui_example.json")
DEMO_SITE_WIDTH_M = 30.0  # assumed_long_side_m (cubicasa5k_demo_layout.json)


_WEATHER_CACHE = {"t": 0.0, "v": None}
_WEATHER_TTL_S = 300.0


def current_weather():
    """기상 대표값(D3 관측 시계열 기반). 파일 재파싱을 막기 위해 5분 캐시.

    실패하거나 관측이 없으면 None → 풍향 보정 없이(등방) 동작한다.
    """
    now = time.time()
    if _WEATHER_CACHE["v"] is not None and now - _WEATHER_CACHE["t"] < _WEATHER_TTL_S:
        return _WEATHER_CACHE["v"]
    try:
        w = weather_kma.representative_weather()
    except Exception:
        w = None
    _WEATHER_CACHE.update({"t": now, "v": w})
    return w


def _clean_points(items, prefix, with_n=False, limit=24):
    """UI가 보낸 지점 목록(출구·작업자 위치)을 검증·정규화한다.

    좌표가 숫자가 아닌 항목은 조용히 버린다(UI 입력을 그대로 신뢰하지 않는다).
    빈 목록·None 이면 None 을 돌려 호출부가 '입력 없음' 경로(가정값/전 구역)를 타게 한다.
    """
    if not isinstance(items, list):
        return None
    out = []
    for k, it in enumerate(items[:limit]):
        if not isinstance(it, dict):
            continue
        try:
            x, y = float(it["x_m"]), float(it["y_m"])
        except (KeyError, TypeError, ValueError):
            continue
        p = {"id": str(it.get("id") or f"{prefix}{k + 1}")[:24], "x_m": x, "y_m": y}
        if it.get("name"):
            p["name"] = str(it["name"])[:40]
        if with_n:
            try:
                npeople = float(it.get("n") or 0)
                if npeople > 0:
                    p["n"] = npeople
            except (TypeError, ValueError):
                pass
        out.append(p)
    return out or None


def set_problem_size(n):
    """기존 검증 모듈(N=12 고정)을 데모용 가변 n으로 사용 — 모듈 전역 N 재설정."""
    qubo_mod.N = bl.N = qs.N = n


def zone_grid(w, h, rows, cols):
    zw, zh = w / cols, h / rows
    return [{"id": f"G{r * cols + c + 1}", "x0": c * zw, "y0": r * zh,
             "x1": (c + 1) * zw, "y1": (r + 1) * zh}
            for r in range(rows) for c in range(cols)]


def coverage_matrix(zones, sensors, ns=12):
    """부분면적 커버리지 근사: 구역을 ns×ns 격자점으로 샘플링, 반경 내 비율(0~1)."""
    a = np.zeros((len(zones), len(sensors)))
    for zi, z in enumerate(zones):
        xs = np.linspace(z["x0"], z["x1"], ns)
        ys = np.linspace(z["y0"], z["y1"], ns)
        gx, gy = np.meshgrid(xs, ys)
        for j, s in enumerate(sensors):
            d2 = (gx - s["x_m"]) ** 2 + (gy - s["y_m"]) ** 2
            a[zi, j] = float(np.mean(d2 <= s["radius_m"] ** 2))
    return a


def build_demo_qubo(a, risk, K, redundancy=0.35, lam_K=2.0):
    n = a.shape[1]
    Q = np.zeros((n, n))
    const = 0.0
    for zi in range(a.shape[0]):
        r = risk[zi]
        for j in range(n):
            if a[zi, j] > 0:
                Q[j, j] -= r * a[zi, j]
            for k in range(j + 1, n):
                if a[zi, j] > 0 and a[zi, k] > 0:
                    Q[j, k] += redundancy * r * a[zi, j] * a[zi, k]
    # 센서 수 제한 (Σx-K)^2
    for j in range(n):
        Q[j, j] += lam_K * (1 - 2 * K)
        for k in range(j + 1, n):
            Q[j, k] += 2 * lam_K
    const += lam_K * K * K
    return Q, const


def true_cov(a, risk, x):
    """구역별 실커버율 1-∏(1-a·x) 의 위험 가중 평균."""
    per_zone = 1.0 - np.prod(1.0 - a * np.array(x)[None, :], axis=1)
    return float(np.sum(per_zone * risk) / np.sum(risk)), per_zone.round(4).tolist()


def explain(a, risk, sensors, x_sel, zones, K, tau_show=0.25, weak_tau=0.30):
    """선택/제외 이유를 사람이 읽을 수 있는 한국어 해설로 생성 (데모 QUBO 기준)."""
    n = len(sensors)
    Z = len(zones)
    xs = np.array(x_sel, dtype=float)
    covsel = 1.0 - np.prod(1.0 - a * xs[None, :], axis=1)
    rsum = float(np.sum(risk))
    wtot = float(np.sum(covsel * risk) / rsum)
    mass = (a * risk[:, None]).sum(axis=0)  # 센서별 단독 커버 기여(위험 가중)
    order = np.argsort(-mass)
    rank = np.empty(n, dtype=int)
    rank[order] = np.arange(1, n + 1)
    max_mass = float(mass.max()) or 1.0

    items = []
    for j, s in enumerate(sensors):
        zj = [zones[zi]["id"] for zi in range(Z) if a[zi, j] >= tau_show]
        it = {"id": s["id"], "selected": bool(xs[j]), "rank": int(rank[j]),
              "covered_zones": zj}
        if xs[j]:
            x2 = xs.copy(); x2[j] = 0
            cov2 = 1.0 - np.prod(1.0 - a * x2[None, :], axis=1)
            drop = (wtot - float(np.sum(cov2 * risk) / rsum)) * 100
            uniq = [zones[zi]["id"] for zi in range(Z)
                    if a[zi, j] >= tau_show and not any(x2[k] and a[zi, k] >= tau_show for k in range(n))]
            parts = []
            if uniq:
                parts.append(f"{'·'.join(uniq)} zones are covered almost exclusively by this sensor")
            parts.append(f"Removing this sensor reduces overall coverage by {drop:.1f} percentage points")
            parts.append(f"Coverage contribution rank: {rank[j]}/{n}")
            it["reason"] = " · ".join(parts)
            it["removal_drop_pp"] = round(drop, 2)
        else:
            x2 = xs.copy(); x2[j] = 1
            cov2 = 1.0 - np.prod(1.0 - a * x2[None, :], axis=1)
            gain = (float(np.sum(cov2 * risk) / rsum) - wtot) * 100
            overlap = float(np.sum(a[:, j] * covsel * risk) / (mass[j] or 1e-12))
            it["add_gain_pp"] = round(gain, 2)
            it["overlap_pct"] = round(overlap * 100)
            if mass[j] < 0.35 * max_mass or not zj:
                it["reason"] = (f"Limited coverage contribution (rank {rank[j]}/{n}) — the candidate is near the boundary or "
                                f"reaches relatively few zones within its detection radius. Adding it improves coverage by only +{gain:.1f} percentage points.")
            elif overlap >= 0.6:
                ov_k = max((k for k in range(n) if xs[k]),
                           key=lambda k: float(np.sum(a[:, j] * a[:, k] * risk)), default=None)
                ov_id = sensors[ov_k]["id"] if ov_k is not None else "a selected sensor"
                it["reason"] = (f"{overlap * 100:.0f}% of its coverage overlaps with {ov_id} or other selected sensors — "
                                f"the marginal gain is only +{gain:.1f} percentage points, so the K={K} sensor budget is better allocated elsewhere.")
            else:
                it["reason"] = (f"This candidate contributes coverage (rank {rank[j]}/{n}), but under the K={K} sensor limit "
                                f"it has lower priority. Adding it provides +{gain:.1f} percentage points and would require replacing a selected sensor.")
        items.append(it)

    weak = [{"id": zones[zi]["id"], "cov": round(float(covsel[zi]), 3)}
            for zi in range(Z) if covsel[zi] < weak_tau]
    zones_info = [{"id": z["id"], "x0": z["x0"], "y0": z["y0"], "x1": z["x1"], "y1": z["y1"],
                   "cov": round(float(covsel[zi]), 3)} for zi, z in enumerate(zones)]
    summary = (f"Selected {int(xs.sum())} sensors achieve {wtot * 100:.1f}% overall risk-weighted coverage. "
               + (f"High-risk zones below the {int(weak_tau * 100)}% coverage threshold: "
                  + ", ".join(f"{w['id']}({w['cov'] * 100:.0f}%)" for w in weak)
                  + " — consider adding candidate locations, increasing detection radius, or increasing K."
                  if weak else "All zones meet the target coverage threshold."))
    return {"summary": summary, "total_coverage_pct": round(wtot * 100, 1),
            "weak_zones": weak, "sensors": items, "zones_info": zones_info}


def run_ionq_cloud(Q, const, n, gammas, betas, shots=1024):
    """IonQ 클라우드 시뮬레이터(무료) 제출. 실패 시 예외 → 호출부에서 ideal 폴백."""
    from qiskit import QuantumCircuit
    from qiskit_ionq import IonQProvider
    key = os.environ.get("IONQ_API_KEY")
    if not key:
        raise RuntimeError("IONQ_API_KEY is not configured")
    # Ising 변환 (qaoa_qiskit.qubo_to_ising와 동일 수식, 가변 n)
    Qu = np.triu(Q)
    h = np.zeros(n)
    J = {}
    for i in range(n):
        h[i] -= Qu[i, i] / 2.0
        for j2 in range(i + 1, n):
            q = Qu[i, j2]
            if q:
                h[i] -= q / 4.0
                h[j2] -= q / 4.0
                J[(i, j2)] = q / 4.0
    qc = QuantumCircuit(n, n)
    qc.h(range(n))
    for g, b in zip(gammas, betas):
        for i in range(n):
            if h[i]:
                qc.rz(2.0 * g * h[i], i)
        for (i, j2), Jij in J.items():
            qc.rzz(2.0 * g * Jij, i, j2)
        qc.rx(2.0 * b, range(n))
    qc.measure(range(n), range(n))
    backend = IonQProvider(key).get_backend("ionq_simulator")
    job = backend.run(qc, shots=shots)
    counts = job.result().get_counts()
    best_i, best_e, agg = None, np.inf, {}
    for bstr, c in counts.items():
        x = [int(ch) for ch in bstr[::-1]]
        e = qubo_mod.energy(Q, const, np.array(x, dtype=float))
        agg[bstr] = c
        if e < best_e:
            best_e, best_i = e, x
    return {"backend": "ionq_simulator(cloud)", "shots": shots, "job_id": job.job_id(),
            "best_x": best_i, "best_energy": round(float(best_e), 6),
            "counts_top5": sorted(agg.items(), key=lambda kv: -kv[1])[:5]}


def optimize(req):
    sensors = req["sensors"]
    n = len(sensors)
    if n < 2:
        return {"error": "Place at least two sensor candidates."}
    if n > MAX_N:
        return {"error": f"This demo supports up to {MAX_N} sensor candidates due to exhaustive-search and statevector limits. Current count: {n}."}
    K = min(int(req.get("K", 6)), n)
    rows, cols = int(req.get("grid_rows", 3)), int(req.get("grid_cols", 4))
    w = float(req.get("site_width_m", 60))
    h = float(req.get("site_height_m", 40))

    zones = zone_grid(w, h, rows, cols)
    # 재해 발생원(위치·반경·유형) — PM 지시 2026-07-27. 센서 미연동 상태의 예시 설정값이며,
    # 지정하지 않으면 기존과 동일하게 uniform risk baseline (0.5)로 동작한다.
    # `hazards`(다중, 2026-07-27 확장)를 우선 쓰고 구버전 UI의 `fire`(단일)도 계속 받는다.
    haz_req = req.get("hazards")
    if haz_req is None:
        haz_req = req.get("fire")
    fire_srcs = fire_scenario.resolve_sources(
        haz_req if isinstance(haz_req, list) else ([haz_req] if haz_req else []))
    # 기상: 기본은 D3 관측 대표값(풍향 33.8°·풍속 3.8 m/s). use_weather=false 면 무풍 등방.
    weather = current_weather() if req.get("use_weather", True) else None
    risk_list, zone_hz = hx.zone_hazard_risk(
        [((z["x0"] + z["x1"]) / 2.0, (z["y0"] + z["y1"]) / 2.0) for z in zones],
        fire_srcs, weather=weather, base=0.5)
    risk = np.array(risk_list, dtype=float)
    a = coverage_matrix(zones, sensors)
    set_problem_size(n)
    Q, const = build_demo_qubo(a, risk, K)

    t0 = time.perf_counter()
    ex = bl.solve_exact(Q, const)
    gr = bl.solve_greedy(Q, const)
    E, _ = qubo_mod.all_energies(Q, const)
    qa = qs.run_qaoa(np.asarray(E), p=int(req.get("p", 1)), shots=1024)

    methods = {}
    for name, sol in (("exact", ex), ("greedy", gr)):
        cov, _ = true_cov(a, risk, sol["x"])
        methods[name] = {"x": sol["x"], "energy": round(sol["energy"], 6),
                         "n_selected": int(sum(sol["x"])), "weighted_coverage": round(cov, 4)}
    qx = qa.get("best_sampled_x", ex["x"])
    covq, _ = true_cov(a, risk, qx)
    methods["qaoa"] = {"x": qx, "energy": round(qa.get("best_sampled_energy", 0.0), 6),
                       "n_selected": int(sum(qx)), "weighted_coverage": round(covq, 4),
                       "approx_ratio": qa["approx_ratio"], "prob_optimal": qa["prob_optimal"],
                       "optimal_found": bool(qa.get("sampled_optimal_found")),
                        "backend": "ideal(statevector)",
                       "top_states": qa.get("top_states", [])}

    warn = None
    if req.get("backend") == "ionq_sim":
        try:
            p = int(req.get("p", 1))
            ion = run_ionq_cloud(Q, const, n, qa["params"][:p], qa["params"][p:])
            covi, _ = true_cov(a, risk, ion["best_x"])
            methods["qaoa"] = {"x": ion["best_x"], "energy": ion["best_energy"],
                               "n_selected": int(sum(ion["best_x"])),
                               "weighted_coverage": round(covi, 4),
                               "optimal_found": abs(ion["best_energy"] - ex["energy"]) < 1e-6,
                               "backend": ion["backend"], "job_id": ion["job_id"]}
        except Exception as e:
            warn = f"IonQ Cloud execution failed ({type(e).__name__}) — falling back to the ideal statevector simulator"

    sel = [s["id"] for s, v in zip(sensors, methods["qaoa"]["x"]) if v]
    expl = explain(a, risk, sensors, methods["qaoa"]["x"], zones, K)
    # 센서 ↔ 재해 영향값 해설을 센서 카드에 합친다 (PM 1순위 지적 3번)
    eff = hx.sensor_hazard_effect(sensors, fire_srcs, weather=weather)
    for it in expl["sensors"]:
        it["hazard"] = eff.get(it["id"], {})
    for zi, z in enumerate(expl["zones_info"]):
        if zi < len(zone_hz):
            z["hazard_mult"] = zone_hz[zi]["배수"]
            z["downwind"] = zone_hz[zi]["풍하측"]
        z["risk"] = round(float(risk[zi]), 3)
    fire_out = {"active": bool(fire_srcs), "sources": fire_srcs,
                "설명": fire_scenario.describe(fire_srcs),
                "zone_risk": [round(float(r), 3) for r in risk]}
    fire_out.update({"해설": hx.hazard_context(fire_srcs, weather)})
    # 대피 계획: 출구는 UI 입력값(없으면 격자 모서리 가정), 출발점은 작업자 위치 입력분
    # (없으면 전 구역). PM 지시 2026-07-27 — "어떤 위치에서 출구까지 어떤 방식이 효과적인가".
    evac = hx.evacuation_plan(zones, rows, cols, [float(r) for r in risk],
                              exits=_clean_points(req.get("exits"), "EX"),
                              origins=_clean_points(req.get("origins"), "W", with_n=True),
                              hazards=fire_srcs, weather=weather)
    return {"selected_ids": sel, "K": K, "n_candidates": n, "explanation": expl,
            "zones": {"rows": rows, "cols": cols}, "fire": fire_out,
            "weather": hx.wind_context(weather), "evacuation": evac,
            "methods": methods, "time_s": round(time.perf_counter() - t0, 2),
            "warning": warn,
            "notes": ("Demo configuration: uniform grid zones · "
                      + ("hazard-source-based risk (simulated input, not live sensor data)"
                         if fire_srcs else "uniform risk baseline (0.5)")
                      + (" · weather-based wind-direction adjustment applied" if (weather and fire_srcs)
                         else " · weather adjustment disabled (isotropic dispersion)" if not weather
                         else " · weather observations available, but directional adjustment is inactive without a hazard source")
                      + " · uniform installation cost. The interactive demo simplifies the full pipeline's risk scoring, hard constraints, and real-world cost model. "
                        "No physical QPU execution is claimed.")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # file:// 로 직접 연 index.html에서도 호출 가능하게 CORS 허용 (로컬 데모 전용 서버)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # fetch preflight
        self._send(204, b"", "text/plain")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(UI_DIR, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/demo_plan.png":
            if os.path.exists(DEMO_PNG):
                with open(DEMO_PNG, "rb") as f:
                    self._send(200, f.read(), "image/png")
            else:
                self._send(404, {"error": "Demo floor plan not found: " + DEMO_PNG})
        elif self.path == "/weather":
            # 풍향·풍속 관측 대표값과 그 의미 해설 (PM 1순위 지적 2번)
            self._send(200, hx.wind_context(current_weather()))
        elif self.path == "/fire_presets":
            # UI 재해 시나리오 선택지 (config/fire_scenarios.json). 센서 연동 전 예시 설정용.
            cfg = fire_scenario.load_config()
            self._send(200, {"ui_기본값": cfg.get("ui_기본값", {}),
                             "default": cfg.get("default"),  # PM 확정 대표 시나리오
                             "대표시나리오_비고": cfg.get("_대표시나리오_확정", ""),
                             "presets": {k: {"설명": v.get("설명", ""),
                                             "sources": v.get("sources", [])}
                                         for k, v in cfg.get("presets", {}).items()},
                             "비고": "Simulated configuration values; not connected to live sensor measurements."})
        elif self.path == "/demo_layout":
            out = {"site_width_m": DEMO_SITE_WIDTH_M,
                   "source": "CubiCasa5K plan 5570 (public residential floor-plan demo)",
                   "sensors": []}
            if os.path.exists(DEMO_SENSORS):
                with open(DEMO_SENSORS, encoding="utf-8") as f:
                    out["sensors"] = json.load(f).get("sensors", [])
            self._send(200, out)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/optimize":
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(200, optimize(req))
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Quantum SafeON interactive demo: http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
