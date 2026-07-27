# -*- coding: utf-8 -*-
"""화재·누출 발생원(발화점) 시나리오 모듈 — PM 지시 2026-07-27

배경: 데모 단계에서는 실제 화재 감지 센서와 연동할 수 없다. 그래서
      (1) 지금은 화재의 **위치와 반경을 사람이 예시로 설정**할 수 있게 하고,
      (2) 나중에 실제 센서 피드가 생기면 **코드 수정 없이 공급원만 교체**하면 되도록
      공급자(Provider) 인터페이스를 분리해 둔다.

설계 원칙
---------
- 이 모듈은 프로젝트 내부 모듈을 import 하지 않는다(순환 참조 방지).
  방향성(풍하측) 보정은 호출부가 `dir_weight` 콜백으로 주입한다 → risk_model 이 담당.
- 발생원이 하나도 없으면 모든 보정 계수가 정확히 1.0 이다.
  즉 기존 실험 결과(발생원 미지정)와 수치가 완전히 동일하다(하위 호환).
- 모델은 CFD가 아니라 **거리 감쇠 1차 근사**다. 발표 자료에 가정으로 명시할 것.

자료구조 (발생원 1건)
--------------------
{
  "id": "F1",                 # 식별자
  "kind": "fire" | "gas_leak" | "smoke",
  "x_m": 19.0, "y_m": 6.0,    # 현장 좌표(m). zone_id 로 주면 resolve_sources 가 채운다.
  "zone_id": "Z04",           # (선택) 구역 중심을 위치로 사용
  "radius_m": 12.0,           # 영향 반경(m) — 이 안은 최대 가중
  "intensity": 1.0,           # 0~1 상대 세기
  "origin": "manual",         # manual | sensor | preset
  "tm": "202607271030",       # (선택) 발생·관측 시각
  "note": "..."               # (선택)
}
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "fire_scenarios.json")

KINDS = ("fire", "gas_leak", "smoke")

# ── 모델링 가정 (발표 자료에 명시) ────────────────────────────────────────────
MAX_GAIN = 1.00        # 발생원 반경 안 구역의 최대 위험 가중 (+100% = 위험 2배)
DECAY_EXP = 2.0        # 반경 밖 감쇠 지수: gain × (R/d)^2 (점원 확산 유추, 1차 근사)
MIN_GAIN_RATIO = 0.02  # 이 비율 미만의 가중은 0으로 절단 (수치 잡음 제거)
KIND_GAIN = {          # 위험 유형별 상대 가중 (가정)
    "fire": 1.00,      # 화재: 복사열·연소 확산
    "gas_leak": 1.10,  # 가스 누출: 점화 시 광역 피해 → 약간 높게
    "smoke": 0.80,     # 연기: 인명 영향 중심
}


# ── 발생원 생성·검증 ─────────────────────────────────────────────────────────
def make_source(sid, x_m=None, y_m=None, radius_m=10.0, kind="fire",
                intensity=1.0, origin="manual", zone_id=None, tm=None, note=None):
    """발생원 1건을 표준 dict 로 만든다."""
    src = {"id": str(sid), "kind": kind if kind in KINDS else "fire",
           "radius_m": float(radius_m), "intensity": float(intensity),
           "origin": origin}
    if zone_id:
        src["zone_id"] = zone_id
    if x_m is not None:
        src["x_m"] = float(x_m)
    if y_m is not None:
        src["y_m"] = float(y_m)
    if tm:
        src["tm"] = tm
    if note:
        src["note"] = note
    return src


def validate_source(src):
    """(정상여부, 오류메시지 리스트). UI·센서 입력을 그대로 신뢰하지 않는다."""
    errs = []
    if not isinstance(src, dict):
        return False, ["발생원이 dict 가 아니다."]
    if not src.get("id"):
        errs.append("id 누락")
    if src.get("kind") not in KINDS:
        errs.append(f"kind 는 {KINDS} 중 하나여야 한다 (현재 {src.get('kind')!r})")
    has_xy = src.get("x_m") is not None and src.get("y_m") is not None
    if not has_xy and not src.get("zone_id"):
        errs.append("위치가 없다 — x_m·y_m 또는 zone_id 중 하나는 있어야 한다")
    try:
        if float(src.get("radius_m", 0)) <= 0:
            errs.append("radius_m 은 0보다 커야 한다")
    except (TypeError, ValueError):
        errs.append("radius_m 이 숫자가 아니다")
    try:
        it = float(src.get("intensity", 1.0))
        if not (0.0 <= it <= 1.0):
            errs.append("intensity 는 0~1 범위여야 한다")
    except (TypeError, ValueError):
        errs.append("intensity 가 숫자가 아니다")
    return (not errs), errs


def resolve_sources(sources, zones=None, strict=False):
    """zone_id 만 있는 발생원의 좌표를 구역 중심으로 채우고, 유효한 것만 돌려준다.

    zones: data_loader.load_zones() 결과 {zid: {"cx":..,"cy":..}}. 없으면 좌표 지정분만 통과.
    strict=True 면 오류 시 예외를 던진다(파이프라인용). False 면 조용히 건너뛴다(UI용).
    """
    out = []
    for s in sources or []:
        s = dict(s)
        if s.get("zone_id") and zones and s["zone_id"] in zones:
            z = zones[s["zone_id"]]
            s.setdefault("x_m", z["cx"])
            s.setdefault("y_m", z["cy"])
        ok, errs = validate_source(s)
        if ok and s.get("x_m") is not None and s.get("y_m") is not None:
            out.append(s)
        elif strict:
            raise ValueError(f"발생원 {s.get('id')!r} 오류: {'; '.join(errs) or '좌표 확정 불가'}")
    return out


# ── 위험 가중 계산 ───────────────────────────────────────────────────────────
def _gain_at(dist_m, src):
    """발생원 하나가 거리 dist_m 지점에 주는 추가 가중(0 이상)."""
    R = float(src.get("radius_m", 0.0)) or 0.0
    if R <= 0:
        return 0.0
    base = MAX_GAIN * float(src.get("intensity", 1.0)) * KIND_GAIN.get(src.get("kind"), 1.0)
    if dist_m <= R:
        g = base
    else:
        g = base * (R / dist_m) ** DECAY_EXP
    return 0.0 if g < base * MIN_GAIN_RATIO else g


def hazard_multiplier(xy, sources, dir_weight=None):
    """지점 xy=(x,y) 의 위험 배수 ∈ [1.0, 1+최대가중].

    - 발생원이 여러 개면 **합산이 아니라 최대값**을 쓴다(지배 발생원 기준, 가정).
    - dir_weight: 선택적 콜백 (src_xy, tgt_xy) -> 배수. 풍하측 보정을 주입할 때 쓴다.
      발생원별 방향 가중을 그 발생원의 거리 가중에 곱한다.
    - sources 가 비면 정확히 1.0 → 기존 결과와 동일.
    """
    best = 0.0
    for s in sources or []:
        sx, sy = s.get("x_m"), s.get("y_m")
        if sx is None or sy is None:
            continue
        d = math.hypot(xy[0] - sx, xy[1] - sy)
        g = _gain_at(d, s)
        if g <= 0:
            continue
        if dir_weight is not None:
            g *= max(0.0, dir_weight((sx, sy), (xy[0], xy[1])) - 1.0) + 1.0
        best = max(best, g)
    return 1.0 + best


def affected_zones(zones, sources, threshold=1.20):
    """배수가 threshold 이상인 '주 영향' 구역 id 목록 (보고·UI 표시용).

    거리 감쇠가 완만해 현장 전체가 미약한 가중을 받으므로, 기본 임계값을 +20%로 두어
    실제로 배치 판단에 영향을 주는 구역만 나열한다.
    """
    return sorted(z for z in zones
                  if hazard_multiplier((zones[z]["cx"], zones[z]["cy"]), sources) >= threshold)


def describe(sources):
    """발표·로그용 한국어 요약 문자열."""
    if not sources:
        return "화재 시나리오 미적용 (발생원 없음 — 등방 기준)"
    kn = {"fire": "화재", "gas_leak": "가스누출", "smoke": "연기"}
    parts = [f"{s['id']}({kn.get(s.get('kind'), s.get('kind'))} "
             f"@({s.get('x_m')}, {s.get('y_m')})m, 반경 {s.get('radius_m')}m, "
             f"세기 {s.get('intensity', 1.0)}, 출처 {s.get('origin', 'manual')})"
             for s in sources]
    return "화재 시나리오 " + ", ".join(parts)


# ── 공급자(Provider) 인터페이스 — 추후 센서 연동 지점 ────────────────────────
class FireSourceProvider(object):
    """발생원 공급자 공통 계약. 새 공급원은 이 클래스를 상속해 get_sources 만 구현한다.

    파이프라인·UI 는 이 인터페이스에만 의존하므로, 실제 센서가 붙어도
    호출부 코드는 바뀌지 않는다.
    """
    name = "base"

    def get_sources(self):
        raise NotImplementedError

    def meta(self):
        return {"provider": self.name}


class ManualProvider(FireSourceProvider):
    """사람이 지정한 발생원(UI 클릭·설정 파일·프리셋). 현재 데모의 기본 경로."""
    name = "manual"

    def __init__(self, sources, label="manual"):
        self._sources = list(sources or [])
        self.label = label

    def get_sources(self):
        return [dict(s) for s in self._sources]

    def meta(self):
        return {"provider": self.name, "label": self.label,
                "n": len(self._sources), "비고": "실측 센서 아님 — 예시 설정값"}


class SensorFeedProvider(FireSourceProvider):
    """실제 화재·가스 감지 센서 피드 어댑터 (연동 준비 스텁).

    연동 시 해야 할 일은 두 가지뿐이다.
      1) `poll()` 에서 현장 게이트웨이/관제 API 응답(JSON)을 받아온다.
      2) `normalize()` 가 그 응답을 이 모듈의 표준 발생원 dict 로 바꾼다.
    나머지(위험 보정·QUBO·UI 표시)는 이미 표준 dict 기준으로 동작한다.

    센서에서 반경이 오지 않는 경우가 많으므로 kind 별 기본 반경을 둔다
    (설비 담당자 확인 후 조정할 값).
    """
    name = "sensor_feed"
    DEFAULT_RADIUS_M = {"fire": 10.0, "gas_leak": 15.0, "smoke": 12.0}

    def __init__(self, endpoint=None, timeout_s=5.0, radius_overrides=None):
        self.endpoint = endpoint
        self.timeout_s = timeout_s
        self.radius_m = dict(self.DEFAULT_RADIUS_M, **(radius_overrides or {}))

    def poll(self):
        """현장 API 호출부. 실제 엔드포인트가 정해지면 여기만 구현한다."""
        raise NotImplementedError(
            "센서 피드 미연동. 엔드포인트·인증·응답 스키마 확정 후 poll() 을 구현할 것. "
            "현재 데모는 ManualProvider(예시 설정)를 쓴다.")

    def normalize(self, payload):
        """센서 응답 → 표준 발생원 리스트. 필드명은 연동 규격 확정 시 매핑만 바꾼다.

        기대 형태(예): [{"sensor_id": "FD-12", "type": "fire", "x": 19.0, "y": 6.0,
                        "level": 0.8, "radius": 12.0, "ts": "202607271030"}]
        """
        out = []
        for i, r in enumerate(payload or []):
            kind = {"fire": "fire", "gas": "gas_leak", "gas_leak": "gas_leak",
                    "smoke": "smoke"}.get(str(r.get("type", "fire")).lower(), "fire")
            out.append(make_source(
                r.get("sensor_id") or f"SENSOR{i + 1}",
                x_m=r.get("x"), y_m=r.get("y"),
                radius_m=r.get("radius") or self.radius_m.get(kind, 10.0),
                kind=kind, intensity=float(r.get("level", 1.0)),
                origin="sensor", tm=r.get("ts")))
        return out

    def get_sources(self):
        return resolve_sources(self.normalize(self.poll()))


# ── 프리셋 설정 파일 ─────────────────────────────────────────────────────────
def load_config(path=CONFIG_PATH):
    """config/fire_scenarios.json 로드. 없으면 빈 설정."""
    if not os.path.exists(path):
        return {"default": None, "presets": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_presets(path=CONFIG_PATH):
    cfg = load_config(path)
    return cfg.get("presets", {})


def get_provider(spec=None, zones=None, path=CONFIG_PATH):
    """시나리오 지정자 → 공급자.

    spec:
      None / "" / "none"  → 발생원 없음 (기존 등방 실험과 동일)
      "<프리셋 이름>"      → config/fire_scenarios.json 의 프리셋
      list[dict]          → 직접 준 발생원 목록 (UI 요청 등)
    """
    if not spec or spec in ("none", "off", "미적용"):
        return ManualProvider([], label="none")
    if isinstance(spec, (list, tuple)):
        return ManualProvider(resolve_sources(spec, zones), label="request")
    cfg = load_config(path)
    presets = cfg.get("presets", {})
    if spec not in presets:
        raise KeyError(f"알 수 없는 화재 시나리오 프리셋: {spec!r} "
                       f"(사용 가능: {', '.join(presets) or '없음'})")
    p = presets[spec]
    srcs = resolve_sources(p.get("sources", []), zones, strict=True)
    for s in srcs:
        s.setdefault("origin", "preset")
    return ManualProvider(srcs, label=spec)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import data_loader as dl
    zones = dl.load_zones()
    name = sys.argv[1] if len(sys.argv) > 1 else None
    if name in (None, "--list"):
        print("사용 가능한 화재 시나리오 프리셋:")
        for k, v in list_presets().items():
            print(f"  - {k}: {v.get('설명', '')}")
        print("\n적용 예시: python src/fire_scenario.py 특수가스_배관실_누출")
        sys.exit(0)
    prov = get_provider(name, zones)
    srcs = prov.get_sources()
    print(describe(srcs))
    print("영향 구역(배수 ≥1.05):", ", ".join(affected_zones(zones, srcs)) or "없음")
    for z in sorted(zones):
        m = hazard_multiplier((zones[z]["cx"], zones[z]["cy"]), srcs)
        if m > 1.0:
            print(f"  {z} ({zones[z]['name']}): ×{m:.3f}")
