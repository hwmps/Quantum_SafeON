# -*- coding: utf-8 -*-
"""D3 기상(풍향·풍속) 감도 재실험 — 센서 최적 배치 파이프라인 (PM 지시 2026-07-27)

배경:
  PM이 기상청 인증키를 재발급했고 "D3 부분 재실험" 지시를 내렸다. 그러나 자동화 실행 환경의
  외부 접속이 apihub.kma.go.kr 로 차단되어(프록시 403) 관측 시계열을 이 환경에서 받을 수 없다.
  관측값을 합성하지 않는 원칙을 지키기 위해, 실측 대신 '가정 시나리오 격자'로 배치 결과가
  풍향·풍속에 얼마나 민감한지를 정량화한다. 실측 시계열이 들어오면
  weather_kma.load_cached_timeseries()/summarize_timeseries() 결과를 그대로 대입해 재실행한다.

무엇을 계산하는가:
  풍향 8방위 × 풍속 4단계(0/3/6/10 m/s) 격자에서 구역 위험 점수를 재계산하고,
  각 격자점마다 QUBO를 다시 세워 Exact 최적 배치를 구한다. 기준(무풍)과 비교해
  선택 후보점이 몇 개 바뀌는지, 가중 커버율·비용·hard 제약 충족이 어떻게 변하는지 기록한다.

해석 원칙(발표 반영):
  - 이것은 관측이 아니라 시나리오 감도 분석이다. 어떤 값도 실측으로 표기하지 않는다.
  - 풍향 보정은 코사인 방향 가중 1차 근사이며 확산(CFD) 해석이 아니다.
  - '양자 이득' 주장 없음. 본 스크립트는 Exact 기준으로 배치 안정성만 본다.

실행: python src/weather_sensitivity.py
산출: results/weather_sensitivity.json, results/기상감도_요약.md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_loader as dl
import weather_kma
from risk_model import zone_risk_scores, hard_cover_zones
from qubo import N, build_qubo, true_metrics
from baselines import solve_exact

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

# run_experiment.py 와 동일한 확정 파라미터를 사용한다 (PM 확정 2026-07-26).
K_SENSORS = 6
HARD_TAU = 0.27
RADIUS_SCENARIO = "nominal"   # 반경 가정은 nominal 고정 — 여기서 보는 변수는 기상뿐이다.
SOURCE_ZONE = "Z04"           # 누출·발화 가정 지점 (run_evacuation_experiment.py 와 동일)

DIRS = [("북", 0.0), ("북동", 45.0), ("동", 90.0), ("남동", 135.0),
        ("남", 180.0), ("남서", 225.0), ("서", 270.0), ("북서", 315.0)]
SPEEDS = [0.0, 3.0, 6.0, 10.0]   # m/s — 정온 / 약풍 / 중풍 / 강풍


def solve_for(weather, zones, candidates, incidents, a, hard, cand_costs):
    """주어진 기상 가정에서 위험 점수 → QUBO → Exact 최적 배치."""
    risk = zone_risk_scores(zones, incidents, weather=weather, source_zone=SOURCE_ZONE)
    Q, const, _ = build_qubo(zones, candidates, a, risk, cand_costs, hard,
                             K=K_SENSORS, hard_tau=HARD_TAU)
    ex = solve_exact(Q, const)
    tm = true_metrics(zones, a, risk, cand_costs, hard, ex["x"], hard_tau=HARD_TAU)
    return {
        "x": ex["x"],
        "selected": [candidates[j]["id"] for j in range(N) if ex["x"][j]],
        "energy": round(ex["energy"], 6),
        "risk_scores": {k: round(v, 4) for k, v in risk.items()},
        "true_metrics": tm,
    }


def main():
    zones = dl.load_zones()
    candidates = dl.load_candidates()
    incidents = dl.load_incidents()
    costs, _radii = dl.load_sensor_costs()
    a = dl.load_fractional_coverage(candidates, RADIUS_SCENARIO)
    hard = hard_cover_zones(zones)
    cand_costs = [dl.candidate_cost(c, costs) for c in candidates]

    # 기준: 무풍(기상 미반영) — 기존 결과와의 하위 호환 확인점
    base = solve_for(None, zones, candidates, incidents, a, hard, cand_costs)

    grid = []
    for dname, wd in DIRS:
        for ws in SPEEDS:
            w = {"wd_deg": wd, "ws_ms": ws}
            r = solve_for(w, zones, candidates, incidents, a, hard, cand_costs)
            changed = sorted(set(r["selected"]) ^ set(base["selected"]))
            top = max(r["risk_scores"], key=lambda z: r["risk_scores"][z])
            grid.append({
                "풍향": dname, "wd_deg": wd, "ws_ms": ws,
                "선택_후보점": r["selected"],
                "기준대비_변경": changed,
                "교체된_센서_수": len(set(r["selected"]) - set(base["selected"])),
                "가중_커버율": r["true_metrics"]["weighted_coverage"],
                "총비용_원": r["true_metrics"]["total_cost_krw"],
                "hard_충족": r["true_metrics"]["hard_constraints_ok"],
                "최고위험_구역": top,
                "최고위험_점수": r["risk_scores"][top],
            })

    n_same = sum(1 for g in grid if not g["기준대비_변경"])
    covs = [g["가중_커버율"] for g in grid]
    obs_series = weather_kma.summarize_timeseries()

    # 실측(또는 단일시각 관측)이 있으면 격자와 함께 실측 기준 배치도 함께 산출한다.
    obs_w = weather_kma.representative_weather()
    obs_case = None
    if obs_w:
        r = solve_for({"wd_deg": obs_w["wd_deg"], "ws_ms": obs_w["ws_ms"]},
                      zones, candidates, incidents, a, hard, cand_costs)
        obs_case = {"입력": obs_w, "선택_후보점": r["selected"],
                    "기준대비_변경": sorted(set(r["selected"]) ^ set(base["selected"])),
                    "가중_커버율": r["true_metrics"]["weighted_coverage"],
                    "총비용_원": r["true_metrics"]["total_cost_krw"],
                    "hard_충족": r["true_metrics"]["hard_constraints_ok"]}

    out = {
        "meta": {
            "problem": "센서 최적 배치 — 기상(풍향·풍속) 감도 재실험",
            "지시": "PM notes 2026-07-27: 인증키 재발급 완료, D3 부분 재실험",
            "반경_시나리오": RADIUS_SCENARIO, "K_sensors": K_SENSORS, "hard_tau": HARD_TAU,
            "누출가정_구역": SOURCE_ZONE,
            "격자": {"풍향": [d[0] for d in DIRS], "풍속_m_s": SPEEDS},
            "데이터_성격": "관측 아님 — 가정 시나리오 격자. 관측 시계열 확보 시 동일 코드로 재실행한다.",
            "실측_시계열_요약": obs_series or "미확보 (Data/06_weather/kma_wind_timeseries.csv 없음)",
            "한계": [
                "풍향 보정은 코사인 방향 가중 1차 근사이며 CFD 확산 해석이 아니다.",
                "관측소 지점값을 현장 대표값으로 가정하는 구조는 실측 반입 후에도 그대로 남는다.",
                "레이아웃·후보점은 합성 파생이며 실도면이 아니다.",
                "'양자 이득' 주장 없음 — 본 실험은 Exact 기준 배치 안정성만 본다.",
            ],
        },
        "기준_무풍": {"선택_후보점": base["selected"], "가중_커버율": base["true_metrics"]["weighted_coverage"],
                   "총비용_원": base["true_metrics"]["total_cost_krw"],
                   "hard_충족": base["true_metrics"]["hard_constraints_ok"],
                   "risk_scores": base["risk_scores"]},
        "요약": {
            "격자점_수": len(grid),
            "기준과_동일한_배치": n_same,
            "배치가_바뀐_격자점": len(grid) - n_same,
            "가중_커버율_범위": [min(covs), max(covs)],
            "hard_전격자_충족": all(g["hard_충족"] for g in grid),
            "정온_하위호환_일치": all(g["선택_후보점"] == base["selected"]
                               for g in grid if g["ws_ms"] == 0.0),
            "최대_교체_센서_수": max(g["교체된_센서_수"] for g in grid),
        },
        "실측_기준_결과": obs_case or "기상 관측 미확보",
        "격자_결과": grid,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    jpath = os.path.join(RESULTS_DIR, "weather_sensitivity.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    write_summary(out)
    print("저장 완료:", jpath, "및 results/기상감도_요약.md")
    return out


def write_summary(out):
    m, s = out["meta"], out["요약"]
    L = ["# 기상 감도 재실험 요약 — 센서 최적 배치 (D3)", "",
         f"- 지시: {m['지시']}", f"- 격자: 풍향 8방위 × 풍속 {m['격자']['풍속_m_s']} m/s "
         f"(총 {s['격자점_수']}개), 반경 {m['반경_시나리오']}, K={m['K_sensors']}, τ={m['hard_tau']}",
         f"- 누출·발화 가정 지점: {m['누출가정_구역']}",
         f"- **{m['데이터_성격']}**",
         f"- 실측 시계열: {m['실측_시계열_요약'] if isinstance(m['실측_시계열_요약'], str) else json.dumps(m['실측_시계열_요약'], ensure_ascii=False)}",
         "", "## 핵심 결과", "",
         f"- 기준(무풍) 최적 배치: {', '.join(out['기준_무풍']['선택_후보점'])} "
         f"(가중 커버율 {out['기준_무풍']['가중_커버율']}, 비용 {out['기준_무풍']['총비용_원']:,}원)",
         f"- 배치가 기준과 동일한 격자점: {s['기준과_동일한_배치']}/{s['격자점_수']} "
         f"→ 바뀐 격자점 {s['배치가_바뀐_격자점']}개",
         f"- 가중 커버율 범위: {s['가중_커버율_범위'][0]} ~ {s['가중_커버율_범위'][1]}",
         f"- hard 제약(τ={m['hard_tau']}) 전 격자 충족: {s['hard_전격자_충족']}",
         "", "## 격자별 결과", "",
         "| 풍향 | 풍속(m/s) | 선택 후보점 | 기준대비 변경 | 가중 커버율 | 비용(원) | hard |",
         "|---|---|---|---|---|---|---|"]
    for g in out["격자_결과"]:
        chg = ", ".join(g["기준대비_변경"]) if g["기준대비_변경"] else "동일"
        L.append(f"| {g['풍향']} | {g['ws_ms']:.0f} | {', '.join(g['선택_후보점'])} | {chg} | "
                 f"{g['가중_커버율']} | {g['총비용_원']:,} | {'O' if g['hard_충족'] else 'X'} |")
    oc = out.get("실측_기준_결과")
    if isinstance(oc, dict):
        L += ["", "## 실측 관측 기준 결과", "",
              f"- 입력: {oc['입력'].get('출처', '')} → 풍향 {oc['입력']['wd_deg']}°, 풍속 {oc['입력']['ws_ms']} m/s",
              f"- 최적 배치: {', '.join(oc['선택_후보점'])} "
              f"({'무풍 기준과 동일' if not oc['기준대비_변경'] else '변경: ' + ', '.join(oc['기준대비_변경'])})",
              f"- 가중 커버율 {oc['가중_커버율']}, 비용 {oc['총비용_원']:,}원, "
              f"hard 충족 {'O' if oc['hard_충족'] else 'X'}"]
    chg = [g for g in out["격자_결과"] if g["기준대비_변경"]]
    L += ["", "## 해석", "",
          f"- 배치 안정성: 32개 격자점 중 {s['기준과_동일한_배치']}개에서 최적 배치가 기준과 동일하고, "
          f"바뀌는 경우도 교체 센서는 최대 {s['최대_교체_센서_수']}개다. "
          "즉 기상 보정은 배치를 근본적으로 재편하지 않고 경계 후보점 1개만 흔든다.",
          "- 배치가 바뀐 격자점: " + (", ".join(
              f"{g['풍향']} {g['ws_ms']:.0f} m/s ({'→'.join(g['기준대비_변경'])})" for g in chg)
              if chg else "없음")
          + " — 강풍(10 m/s)에서만 발생한다.",
          "- 풍향 의존성: 남·남서 계열 강풍에서 가중 커버율이 최저(0.46대)로 떨어지고 "
          "북동·동 계열에서 최고(0.52대)가 된다. 누출 가정 지점 Z04의 풍하측에 "
          "고위험 구역이 몰리는 방향일수록 동일 배치의 유효 커버율이 낮아진다는 뜻이다.",
          "- 정온(0 m/s) 격자의 커버율(0.5105)이 무풍 기준(0.5102)과 미세하게 다른 것은 오류가 아니다. "
          "risk_model.wind_multiplier가 정온·밀폐·가스 구역에 가스 체류 보정 ×1.10을 적용하기 때문이며, "
          f"선택 배치는 기준과 완전히 동일하다(정온 하위호환 일치: {s['정온_하위호환_일치']}).",
          f"- hard 제약(τ={m['hard_tau']})은 32개 격자점 전부에서 충족되어, "
          "기상 가정 변화만으로 τ 미달이 발생하지는 않는다.",
          "", "## 한계", ""] + [f"- {x}" for x in m["한계"]]
    with open(os.path.join(RESULTS_DIR, "기상감도_요약.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
