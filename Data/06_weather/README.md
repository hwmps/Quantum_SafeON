# 기상청 풍속·풍향 데이터

## 상태

- 2026-07-26 기준 실제 관측 캐시는 아직 생성하지 않았다.
- 이유: 자동화는 문서에 노출된 API 키를 사용하거나 외부로 전송하지 않는다.
- PM은 노출된 키를 재발급한 뒤 로컬 환경변수 `KMA_API_KEY`로만 제공해야 한다.

## 수집 방법

```powershell
$env:KMA_API_KEY="<재발급한 키>"
.\.venv\Scripts\python.exe src\weather_kma.py
```

수집 성공 시 `Data/06_weather/kma_wind_latest.csv`가 UTF-8 BOM CSV로 생성된다.

## 스키마

| 열 | 정의 | 단위 | 필수 |
|---|---|---|---|
| `tm` | 관측 시각 | `YYYYMMDDHHMM` | 예 |
| `stn` | 기상청 관측소 번호 | 코드 | 예 |
| `wd_deg` | 풍향 | degree(가정, 최초 수신 시 확인) | 예 |
| `ws_ms` | 풍속 | m/s | 예 |

## 출처·이용 조건·한계

- 출처: 기상청 API 허브 지상관측 `kma_sfctm2`
- 원문 URL: https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php
- 확인일: 2026-07-26
- 이용 조건: 실제 사용 전 기상청 API 허브의 신청 서비스 이용 조건과 재배포 조건을 확인한다.
- 기본 관측소 `108`(서울)의 지점 관측값을 현장 대표값으로 쓰는 것은 모델링 가정이다. 실제 현장 위치가 확정되면 인접 관측소로 교체해야 한다.
- `wd_deg` 단위는 API 도움말 기준 degree로 해석하도록 구현돼 있으나, 최초 실데이터 수신 시 응답 헤더와 값 범위를 대조해야 한다.

