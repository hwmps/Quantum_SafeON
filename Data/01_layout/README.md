# P1 반도체 건설현장 참조 레이아웃

## 산출물 성격

`reference_layout.svg`, `zone_graph.csv`, `sensor_candidates_12.csv`는 실제 사업장 도면이 아니라 공개 자료에 나타난 팹의 기능 구성을 바탕으로 만든 60 m × 40 m **연구용 합성 레이아웃**이다. QUBO/그래프 파이프라인 착수용이며 안전설계·인허가에 사용할 수 없다.

## 근거

- Semiconductor Industry Association, *Background on Semiconductor Manufacturing and PFAS* (2023): 현대 팹은 cleanroom, clean subfab, utility level, interstitial/fan deck으로 구성되고 subfab에는 펌프·배관·덕트가 배치된다고 설명하고 예시 단면을 제공한다.  
  https://www.semiconductors.org/wp-content/uploads/2023/05/FINAL-PFAS-Consortium-Background-Paper.pdf
- NIST Boulder Microfabrication Facility: 가스 캐비닛 배기, 공정장비 배기, 장비 위 주변공기에서 독성가스를 감시하며 silane/ammonia scrubber와 질소탱크를 운영한다고 설명한다.  
  https://www.nist.gov/pml/boulder-microfabrication-facility-tools-capabilities-and-infrastructure
- NIST semiconductor fab modernization environmental assessment: 건설단계 임시 저장물로 용접가스, 도료, 접착제, 희석제, 용제 등을 열거하고 누출·화재 위험을 설명한다.  
  https://www.nist.gov/system/files/documents/2024/06/28/Final%20PEA%20for%20Modernization%20and%20Expansion%20of%20Semiconductor%20Fabs%206-28-2024%20-%20OGC-508C.pdf
- OSHA semiconductor device fabrication: CVD 공정의 silane, ammonia, hydrogen 등 인화성·폭발성·독성 가스 위험을 설명한다.  
  https://www.osha.gov/semiconductors/silicon/device-fabrication

## 이용 조건과 한계

- 확인일: 2026-07-26.
- SIA 문서는 저작권이 명시되어 있어 원 그림을 복제하지 않고 링크와 사실관계만 사용했다.
- NIST·OSHA는 미국 연방기관 자료이나 각 페이지의 제3자 콘텐츠는 별도 권리가 있을 수 있다.
- 공개 자료는 완공된 팹의 기능 단면 위주다. 건설 중 실제 벽체, 가설통로, 풍향, 높이, 공조 가동 상태는 반영되지 않았다.
- `x_m`, `y_m`, 크기, 인접관계 및 12개 후보점은 검증 가능한 합성값이다. 실제 BIM/CAD를 받으면 동일 스키마로 교체한다.

## 부분 커버리지 개선본

- 정본: `QRC2026_fractional_coverage_matrix_v1.xlsx`
- 코드용 보조본: `coverage_matrix_fractional_excel_utf8.csv` (UTF-8 BOM)
- 기존 `coverage_matrix_detailed_excel_utf8.csv`는 구역 중심거리 기준 0/1 판정의 이전 버전으로 보존한다.
- 새 개선본은 센서 원과 직사각형 구역의 교집합 면적을 구역 면적으로 나눈 0~1 값을 사용한다. 후보 12개 × 구역 12개의 144행과 기존 17열 스키마를 유지한다.
- 새 개선본은 커버리지 데이터만 대체하며 `Data/00_master/QRC2026_detailed_research_data.xlsx`의 다른 P1~P5 자료를 대체하지 않는다.
- 센서 반경 3/5/8 m는 제조사 보편 성능값이 아니라 기존 민감도 분석 가정이다. 결과는 현장 실측 커버리지로 표현하지 않는다.
