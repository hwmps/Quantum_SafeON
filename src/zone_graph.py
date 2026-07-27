# -*- coding: utf-8 -*-
"""구역 그래프 구성 (워크플로우_파트1 P1-3) — 센서 QUBO와 대피 QUBO의 공통 기반

노드 = 구역(12개, Data/01_layout/zone_graph), 간선 = 인접(문·개구부) 관계.
간선 속성: 길이(중심 간 직선거리, m), 물리 폭(법규 D1-LAW-009/010), 유효폭(D2-FLOW-005),
용량 c_e(D2-FLOW-004, persons/s).

출구: 레이아웃상 Z12(하역장·주 출입구). 건축법 시행령 제34조제2항(D1-LAW-005)의
'직통계단 2개소 이상' 요건을 반영하기 위해 서측 비상구 EX2를 **합성 노드로 추가**하고
synthetic=True로 명시한다(실측 아님 — 발표 자료·결과 JSON에 한계로 기록).
"""
import math
from itertools import islice

from evacuation_evidence import edge_capacity, effective_width, load_evidence

# 합성 비상구: 서측 경계. 근거는 레이아웃이 아니라 법정 출구 수 요건 충족을 위한 모델링 가정.
EXIT_DOOR_WIDTH_M = 0.9      # D1-LAW-012 피난계단 출입구 최소 폭 (비상구 병목, 보수적 하한)
LOADING_GATE_WIDTH_M = 3.0   # 하역장 주 출입구 개구부 — 모델링 가정(실측 아님, 발표 시 명시)

SYNTHETIC_EXIT = {
    "id": "EX2",
    "name": "서측 비상구(합성)",
    "type": "emergency_exit",
    "cx": 0.0,
    "cy": 18.0,
    "adjacent": ["Z01", "Z06"],
    "synthetic": True,
}


def build_graph(zones, evidence=None):
    """반환: dict(nodes, edges, exits, meta)

    edges: {(u,v) 정렬튜플: {"length_m", "width_m", "eff_width_m", "capacity_pps"}}
    """
    ev = evidence or load_evidence()
    c = ev["constants"]

    nodes = {zid: {
        "name": z["name"], "type": z["type"], "cx": z["cx"], "cy": z["cy"],
        "synthetic": False,
    } for zid, z in zones.items()}
    adj = {zid: set(z["adjacent"]) for zid, z in zones.items()}

    # 합성 비상구 노드 추가
    ex = SYNTHETIC_EXIT
    nodes[ex["id"]] = {"name": ex["name"], "type": ex["type"], "cx": ex["cx"],
                       "cy": ex["cy"], "synthetic": True}
    adj[ex["id"]] = set(ex["adjacent"])
    for n in ex["adjacent"]:
        adj.setdefault(n, set()).add(ex["id"])

    edges = {}
    for u, nbrs in adj.items():
        for v in nbrs:
            if v not in nodes:
                continue
            key = tuple(sorted((u, v)))
            if key in edges:
                continue
            a, b = nodes[key[0]], nodes[key[1]]
            length = math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
            types = {nodes[k]["type"] for k in key}
            # 폭 결정 규칙 (법정 최소치를 보수적으로 대입 — '이상' 기준이므로 하한값 사용)
            #  · 비상구 접속: 0.9 m — D1-LAW-012 피난계단 출입구 최소 폭 (병목)
            #  · 하역장 주 출입구 접속: 3.0 m — 차량·자재 반입 개구부, **모델링 가정(실측 아님)**
            #  · 주 통로·피난 동선 접속: 1.5 m — D1-LAW-009 거실 양옆 복도
            #  · 그 외: 1.2 m — D1-LAW-010 기타 복도
            if "emergency_exit" in types:
                w = EXIT_DOOR_WIDTH_M
            elif "loading_entrance" in types:
                w = LOADING_GATE_WIDTH_M
            elif "main_corridor" in types:
                w = c["corridor_width_main_m"]
            else:
                w = c["corridor_width_other_m"]
            edges[key] = {
                "length_m": round(length, 2),
                "width_m": w,
                "eff_width_m": round(effective_width(w, boundary_m=c["boundary_layer_m"]), 3),
                "capacity_pps": round(edge_capacity(w, c), 3),
            }

    exits = [zid for zid, n in nodes.items()
             if n["type"] in ("loading_entrance", "emergency_exit")]

    return {
        "nodes": nodes,
        "adj": {k: sorted(v) for k, v in adj.items()},
        "edges": edges,
        "exits": sorted(exits),
        "meta": {
            "edge_length_def": "구역 중심 간 직선거리 (2D 근사, 실제 통행 경로장 아님)",
            "width_basis": (f"복도 D1-LAW-009(1.5m)/D1-LAW-010(1.2m), 비상구 접속 "
                            f"D1-LAW-012({EXIT_DOOR_WIDTH_M}m), 하역장 개구부 "
                            f"{LOADING_GATE_WIDTH_M}m(모델링 가정·실측 아님)"),
            "capacity_basis": "D2-FLOW-004 1.3 persons/(m·s) × 유효폭(D2-FLOW-005 편측 0.15m 차감)",
            "exit_note": (f"출구 {len(exits)}개소 — Z12는 레이아웃 근거, EX2는 D1-LAW-005"
                          "(직통계단 2개소 이상) 충족을 위한 합성 노드"),
            "limitation": "벽 차폐·문 위치·층고·계단 미반영. 실제 도면 좌표가 아니라 합성 레이아웃.",
        },
    }


def _simple_paths(adj, start, goals, max_len=6):
    """단순 경로 전수 열거 (12+1 노드 소규모 그래프이므로 DFS 전수로 충분)."""
    out = []
    stack = [(start, [start])]
    while stack:
        node, path = stack.pop()
        if node in goals and len(path) > 1:
            out.append(path)
            continue  # 출구 도달 후 더 진행하지 않음
        if len(path) >= max_len:
            continue
        for nb in adj.get(node, []):
            if nb not in path:
                stack.append((nb, path + [nb]))
    return out


def path_length(graph, path):
    return sum(graph["edges"][tuple(sorted((path[i], path[i + 1])))]["length_m"]
               for i in range(len(path) - 1))


def path_edges(path):
    return [tuple(sorted((path[i], path[i + 1]))) for i in range(len(path) - 1)]


def k_shortest_routes(graph, origin, k=3, exits=None, max_len=6, diversify_exits=True):
    """출발 구역 → 출구까지의 k-최단 단순 경로 (경로 후보 = QUBO 변수 후보).

    diversify_exits=True이면 **출구별 최단 경로를 먼저 1개씩 확보**한 뒤 나머지를 전체 최단
    순으로 채운다. 단순 k-최단만 쓰면 후보 3개가 모두 같은 출구·같은 마지막 간선을 공유해
    혼잡 회피 선택지가 아예 없어지기 때문이다(대체안이 없으면 이차항이 상수가 되어 최적화
    문제가 퇴화한다). 대피 계획 관점에서도 출구 분산은 표준적인 요구사항이다.
    """
    goals = set(exits or graph["exits"])
    paths = _simple_paths(graph["adj"], origin, goals, max_len=max_len)
    paths.sort(key=lambda p: path_length(graph, p))
    if not diversify_exits:
        return list(islice(paths, k))
    chosen, seen_exit = [], set()
    for p in paths:
        if p[-1] not in seen_exit:
            chosen.append(p)
            seen_exit.add(p[-1])
        if len(chosen) >= k:
            break
    for p in paths:
        if len(chosen) >= k:
            break
        if p not in chosen:
            chosen.append(p)
    chosen.sort(key=lambda p: path_length(graph, p))
    return chosen[:k]


if __name__ == "__main__":
    import json
    from data_loader import load_zones

    g = build_graph(load_zones())
    print(json.dumps({
        "n_nodes": len(g["nodes"]), "n_edges": len(g["edges"]), "exits": g["exits"],
        "sample_edges": {str(k): v for k, v in list(g["edges"].items())[:5]},
        "routes_Z06": [{"path": p, "len_m": round(path_length(g, p), 1)}
                       for p in k_shortest_routes(g, "Z06")],
    }, ensure_ascii=False, indent=2))
