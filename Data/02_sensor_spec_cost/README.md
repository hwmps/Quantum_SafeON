# P2 센서 사양·비용 데이터

## 바로 사용할 열

- `equipment_cost_krw_approx`: 공개된 미국 판매가에 **계획용 환율 1 USD = 1,400 KRW**를 곱한 장비가 근사치다. 환율·부가세·운임·관세·방폭/국내인증·제어반·배선·교정·시공비는 포함하지 않았다.
- `qbo_radius_low/nominal/high_m`: 가스 점감지기에 공식 “커버리지 반경”이 없으므로 제품 사양이 아니라 2/4/6 m 등의 **민감도 분석용 가정**이다.
- `manufacturer_spacing_m`: System Sensor 2151의 평활천장 30 ft 가이드만 수치가 있다. 실제 간격은 천장 높이, 공기 흐름, 구조물, 국내 NFPC/NFTC 및 형식승인에 따라 달라진다.

## 중요한 해석

가스 감지기는 누출원·풍향·환기·가스 비중에 따라 배치하는 점감지/흡입식 장치다. 따라서 하나의 고정 원형 반경을 실제 성능으로 주장하면 안 된다. QUBO에서는 반경 시나리오를 바꿔 해의 안정성을 보고, 실제 적용 단계에서는 CFD 또는 가스 매핑과 현장 위험성평가로 커버리지 행렬을 다시 산정해야 한다.

## 출처·이용 조건

- 제조사 사양: Honeywell/System Sensor 공식 PDF. 저작권 자료이므로 재배포하지 않고 URL과 제한된 사실값만 표에 기록했다.
- 가격: SupplyHouse, ReScience, JJS Technical Services의 공개 상품 페이지. 가격은 2026-07-26 확인 스냅샷이며 판매조건·재고·구성에 따라 변한다.
- MIDAS S2 silane 카트리지 공개가 근거: https://www.e-controls.net/honeywell-analytics-midas-e-shl-sensor-cartridge.html
- 설치비는 공개된 동일 범위 국내 견적을 검증하지 못해 `NA`로 남겼다. PM이 국내 공급사 2곳 이상에 같은 BOM으로 견적을 요청해야 비교 가능하다.
