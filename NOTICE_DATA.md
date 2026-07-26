# 데이터 출처·라이선스 고지

이 저장소에 포함된 데이터는 공개 출처의 **사실값과 요약**, 그리고 그로부터 계산한 **파생·합성 데이터**다. 제조사·기관 원문은 재배포하지 않으며 출처 URL과 확인일을 각 파일에 기록했다.

## 1. 저장소에 포함된 데이터

| 경로 | 내용 | 성격 | 주요 출처 |
|---|---|---|---|
| `Data/01_layout/` | 60×40 m 합성 레이아웃, 12구역·12후보, 부분면적 커버리지 행렬 | **합성·파생** (실제 도면 아님) | SIA·NIST 팹 기능구성 배경 |
| `Data/02_sensor_spec_cost/` | 화재·가스 감지기 사양과 공개 판매가 | 사실값 + 환산(1 USD=1,400 KRW 계획환율) | System Sensor, Honeywell, MIDAS 제조사 공개 사양 |
| `Data/03_incident_scenarios/` | 화재·가스 사고 조사 사례 요약 | 사실값 요약 (소표본) | KOSHA, OSHA, CSB, NIST |
| `Data/04_legal_criteria/` | 감지기 설치 법적 기준 | 조문 요약 | 국가법령정보센터(산업안전보건기준에 관한 규칙, 고용노동부고시, NFPC 203) |
| `Data/05_ionq_noise/` | IonQ Aria/Forte 오류율·T1/T2 | 공식 공개 평균값 | IonQ 공식 문서 |
| `Data/06_weather/` | 기상청 풍향·풍속 관측 캐시 | 실측 | 기상청 API허브 |
| `Data/07_quantum_environment/` | 양자 실행 환경 검증 기록 | 내부 산출물 | — |
| `Data/00_master/` | 위 자료의 통합 정본 워크북 | 정리본 | 위와 동일 |
| `Data/demo_plan/` | UI 데모용 평면도 1장 | 제3자 데이터셋 | **CubiCasa5K** (아래 참조) |

주요 출처 URL:

- 국가법령정보센터 https://www.law.go.kr/
- KOSHA https://oshri.kosha.or.kr/
- OSHA 사고 조사 https://www.osha.gov/
- NIST 반도체 팹 시설 https://www.nist.gov/pml/boulder-microfabrication-facility-tools-capabilities-and-infrastructure
- IonQ Aria https://www.ionq.com/resources/ionq-aria-practical-performance
- 기상청 API허브 https://apihub.kma.go.kr/

## 2. 제3자 데이터셋

### CubiCasa5K — 데모 평면도 1장 포함

- 출처: https://github.com/CubiCasa/CubiCasa5k · 데이터 https://zenodo.org/records/2613548 · 논문 https://arxiv.org/abs/1904.01920
- 라이선스: **CC BY-NC 4.0** (저작자 표시, 비상업적 이용) https://creativecommons.org/licenses/by-nc/4.0/
- 포함 범위: `Data/demo_plan/F1_scaled.png` — plan 5570 평면도 **1장만** 포함. 전체 데이터셋(5,000장)은 포함하지 않는다.
- 용도: UI 데모 기본 도면. **주거용 평면도이며 반도체 건설현장 자료가 아니다.**
- 상업적 이용 시 이 파일을 제거하고 자체 도면으로 교체해야 한다.

### Structured3D — 미포함

- 출처: https://structured3d-dataset.org/
- 이용약관 동의 후 개별 신청으로 제공되는 데이터셋이므로 **원자료와 그 파생 산출물을 이 저장소에 포함하지 않는다.**
- 프로젝트 내부에서는 2차 도메인 검증용으로만 사용한다.

### 대용량 원자료 미포함

CubiCasa5K 전체(약 6 GB)와 UI 테스트 코퍼스(약 2 GB)는 저장소 크기와 라이선스를 고려해 포함하지 않는다. 각 공식 배포처에서 직접 내려받아야 한다.

## 3. 재사용 시 반드시 함께 표기할 한계

- 레이아웃·후보점은 **합성**이며 실제 도면이 아니다 (`data_status` 열 확인).
- 감지 반경 3/5/8 m는 **민감도 분석용 가정**이지 제품 보증 성능이나 법정 기준이 아니다.
- 커버리지는 2D 등방 원형 근사이며 벽·천장고·공조·풍향 확산을 반영하지 않는다 (CFD 아님).
- 사고 사례는 소표본으로, 확률 학습 데이터가 아니라 규칙 기반 위험 점수의 근거로만 사용한다.
- 비용은 공개 장비가 기준이며 국내 시공비·배선·인증·세금은 `NA`다.
