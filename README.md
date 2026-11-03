# 🎯 Event Radar

> **한국·미국 미래 주가 이벤트 및 A/B 관련주 백테스트 레이더**

Event Radar는 한국과 미국의 공식 일정·공시와 미래 시점을 명시한 뉴스를 자동 수집하고, 관련 종목을 연결해 이벤트 전후 반응과 매매 전략을 분석하는 개인용 Event-Driven Trading 시스템입니다. 데이터는 GitHub에 저장되고 GitHub Pages 대시보드로 표시됩니다.

---

## 🌟 수집 원천

### 한국
- **DART**: 무상증자, 분할, CB 등 주요 공시. 일반 유상증자는 제외하고 OpenDART 구조화 데이터에서 **시설자금이 확인되는 경우만 `CAPEX_FINANCING`**으로 유지합니다.
- **KIND IPO**: 수요예측 시작·종료, 공모청약 시작·종료, 납입일, 상장예정일.
- **NEWS_FUTURE**: `내달`, `다음달`, `11월`, `연내`, `내년 1분기`처럼 미래 시점을 명시하면서 가동·출시·승인·수주·임상결과·정책·상장·CAPEX 같은 촉매를 함께 포함한 뉴스만 후보로 수집합니다.
- 기존 엔터테인먼트·게임·지수변경 수집기도 함께 동작합니다.

### 미국
- **SEC EDGAR**: 미국 전체 발행사의 최근 8-K / 8-K/A를 자동 발견합니다. 별도 CIK watchlist는 필요하지 않습니다.
- **FDA Advisory Committee**: FDA 공식 자문위원회 일정. 직접 종목을 식별할 수 없으면 바이오 섹터 프록시 `XBI`에 연결합니다.
- **FOMC**: Federal Reserve 공식 회의 캘린더에서 정책결정일(회의 마지막 날)을 `FOMC_DECISION`으로 수집합니다.

---

## 🗓️ 정확한 날짜와 기간형 일정

공식 일정처럼 하루가 확정된 이벤트는 `EXACT_DATE / CONFIRMED`로 저장합니다.

뉴스에서 발견한 `내달`, `1분기`, `연내` 같은 표현은 특정 하루로 조작하지 않고 아래 정보를 함께 저장합니다.

- `date_precision`: `EXACT_DATE`, `WEEK`, `MONTH`, `QUARTER`, `HALF_YEAR`, `YEAR`
- `window_start`
- `window_end`
- 뉴스 단독 후보는 기본적으로 `EXPECTED`

기존 파이프라인 호환성을 위해 `event_date`에는 기간의 시작일이 들어가지만, Pages 화면에서는 실제 정밀도에 맞춰 `2026년 12월`, `2027년 1분기`, `2026년 내`처럼 표시합니다.

---

## 📊 분석 구조

1. 독립 Collector들이 이벤트를 수집
2. 표준 Event 모델로 정규화
3. 동일 이벤트 중복 제거 및 revision 추적
4. A/B 관련 종목 연결
5. Yahoo 가격 데이터 기반 이벤트 윈도우 수익률·초과수익률 계산
6. 사전 정의 전략 및 Event Score 계산
7. `site/data/*.json`으로 내보내 GitHub Pages 갱신

한 Collector가 실패해도 다른 원천의 수집은 계속 진행하는 graceful-degradation 구조입니다.

---

## 🚀 빠른 시작

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
pytest -p no:cacheprovider -v
python scripts/collect.py
```

로컬 대시보드:

```bash
cd site
python -m http.server 8080
```

---

## ⚙️ GitHub Actions Secrets

저장소의 `Settings` → `Secrets and variables` → `Actions` → `Secrets`에서 등록합니다.

| Secret | 용도 | 필수 여부 |
|---|---|---|
| `DART_API_KEY` | OpenDART 실수집 | DART 사용 시 필요 |
| `NAVER_API_HUB_KEY_ID` | NAVER API HUB Key ID | 뉴스 미래 이벤트 수집 시 필요 |
| `NAVER_API_HUB_KEY` | NAVER API HUB Key | 뉴스 미래 이벤트 수집 시 필요 |

`NAVER_API_HUB_KEY_ID`와 `NAVER_API_HUB_KEY`가 없으면 **NEWS_FUTURE만 0건으로 건너뛰고**, DART·SEC·FDA·KIND·FOMC 등 나머지 수집은 계속됩니다.

SEC에는 별도 API Key나 `SEC_CIKS` Variable이 필요하지 않습니다.

Google Drive 백업은 사용하지 않습니다. GitHub 저장소가 데이터 원본 및 변경 이력 저장소 역할을 합니다.

---

## ⏰ 자동 실행

GitHub Actions가 하루 두 번 실행됩니다.

- 06:00 KST
- 18:00 KST

수집 후 `data/`와 `site/data/`의 변경사항을 자동 커밋합니다.

---

## 📁 주요 경로

```text
src/event_radar/collectors/   # DART, SEC, NEWS, FDA, KIND, FOMC 등
src/event_radar/pipeline.py   # 전체 파이프라인
src/event_radar/export.py     # Pages JSON 생성
data/canonical/               # 이벤트·관계 원본
site/data/                    # 대시보드 공개 데이터
site/js/                      # 목록/상세 렌더링
.github/workflows/collect.yml # 하루 2회 자동 수집
```

---

## 현재 범위 밖

이번 Event Sources v2에는 아래 항목을 아직 포함하지 않습니다.

- 모든 기업의 PDUFA 목표일 완전 자동 재구성
- CPI / 고용 / PPI 등 FOMC 이외의 매크로 일정
- 뉴스 회사명을 전체 상장사 종목코드로 자동 매핑하는 완전한 엔티티 사전
- 과거 동일 유형 이벤트의 대규모 백필

이 항목들은 이후 단계에서 확장할 수 있습니다.

---

## 📖 문서

- `docs/operations.md`
- `docs/data-dictionary.md`
- `docs/superpowers/specs/2026-11-03-event-sources-v2.md`
- `docs/superpowers/plans/2026-11-03-event-sources-v2.md`

---

## 📜 License

MIT License
