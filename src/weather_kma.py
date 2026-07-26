# -*- coding: utf-8 -*-
"""기상청 API 허브 지상관측(kma_sfctm2) 풍속·풍향 로더 — PM 지시 2026-07-26

보안 규칙(Codex 합의): 인증키는 문서·코드에 기록하지 않고 환경변수 KMA_API_KEY 로만 전달.

사용법 (네트워크 가능한 로컬 환경에서):
    set KMA_API_KEY=<키>          (Windows)  /  export KMA_API_KEY=<키>  (mac·linux)
    python src/weather_kma.py [tm(YYYYMMDDHHMM)] [stn]
→ Data/06_weather/kma_wind_latest.csv 에 캐시 저장.
파이프라인(run_experiment.py)은 캐시가 있으면 자동 반영, 없으면 기상 보정 없이 실행.

한계(발표 명시): 관측소 지점값(기본 108 서울)을 현장 대표값으로 가정.
WD 단위는 API help=1 기준 degree로 가정 — 실데이터 수신 후 1회 검증 필요.
"""
import csv
import os
import sys
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_loader  # noqa: F401 — .env의 KMA_API_KEY 자동 주입

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data")
CACHE_PATH = os.path.join(DATA_DIR, "06_weather", "kma_wind_latest.csv")
BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
DEFAULT_STN = "108"  # 서울 관측소 (현장 인근 지점으로 교체 가능)
MISSING = {-9.0, -99.0, -999.0}


def parse_sfctm2(text):
    """sfctm2 텍스트 응답 파싱. 컬럼: TM STN WD WS ... (# 시작 줄은 헤더/도움말)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) < 4:
            continue
        try:
            wd, ws = float(p[2]), float(p[3])
        except ValueError:
            continue
        if wd in MISSING or ws in MISSING:
            continue
        out.append({"tm": p[0], "stn": p[1], "wd_deg": wd, "ws_ms": ws})
    return out


def fetch_and_cache(tm=None, stn=DEFAULT_STN):
    """API 호출 후 캐시 저장. 반환: 관측 dict 또는 None."""
    key = os.environ.get("KMA_API_KEY")
    if not key:
        raise RuntimeError("환경변수 KMA_API_KEY 가 설정되어 있지 않습니다 (키를 파일에 쓰지 말 것).")
    if tm is None:
        tm = (datetime.now() - timedelta(hours=1)).strftime("%Y%m%d%H00")
    url = f"{BASE_URL}?tm={tm}&stn={stn}&help=0&authKey={key}"
    raw = urllib.request.urlopen(url, timeout=15).read()
    for enc in ("euc-kr", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = parse_sfctm2(text)
    if not rows:
        print("경고: 파싱된 관측값 없음 — 응답 원문 확인 필요")
        return None
    obs = rows[0]
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tm", "stn", "wd_deg", "ws_ms"])
        w.writeheader()
        w.writerow(obs)
    print(f"캐시 저장: {CACHE_PATH} → tm={obs['tm']} stn={obs['stn']} "
          f"풍향={obs['wd_deg']}° 풍속={obs['ws_ms']}m/s")
    return obs


def load_cached_weather():
    """캐시된 최신 풍속·풍향 반환. 없으면 None (파이프라인은 보정 없이 진행)."""
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    r = rows[0]
    return {"tm": r["tm"], "stn": r["stn"],
            "wd_deg": float(r["wd_deg"]), "ws_ms": float(r["ws_ms"])}


if __name__ == "__main__":
    tm = sys.argv[1] if len(sys.argv) > 1 else None
    stn = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_STN
    fetch_and_cache(tm, stn)
