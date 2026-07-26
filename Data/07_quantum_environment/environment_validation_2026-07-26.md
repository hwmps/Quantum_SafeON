# 양자 시뮬레이션 환경 구성·검증 보고

- 확인일: 2026-07-26
- 실행 환경: Windows, Python 3.13.1, 프로젝트 전용 `.venv`
- 목적: QUBO/QAOA Ideal Simulator와 Qiskit 기반 IonQ 제출 준비 환경의 재현 가능성 확인

## 설치된 직접 의존성

| 패키지 | 버전 | 용도 | 출처 | 이용 조건 |
|---|---:|---|---|---|
| NumPy | 2.5.1 | QUBO 행렬·상태벡터 계산 | https://numpy.org/ | 설치 패키지 메타데이터 및 프로젝트 라이선스 참조 |
| Qiskit | 2.5.1 | 양자 회로 생성·트랜스파일 | https://github.com/Qiskit/qiskit | Apache-2.0 |
| qiskit-ionq | 1.1.1 | IonQ 백엔드 연동 | https://github.com/qiskit-community/qiskit-ionq | Apache-2.0 |

정확한 직접 의존성은 루트 `requirements.txt`에 고정했다. 재구성은 `scripts/setup_quantum_env.cmd`로 수행한다.

## 검증 결과

1. `src/` 전체 Python 바이트코드 컴파일: 통과
2. `qiskit`, `qiskit_ionq`, `numpy` import: 통과
3. `src/qaoa_qiskit.py`의 12큐비트 QAOA 회로 생성: 통과
4. Qiskit `optimization_level=3` 트랜스파일 및 회로 지표 추출: 통과
5. `src/run_experiment.py` 전체 재실행: 통과
   - low/nominal/high 세 시나리오 실행 완료
   - QAOA p=2는 세 시나리오 모두 Exact 최적해 발견
   - low 시나리오 Z10은 최대 커버율 0.283으로 임계값 0.3에 구조적으로 미달하는 기존 경고 유지

## 인증·실기 QPU 범위

- IonQ API 호출·작업 제출은 수행하지 않았다.
- 이유: 자동화는 API 키를 사용하거나 외부 서비스로 전송하지 않으며, 실제 QPU 실행에는 비용·계정·대회 제공 자격 확인이 필요하다.
- qiskit-ionq는 기본적으로 환경변수 `IONQ_API_KEY`를 사용한다. 키는 `.env.example`을 참고해 환경변수로만 제공한다.
- 공식 문서: https://docs.ionq.com/sdks/qiskit
- Qiskit 트랜스파일 문서: https://quantum.cloud.ibm.com/docs/api/qiskit/compiler

## 남은 한계와 후속 조치

- 실제 IonQ 백엔드 기준 트랜스파일 지표는 대회용 IonQ 자격증명과 대상 백엔드가 확정된 뒤 다시 측정해야 한다.
- 현재 로컬 트랜스파일 검증은 백엔드 제약을 주지 않은 설치·API 호환성 확인용이며 실제 장비 깊이·2큐비트 게이트 수를 대표하지 않는다.
- 문서에 노출된 기상청 키는 재발급하고, 새 키를 `KMA_API_KEY` 환경변수로만 제공해야 한다.
- 기상 캐시 생성 후 `src/run_experiment.py`를 다시 실행하여 무보정/풍속 보정 결과를 비교한다.
