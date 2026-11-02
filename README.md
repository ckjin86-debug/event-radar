# 🎯 Event Radar

> **한국·미국 날짜 확정형 주가 이벤트 및 A/B 관련주 백테스트 레이더**

Event Radar는 한국(DART, 엔터, 게임, 거래소)과 미국(SEC EDGAR, FDA PDUFA)의 날짜 확정형 주가 이벤트를 자동 수집하고, 경제적 인과관계가 확인된 A/B급 관련주를 연결하여 과거 이벤트 반응과 매매 전략을 백테스트한 뒤, GitHub Pages 정적 대시보드 및 Google Drive 백업으로 제공하는 개인용 Event-Driven Trading 시스템입니다.

---

## 🌟 핵심 특징

1. **규제기관 및 공식 일정 중심 자동 수집 (Milestone 2)**
   - **한국**: DART 무상증자, 유상증자, 주식분할, 전환사채(CB) 상장, 보호예수 해제
   - **미국**: SEC EDGAR Form 8-K (실적 발표, 주식분할, 유상증자)
   - **비정형 공식 일정**: FDA PDUFA 승인일, 엔터테인먼트 컴백, 게임 신작 출시, 주요 지수 정기변경

2. **철저한 시계열 분리와 Look-ahead Bias 방지**
   - 불변 고유 식별자 (`event_id`): 일정 변경 시 복제하지 않고 revision으로 이력 보존
   - A/B 관련주 타임스탬프 검증: 이벤트 발표 시점(`announced_at`) 이전에 공식 확인된 관계만 인정
   - 시장 반응일(`D0`) 정렬: 장후 공시(AFTERHOURS) 및 비거래일 이벤트의 다음 거래일 반응 엄격 반영

3. **거래일 기준 이벤트 스터디 & 9대 사전 정의 전략 백테스트**
   - D-60 ~ D+20 거래일 기준 개별 종목 누적수익률 및 벤치마크(KOSPI / S&P500) 대비 초과수익률(CAR) 산출
   - 과최적화 방지용 9대 전략 비교 (D-30→D0, D-20→D-5, D-10→D-1, D-5→D+3, D0→D+5 등)
   - 인접 윈도우 방향 일치성 기반 Robustness Score 산출

4. **100점 만점 Event Score V1**
   - **일정 확정도 (20점)**: CONFIRMED(20) / EXPECTED(10) / RUMORED(0)
   - **관계 직접성 (20점)**: 직접 당사자(A급, 20점) / 경제적 관련주(B급, 12~18점)
   - **과거 통계적 Edge (30점)**: 중앙 초과수익률, 승률, 표본 수 패널티 (N<3건 시 최대 5점 엄격 제한)
   - **Robustness (15점)**: 인접 전략 방향 일치성 및 평균/중앙값 괴리 패널티
   - **현재 Setup (15점)**: 이벤트 전 선반영 급등 및 최근 거래량 추세 반영

5. **완전 자동화 및 제로 서버 비용 (GitHub Actions + Pages)**
   - GitHub Actions가 하루 2회 (06:00 KST, 18:00 KST) 파이프라인 자동 실행
   - GitHub Pages 정적 대시보드 (Chart.js / Canvas 기반 반응형 차트)
   - 구글 드라이브(Google Drive API) CSV 자동 백업
   - 민감정보(API Key, Secret, Token) 공개 산출물 배포 100% 차단

---

## 📁 저장소 디렉터리 구조

```text
event-radar/
├─ .github/workflows/         # CI/CD 및 하루 2회 스케줄 수집 워크플로우
├─ config/                    # 이벤트 유형, 사이트 레지스트리, 점수 및 백테스트 설정
│  ├─ event_types.yaml
│  ├─ site_registry.yaml
│  ├─ score.yaml
│  └─ backtest.yaml
├─ data/
│  ├─ canonical/              # 표준 마스터 CSV (events, revisions, relations, securities)
│  ├─ derived/                # 백테스트 수익률, 전략 성과, 점수 결과
│  ├─ cache/prices/           # 일봉 가격 데이터 로컬 캐시
│  └─ logs/                   # Collector 실행 이력 및 상태 로그
├─ src/event_radar/           # 코어 파이프라인 모듈
│  ├─ models.py               # Pydantic 도메인 모델
│  ├─ ids.py                  # 불변 event_id 생성기
│  ├─ normalize.py            # 정규화 및 데이터 파싱
│  ├─ dedupe.py               # 중복 제거 및 소스 우선순위 병합
│  ├─ revisions.py            # 변경 이력 추적
│  ├─ relations.py            # A/B 관련주 연결 및 시계열 필터
│  ├─ scoring.py              # 100점 만점 Event Score 엔진
│  ├─ pipeline.py             # E2E 파이프라인 오케스트레이터
│  ├─ export.py               # GitHub Pages용 정적 JSON 생성
│  ├─ collectors/             # DART, SEC, FDA, 엔터, 게임, 지수 수집기
│  ├─ prices/                 # Yahoo/거래소 가격 어댑터 및 거래일 달력
│  ├─ backtest/               # 세션 정렬, 이벤트 스터디, 전략 비교
│  ├─ manual/                 # Google Form / Sheet 수동 입력 통합
│  └─ integrations/           # Google Drive OAuth 백업 클라이언트
├─ site/                      # GitHub Pages 정적 대시보드
│  ├─ index.html              # 대시보드 메인 (필터, 정렬, 목록)
│  ├─ event.html              # 이벤트 상세 및 백테스트 차트
│  ├─ css/app.css             # 다크 모드 스타일시트
│  └─ js/                     # 차트, 필터, 상세 렌더링 스크립트
├─ tests/                     # TDD 기반 유닛/통합 테스트 스위트
├─ scripts/                   # 실행용 CLI 엔트리포인트 (collect, rebuild, backup)
├─ docs/                      # 운영 가이드, 데이터 사전
└─ pyproject.toml             # 프로젝트 설정 및 의존성
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 환경 설정 및 의존성 설치
```bash
# 가상환경 생성 및 활성화 (Python 3.12+)
python -m venv .venv
.\.venv\Scripts\activate   # Windows

# 의존성 설치
pip install -e ".[dev]"
```

### 2. 테스트 스위트 실행
```bash
pytest -p no:cacheprovider -v
```

### 3. 수집 파이프라인 1회 실행
```bash
python scripts/collect.py
```

### 4. 로컬 대시보드 확인
```bash
cd site
python -m http.server 8080
# 웹 브라우저에서 http://localhost:8080 접속
```

---

## ⚙️ GitHub Actions & Secrets 설정

GitHub Actions 자동 수집 및 배포를 위해 저장소의 `Settings` → `Secrets and variables` → `Actions`에 다음 시크릿을 등록합니다:

| Secret 이름 | 설명 | 필수 여부 |
|---|---|---|
| `DART_API_KEY` | OpenDART API 인증키 | 권장 |
| `GOOGLE_CLIENT_ID` | Google Cloud OAuth 클라이언트 ID | 드라이브 백업 시 |
| `GOOGLE_CLIENT_SECRET` | Google Cloud OAuth 클라이언트 시크릿 | 드라이브 백업 시 |
| `GOOGLE_REFRESH_TOKEN` | 오프라인 접근용 Refresh Token | 드라이브 백업 시 |
| `GOOGLE_DRIVE_FOLDER_ID` | 백업 대상 구글 드라이브 폴더 ID | 드라이브 백업 시 |

*구글 드라이브 토큰 최초 발급은 `python scripts/oauth_bootstrap.py`를 실행하세요.*

---

## 📖 문서 링크
- [운영 및 장애 복구 가이드 (docs/operations.md)](docs/operations.md)
- [데이터 명세서 (docs/data-dictionary.md)](docs/data-dictionary.md)
- [구현 계획서 (docs/superpowers/plans/2026-11-02-event-radar-implementation-plan.md)](docs/superpowers/plans/2026-11-02-event-radar-implementation-plan.md)

---

## 📜 라이선스
MIT License
