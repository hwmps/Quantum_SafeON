# 기상청 풍속·풍향 데이터

## 상태 — 확보 완료 (2026-07-27 15:54 PM 재점검, 상태 절 갱신: Claude)

> 아래 상태·대표값·파일 목록은 2026-07-27 확보분 기준으로 갱신했다. 스키마·출처 절은 Codex 원문 유지.

기상청 API허브 지상관측 3종이 모두 정상이며, **공식 관측만** 저장한다(합성·보간·결측 대체 없음).

| API | 용도 | 상태 |
|---|---|---|
| `kma_sfctm2` 단일시각 조회 | 최신 1시각 관측 캐시 | 성공 |
| `kma_sfctm3` 시간별 기간조회 | 시계열 1회 수집(정시 25회 반복 불필요) | 성공 |
| `kma_sfcdd3` 일자별 기간조회 | 일평균·일최대 풍속 | 성공 |

인증키는 로컬 `.env` 의 `KMA_API_KEY` 환경변수에서만 읽고, 산출물·로그·문서에 기록하지 않는다. `kma_api_status.json` 의 요청 URL도 `authKey=<KMA_API_KEY>` 로 마스킹해 저장한다.

### 파이프라인이 쓰는 대표값 (`src/weather_kma.py` → `representative_weather()`)

| 항목 | 값 |
|---|---|
| 대표 풍속 (90퍼센타일, 보수적 설계값) | **3.8 m/s** |
| 평균 / 최대 풍속 | 2.54 / 4.3 m/s |
| 최다 풍향 (16방위 최빈 구간 중앙값) | **33.8°** (북동) → 연기 이동 방향 남서 |
| 관측소 / 행수 / 기간 | 108(서울) / 25행 / 2026-07-26 00시 ~ 07-27 00시 |

우선순위는 **시계열 대표값 > 단일시각 캐시 > 미반영(None)** 이다. 단일 시각 관측은 우연히 정온인 시각을 대표값으로 삼을 위험이 있어 시계열이 있으면 쓰지 않는다.

## 수집 방법

```powershell
$env:KMA_API_KEY="<발급받은 키>"
.\.venv\Scripts\python.exe src\weather_kma.py                                    # 최신 1시각 관측 캐시
.\.venv\Scripts\python.exe src\weather_kma.py --range 202607260000 202607270000  # 시간 시계열
.\.venv\Scripts\python.exe src\weather_kma.py --daily 20260720 20260727          # 일자료
.\.venv\Scripts\python.exe src\weather_kma.py --recheck                          # API 3종 상태 재점검
.\.venv\Scripts\python.exe src\weather_kma.py --summary                          # 저장된 시계열 대표값
```

### 파일

| 파일 | 내용 |
|---|---|
| `kma_wind_timeseries.csv` / `_meta.json` | 시간 관측 시계열(25행)과 수집 메타 — **파이프라인 기본 입력** |
| `kma_wind_daily.csv` / `_meta.json` | 일 관측(7행, 일평균·일최대 풍속과 최대풍속 시 풍향) |
| `kma_wind_latest.csv` | 최신 1시각 관측 캐시 (시계열 미확보 시 폴백), UTF-8 BOM CSV |
| `kma_api_status.json` | API 3종 재점검 결과 (키 마스킹) |
| `kma_daily_raw_head.txt` | 일자료 응답 원문 머리부 — 번호형 범례(`#N. 컬럼명`) 파서 검증 근거 |
| `kma_fetch_diagnosis.json` | 수집 실패 진단. 초기 파서 오류는 `RECOVERED` 로 해소됨 |

### 진단 코드

| 원인코드 | 뜻 | 조치 |
|---|---|---|
| `EGRESS_BLOCKED` | 실행 환경이 외부 접속 차단 | 네트워크가 열린 PC에서 실행 |
| `KMA_HTTP_403` / `401` | 기상청 인증 거부 | 키 확인 + 해당 API 활용신청 승인 확인 |
| `EMPTY_RESPONSE` | 응답에 유효 관측 없음 | 기간·지점번호 확인 |
| `SCHEMA_UNRESOLVED` | 응답 헤더 해석 실패 | 값을 추측해 채우지 않고 실패로 남긴다 |

## 스키마

| 열 | 정의 | 단위 | 필수 |
|---|---|---|---|
| `tm` | 관측 시각 | `YYYYMMDDHHMM` | 예 |
| `stn` | 기상청 관측소 번호 | 코드 | 예 |
| `wd_deg` | 풍향 | degree(가정, 최초 수신 시 확인) | 예 |
| `ws_ms` | 풍속 | m/s | 예 |

## 출처·이용 조건·한계

- 출처: 기상청 API 허브 지상관측 `kma_sfctm2`(단일시각) · `kma_sfctm3`(시간 기간조회) · `kma_sfcdd3`(일 기간조회)
- 원문 URL: https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php · https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php · https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php
- 확인일: 2026-07-26 (시간·일 기간조회 확인일 2026-07-27)
- 이용 조건: 실제 사용 전 기상청 API 허브의 신청 서비스 이용 조건과 재배포 조건을 확인한다.
- 기본 관측소 `108`(서울)의 지점 관측값을 현장 대표값으로 쓰는 것은 모델링 가정이다. 실제 현장 위치가 확정되면 인접 관측소로 교체해야 한다.
- `wd_deg` 단위는 API 도움말 기준 degree로 해석하도록 구현돼 있으나, 최초 실데이터 수신 시 응답 헤더와 값 범위를 대조해야 한다.

