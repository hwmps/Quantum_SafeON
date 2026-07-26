# P5 IonQ Aria/Forte 노이즈 파라미터

## 결론

- Aria 공식 공개 평균: 1Q error 0.05%, 2Q error 0.4%, SPAM 0.39%, T1 10–100 s, T2 약 1 s, 1Q 135 µs, 2Q 600 µs.
- Forte 공식 공개 평균: 1Q error 0.02%, 2Q error 0.4%, SPAM 0.5%, T1/T2 표기 10–100 s / 약 1 s.
- 공식 페이지는 장치 전체의 평균 요약값이다. 큐비트별·쌍별 분포, 상관오류, 드리프트, 누화, amplitude/phase damping 채널 파라미터를 제공하지 않는다.

## Noisy Simulator 판단

이 값만으로 Aria/Forte를 충실하게 재현하는 노이즈 모델을 만들 수 없다. 단순 depolarizing + readout 모델을 만들 경우 반드시 “공식 평균 오류율을 사용한 교육용 근사모델”로 표시하고 실제 QPU 예측 모델이라고 주장하지 않는다. 본선 우선순위는 다음이 안전하다.

1. Ideal simulator에서 Exact와 QAOA 정합성 확인.
2. 실제 대회 계정에서 transpilation 후 큐비트 수·깊이·2Q gate 수 기록.
3. Real QPU 결과와 calibration metadata가 제공될 때 그 시점의 값으로 오류 분석.
4. Noisy simulation은 민감도 분석(예: 공식 평균의 0.5×, 1×, 2×)으로 제한.

## 출처·이용 조건

- IonQ Aria 공식 자료: https://www.ionq.com/resources/ionq-aria-practical-performance
- IonQ Forte 공식 제품 페이지: https://www.ionq.com/quantum-systems/forte
- 확인일: 2026-07-26.
- IonQ 저작권 자료이므로 페이지를 복제하지 않고 수치와 URL만 기록했다.
- 장비 성능은 교정·운영 구성·공개 페이지 갱신에 따라 달라질 수 있다. 실행 시점의 provider metadata가 우선이다.
