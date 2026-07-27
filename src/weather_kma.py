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
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env_loader  # noqa: F401 — .env의 KMA_API_KEY 자동 주입

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data")
CACHE_PATH = os.path.join(DATA_DIR, "06_weather", "kma_wind_latest.csv")
SERIES_PATH = os.path.join(DATA_DIR, "06_weather", "kma_wind_timeseries.csv")
SERIES_META_PATH = os.path.join(DATA_DIR, "06_weather", "kma_wind_timeseries_meta.json")
DIAG_PATH = os.path.join(DATA_DIR, "06_weather", "kma_fetch_diagnosis.json")
BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
SERIES_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"  # 기간조회(tm1~tm2)
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


# ── D3 기간조회 시계열 + 오류 원인 분류 (PM 지시 2026-07-27: 키 재발급 후 재실험) ──
# 배경: 2026-07-26 Codex 보고에서 기간조회가 403으로 차단되었고 PM은 키를 재발급했다.
# 403은 원인이 여러 가지이므로(샌드박스 egress 차단 / 인증키 오류 / 활용신청 미승인)
# 아래 classify_error()로 구분해 기록한다. 관측값은 절대 합성하지 않는다.

def classify_error(exc):
    """네트워크 예외를 원인별로 분류. 반환: (원인코드, 사람이 읽는 설명)."""
    s = str(exc)
    if isinstance(exc, urllib.error.URLError) and "Tunnel connection failed" in s:
        return ("EGRESS_BLOCKED",
                "실행 환경(샌드박스) 프록시가 apihub.kma.go.kr 로의 외부 접속을 차단했다. "
                "기상청 인증키 문제가 아니며, 네트워크가 열린 로컬 PC에서 동일 명령을 실행해야 한다.")
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return (f"KMA_HTTP_{code}",
                "기상청 서버가 인증 거부를 반환했다. 인증키 문자열과 "
                "API허브 '지상관측 시간자료(기간 조회)' 활용신청 승인 상태를 함께 확인해야 한다.")
    if code == 429:
        return ("KMA_RATE_LIMIT", "호출 한도 초과. 잠시 후 재시도한다.")
    if code:
        return (f"KMA_HTTP_{code}", "기상청 서버가 오류를 반환했다.")
    return ("NETWORK_ERROR", "네트워크 오류로 응답을 받지 못했다.")


def _get_key():
    key = os.environ.get("KMA_API_KEY")
    if not key:
        raise RuntimeError("환경변수 KMA_API_KEY 가 설정되어 있지 않습니다 (키를 파일에 쓰지 말 것).")
    return key


def _fetch_text(url):
    raw = urllib.request.urlopen(url, timeout=20).read()
    for enc in ("euc-kr", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _write_diagnosis(mode, url_no_key, cause, detail):
    """실패 원인을 파일로 남긴다. 인증키는 절대 기록하지 않는다."""
    os.makedirs(os.path.dirname(DIAG_PATH), exist_ok=True)
    with open(DIAG_PATH, "w", encoding="utf-8") as f:
        json.dump({"시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "모드": mode, "요청": url_no_key,
                   "원인코드": cause, "설명": detail,
                   "비고": "관측값을 합성하지 않았다. 인증키는 기록하지 않는다."},
                  f, ensure_ascii=False, indent=2)
    print(f"진단 저장: {DIAG_PATH} → {cause}")


def fetch_timeseries(tm1, tm2, stn=DEFAULT_STN):
    """D3 정본: 기간조회로 풍향·풍속 시계열을 받아 CSV로 저장.

    tm1, tm2: YYYYMMDDHHMM (기상청 KST). 성공 시 관측 리스트, 실패 시 None을 반환하고
    실패 원인은 Data/06_weather/kma_fetch_diagnosis.json 에 기록한다.
    """
    key = _get_key()
    url = f"{SERIES_URL}?tm1={tm1}&tm2={tm2}&stn={stn}&help=0&authKey={key}"
    url_no_key = url.replace(key, "<KMA_API_KEY>")
    try:
        text = _fetch_text(url)
    except Exception as e:  # noqa: BLE001 — 원인 분류 후 그대로 보고
        cause, detail = classify_error(e)
        _write_diagnosis("기간조회(kma_sfctm3)", url_no_key, cause, detail)
        return None
    rows = parse_sfctm2(text)
    if not rows:
        _write_diagnosis("기간조회(kma_sfctm3)", url_no_key, "EMPTY_RESPONSE",
                         "응답에 유효한 관측 행이 없다. 기간·지점 번호와 활용신청 범위를 확인해야 한다.")
        return None
    os.makedirs(os.path.dirname(SERIES_META_PATH), exist_ok=True)
    with open(SERIES_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"수집시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "수집방법": "기간조회(kma_sfctm3) 1회 호출",
                   "요청_기간": [tm1, tm2], "지점": stn, "확보_행수": len(rows),
                   "비고": "기상청 공식 관측. 합성·보간 없음."}, f, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(SERIES_PATH), exist_ok=True)
    with open(SERIES_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tm", "stn", "wd_deg", "ws_ms"])
        w.writeheader()
        w.writerows(rows)
    print(f"시계열 저장: {SERIES_PATH} → {len(rows)}행 ({rows[0]['tm']}~{rows[-1]['tm']})")
    return rows


def _hour_range(tm1, tm2):
    """tm1~tm2(YYYYMMDDHHMM)를 정시 단위로 순회."""
    t = datetime.strptime(tm1[:10] + "00", "%Y%m%d%H%M")
    end = datetime.strptime(tm2[:10] + "00", "%Y%m%d%H%M")
    while t <= end:
        yield t.strftime("%Y%m%d%H00")
        t += timedelta(hours=1)


def fetch_timeseries_hourly(tm1, tm2, stn=DEFAULT_STN, sleep_s=0.3):
    """승인된 단일시각 조회(kma_sfctm2)를 정시마다 반복해 D3 시계열을 조립한다.

    배경(2026-07-27 확인): 재발급 키로 단일시각 조회는 정상 동작하지만 기간조회
    (kma_sfctm3)는 활용신청 미승인으로 HTTP 403이다. 기간조회 승인 없이도 D3를
    확보하기 위한 우회 경로이며, 값 자체는 동일한 공식 관측이라 합성이 아니다.

    일부 시각이 실패해도 성공한 시각만 저장하고 결손 시각을 메타에 기록한다.
    """
    import time
    key = _get_key()
    rows, failed = [], []
    hours = list(_hour_range(tm1, tm2))
    for i, tm in enumerate(hours):
        url = f"{BASE_URL}?tm={tm}&stn={stn}&help=0&authKey={key}"
        try:
            got = parse_sfctm2(_fetch_text(url))
        except Exception as e:  # noqa: BLE001
            cause, detail = classify_error(e)
            if cause in ("EGRESS_BLOCKED", "KMA_HTTP_401", "KMA_HTTP_403"):
                # 인증·환경 차원의 차단이면 전체가 동일하게 실패하므로 즉시 중단한다.
                _write_diagnosis("시간별 반복(kma_sfctm2 루프)",
                                 f"{BASE_URL}?tm={tm}&stn={stn}&help=0&authKey=<KMA_API_KEY>",
                                 cause, detail)
                return None
            failed.append({"tm": tm, "원인": cause})
            continue
        if got:
            rows.append(got[0])
        else:
            failed.append({"tm": tm, "원인": "EMPTY_OR_MISSING"})
        if sleep_s and i < len(hours) - 1:
            time.sleep(sleep_s)
    if not rows:
        _write_diagnosis("시간별 반복(kma_sfctm2 루프)", f"tm1={tm1} tm2={tm2} stn={stn}",
                         "EMPTY_RESPONSE", "요청한 모든 시각에서 유효 관측을 얻지 못했다.")
        return None
    rows.sort(key=lambda r: r["tm"])
    os.makedirs(os.path.dirname(SERIES_PATH), exist_ok=True)
    with open(SERIES_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tm", "stn", "wd_deg", "ws_ms"])
        w.writeheader()
        w.writerows(rows)
    with open(SERIES_META_PATH, "w", encoding="utf-8") as f:
        json.dump({"수집시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "수집방법": "단일시각 조회(kma_sfctm2) 정시 반복 — 기간조회 활용신청 미승인 우회",
                   "요청_기간": [tm1, tm2], "지점": stn,
                   "요청_시각수": len(hours), "확보_행수": len(rows),
                   "결손_시각": failed,
                   "비고": "값은 기상청 공식 관측이며 합성·보간하지 않았다. 결손 시각은 채우지 않았다."},
                  f, ensure_ascii=False, indent=2)
    print(f"시계열 저장: {SERIES_PATH} → {len(rows)}/{len(hours)}행 "
          f"({rows[0]['tm']}~{rows[-1]['tm']}), 결손 {len(failed)}개")
    return rows


def load_cached_timeseries():
    """저장된 D3 시계열 반환. 없으면 None."""
    if not os.path.exists(SERIES_PATH):
        return None
    with open(SERIES_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [{"tm": r["tm"], "stn": r["stn"],
                 "wd_deg": float(r["wd_deg"]), "ws_ms": float(r["ws_ms"])}
                for r in csv.DictReader(f)]
    return rows or None


def summarize_timeseries(rows=None):
    """시계열 → 파이프라인용 대표값. 보수적 설계를 위해 풍속 상위 분위를 쓴다.

    반환: {"대표_풍속_m_s": p90, "최다_풍향_deg": 최빈 16방위 중앙값, "n": 행수, ...}
    """
    rows = rows if rows is not None else load_cached_timeseries()
    if not rows:
        return None
    ws = sorted(r["ws_ms"] for r in rows)
    idx = max(0, min(len(ws) - 1, int(round(0.9 * (len(ws) - 1)))))
    bins = {}
    for r in rows:
        b = int((r["wd_deg"] % 360) // 22.5)
        bins[b] = bins.get(b, 0) + 1
    top = max(bins, key=lambda b: bins[b])
    return {"n": len(rows), "기간": [rows[0]["tm"], rows[-1]["tm"]], "stn": rows[0]["stn"],
            "평균_풍속_m_s": round(sum(ws) / len(ws), 2),
            "대표_풍속_m_s": round(ws[idx], 2), "최대_풍속_m_s": round(ws[-1], 2),
            "최다_풍향_deg": round(top * 22.5 + 11.25, 1),
            "산정근거": "대표 풍속은 90퍼센타일(보수적 설계값), 최다 풍향은 16방위 최빈 구간 중앙값"}


def representative_weather():
    """파이프라인이 쓸 기상 입력 1건. 우선순위: D3 시계열 대표값 > 단일시각 캐시 > None.

    시계열이 있으면 보수적 설계값(풍속 90퍼센타일, 최다 풍향)을 쓴다. 단일 시각 관측은
    우연히 정온인 시각을 대표값으로 삼을 위험이 있어 시계열이 있을 때는 사용하지 않는다.
    반환 dict에는 출처를 함께 담아 결과 meta 에 그대로 기록할 수 있게 한다.
    """
    s = summarize_timeseries()
    if s:
        return {"wd_deg": s["최다_풍향_deg"], "ws_ms": s["대표_풍속_m_s"],
                "출처": "D3 관측 시계열 대표값(풍속 90퍼센타일·최다 풍향)",
                "기간": s["기간"], "stn": s["stn"], "n": s["n"],
                "평균_풍속_m_s": s["평균_풍속_m_s"], "최대_풍속_m_s": s["최대_풍속_m_s"]}
    w = load_cached_weather()
    if w:
        w = dict(w)
        w["출처"] = "단일시각 관측 캐시 (시계열 미확보 — 대표성 한계 있음)"
        return w
    return None


def _usage():
    print("사용법:\n"
          "  python src/weather_kma.py                      # 최신 1시각 관측 캐시\n"
          "  python src/weather_kma.py <tm> [stn]           # 특정 시각 관측 캐시\n"
          "  python src/weather_kma.py --range <tm1> <tm2> [stn]   # D3 시계열 (403이면 자동 폴백)\n"
          "  python src/weather_kma.py --range-hourly <tm1> <tm2> [stn]  # 단일시각 정시 반복만 사용\n"
          "  python src/weather_kma.py --summary            # 저장된 시계열 대표값 출력\n"
          "  tm 형식: YYYYMMDDHHMM (KST). 인증키는 .env 의 KMA_API_KEY 에서만 읽는다.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        _usage()
    elif args and args[0] == "--summary":
        s = summarize_timeseries()
        print(json.dumps(s, ensure_ascii=False, indent=2) if s
              else f"저장된 시계열이 없다: {SERIES_PATH}")
    elif args and args[0] in ("--range", "--range-hourly"):
        if len(args) < 3:
            _usage()
            sys.exit(2)
        tm1, tm2 = args[1], args[2]
        stn = args[3] if len(args) > 3 else DEFAULT_STN
        if args[0] == "--range-hourly":
            rows = fetch_timeseries_hourly(tm1, tm2, stn)
        else:
            rows = fetch_timeseries(tm1, tm2, stn)
            # 기간조회 활용신청 미승인(403)이면 승인된 단일시각 조회 반복으로 자동 폴백.
            if rows is None and os.path.exists(DIAG_PATH):
                with open(DIAG_PATH, encoding="utf-8") as f:
                    cause = json.load(f).get("원인코드", "")
                if cause in ("KMA_HTTP_403", "KMA_HTTP_401"):
                    print(f"기간조회 거부({cause}) → 승인된 단일시각 조회를 정시마다 반복해 대체 수집한다.")
                    rows = fetch_timeseries_hourly(tm1, tm2, stn)
        if rows:
            print(json.dumps(summarize_timeseries(rows), ensure_ascii=False, indent=2))
        else:
            sys.exit(1)
    else:
        tm = args[0] if args else None
        stn = args[1] if len(args) > 1 else DEFAULT_STN
        key = _get_key()
        try:
            fetch_and_cache(tm, stn)
        except Exception as e:  # noqa: BLE001
            cause, detail = classify_error(e)
            _write_diagnosis("단일시각(kma_sfctm2)",
                             f"{BASE_URL}?tm={tm}&stn={stn}&help=0&authKey=<KMA_API_KEY>",
                             cause, detail)
            sys.exit(1)
