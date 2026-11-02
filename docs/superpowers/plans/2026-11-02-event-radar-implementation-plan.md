# Event Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국·미국의 날짜 확정형 주가 이벤트를 자동 수집하고, A/B급 관련주를 연결해 과거 이벤트 반응과 전략 성과를 백테스트한 뒤 GitHub Pages 대시보드와 Google Drive 백업으로 제공하는 개인용 Event Driven Trading Radar를 구축한다.

**Architecture:** GitHub Actions가 하루 2회 Python 파이프라인을 실행한다. 각 Collector가 공식·준공식 소스에서 이벤트를 표준 스키마로 변환하고, 관계 엔진·가격 엔진·백테스트 엔진·점수 엔진을 거쳐 CSV/JSON을 생성한다. GitHub Pages는 생성된 JSON만 읽는 정적 대시보드로 운영하며, Google Drive는 분석 및 ChatGPT/bb-invest 연동용 백업 저장소로 사용한다.

**Tech Stack:** Python 3.12+, pytest, pandas, requests/httpx, BeautifulSoup/lxml, pydantic, yfinance-compatible price-provider adapter, vanilla HTML/CSS/JavaScript, Chart.js(고정 버전), GitHub Actions, GitHub Pages, Google Drive API OAuth 2.0.

**Spec:** `docs/event-radar-spec-v1.0.md`

## Global Constraints

- 핵심 시스템은 AI 없이 동작한다.
- 대상 국가는 한국과 미국이다.
- 기본 이벤트 범위는 무상증자, 유상증자, 주식분할/역분할, CB/BW/신주상장, 보호예수/락업, 실적, FDA/PDUFA/주요 임상, 지수 편입·편출, 엔터테인먼트 일정, 게임 출시/대형 업데이트다.
- A급은 직접 당사자, B급은 공식적인 경제적 관계가 확인된 종목으로 제한한다.
- 수동 입력은 AUTO 데이터와 분리해 `MANUAL`, 자동+수동 검증은 `AUTO+MANUAL`로 기록한다.
- 수동 데이터는 자동 파이프라인이 무단 덮어쓰지 않는다.
- 이벤트 변경 이력과 관계 유효기간을 보존한다.
- 백테스트는 당시 시점에 알려진 정보만 사용해 look-ahead bias를 방지한다.
- 대시보드는 공개하되 API Key, OAuth token, refresh token, client secret 등 비밀정보는 절대 배포 산출물에 포함하지 않는다.
- 자동 주문 기능은 V1 범위에서 제외한다.
- 화면의 D-Day는 달력 기준, 백테스트 오프셋은 거래일 기준으로 구분한다.
- 가격 공급자는 교체 가능한 adapter로 구현한다. 특정 무료 공급자 장애가 전체 시스템 장애로 이어지지 않게 한다.
- Collector 오류 하나가 전체 수집 작업을 중단시키지 않아야 한다.

## Review Focus

1. **주말·휴일·장후 이벤트** — 이벤트 반응일을 잘못 잡아 D0가 하루씩 밀리는 오류를 방지한다.
2. **같은 이벤트의 날짜 변경/중복 공지** — 새 이벤트로 복제하지 않고 revision으로 연결한다.
3. **현재 관계를 과거에 소급 적용하는 오류** — `relation_start_date`, `relation_end_date`, `relation_known_date`로 차단한다.
4. **표본 수 1~3건의 과대평가** — Event Score와 전략 추천에서 최소 표본 패널티를 적용한다.
5. **Collector 하나의 HTML/API 변경** — 해당 source만 FAILED로 기록하고 나머지 Collector·배포·기존 데이터는 유지한다.

---

## 1. 제품 구성

### 1.1 사용자 화면

메인 화면:
- 오늘 / 7일 / 30일 / 90일
- 전체 / 한국 / 미국
- 전체 / 증자 / 분할 / 락업 / 실적 / FDA / 지수 / 엔터 / 게임
- 전체 / A / B
- CONFIRMED / EXPECTED
- Event Score 정렬
- 검색: 종목명 / 티커 / 이벤트명

목록 열:
- D-Day
- 국가
- 종목
- Ticker
- 이벤트
- 이벤트 날짜
- A/B
- Relation Score
- Event Score
- 상태
- 출처

상세 화면:
- 이벤트 기본정보와 공식 링크
- 최초 발표일 / 최신 일정 / 변경 이력
- A/B 관련주와 관계 근거
- D-60~D+20 평균 이벤트 곡선
- 절대수익률 / 벤치마크 대비 초과수익률
- 평균 / 중앙값 / 승률 / 표준편차 / MDD / 표본 수
- 사전 정의된 진입·청산 전략 비교
- 현재 이벤트와 과거 패턴 비교

### 1.2 수동 입력

공개 GitHub Pages에는 쓰기 권한을 두지 않는다.

V1 수동 입력:
- Google Form → Google Sheet
- GitHub Actions가 Sheet를 읽어 `manual_events.csv`, `manual_relations.csv`로 병합
- 대시보드에는 "수동 일정 추가" 링크만 제공

충돌 정책:
- MANUAL 값 우선
- AUTO 값은 폐기하지 않고 conflict/revision 로그에 기록
- 자동 source에서 더 높은 우선순위의 공식 변경이 확인되면 `needs_review=true`로 표시

---

## 2. 저장소 구조

```text
event-radar/
├─ .github/
│  └─ workflows/
│     ├─ collect.yml
│     ├─ deploy-pages.yml
│     └─ tests.yml
├─ config/
│  ├─ sources.yaml
│  ├─ event_types.yaml
│  ├─ backtest.yaml
│  ├─ score.yaml
│  └─ site_registry.yaml
├─ data/
│  ├─ canonical/
│  │  ├─ events.csv
│  │  ├─ event_revisions.csv
│  │  ├─ securities.csv
│  │  ├─ relations.csv
│  │  ├─ manual_events.csv
│  │  └─ manual_relations.csv
│  ├─ derived/
│  │  ├─ event_security_map.csv
│  │  ├─ backtest_event_returns.csv
│  │  ├─ backtest_summary.csv
│  │  ├─ strategy_summary.csv
│  │  └─ event_scores.csv
│  ├─ cache/
│  │  └─ prices/
│  └─ logs/
│     └─ collector_runs.csv
├─ src/
│  └─ event_radar/
│     ├─ models.py
│     ├─ ids.py
│     ├─ pipeline.py
│     ├─ normalize.py
│     ├─ dedupe.py
│     ├─ revisions.py
│     ├─ relations.py
│     ├─ scoring.py
│     ├─ export.py
│     ├─ collectors/
│     │  ├─ base.py
│     │  ├─ dart.py
│     │  ├─ sec.py
│     │  ├─ earnings.py
│     │  ├─ fda.py
│     │  ├─ index_changes.py
│     │  ├─ entertainment.py
│     │  └─ games.py
│     ├─ prices/
│     │  ├─ base.py
│     │  ├─ yahoo.py
│     │  └─ calendar.py
│     ├─ backtest/
│     │  ├─ align.py
│     │  ├─ returns.py
│     │  ├─ metrics.py
│     │  └─ strategies.py
│     ├─ manual/
│     │  └─ google_sheet.py
│     └─ integrations/
│        └─ google_drive.py
├─ site/
│  ├─ index.html
│  ├─ event.html
│  ├─ css/app.css
│  ├─ js/
│  │  ├─ app.js
│  │  ├─ filters.js
│  │  ├─ event-detail.js
│  │  └─ charts.js
│  └─ data/
│     ├─ events.json
│     ├─ event_details.json
│     └─ metadata.json
├─ tests/
│  ├─ fixtures/
│  ├─ test_ids.py
│  ├─ test_normalize.py
│  ├─ test_dedupe.py
│  ├─ test_revisions.py
│  ├─ test_relations.py
│  ├─ test_calendar_align.py
│  ├─ test_backtest_returns.py
│  ├─ test_strategies.py
│  ├─ test_scoring.py
│  ├─ collectors/
│  │  ├─ test_dart.py
│  │  └─ test_sec.py
│  └─ integration/
│     └─ test_pipeline.py
├─ scripts/
│  ├─ collect.py
│  ├─ rebuild_backtest.py
│  ├─ build_site_data.py
│  ├─ backup_drive.py
│  └─ oauth_bootstrap.py
├─ docs/
│  ├─ event-radar-spec-v1.0.md
│  └─ superpowers/plans/
│     └─ 2026-11-02-event-radar-implementation-plan.md
├─ pyproject.toml
├─ requirements.lock
└─ README.md
```

---

## 3. 핵심 데이터 스키마

### 3.1 `events.csv`

| 필드 | 의미 |
|---|---|
| `event_id` | 날짜 변경에도 유지되는 내부 고유 ID |
| `country` | KR / US |
| `event_type` | 표준 이벤트 코드 |
| `event_name` | 사람이 읽는 이벤트명 |
| `primary_ticker` | 직접 당사자 티커 |
| `primary_company` | 직접 당사자 |
| `announced_at` | 시장이 최초로 일정을 알 수 있었던 시점 |
| `event_date` | 현재 예정일 |
| `event_time_context` | PREMARKET / INTRADAY / AFTERHOURS / DATE_ONLY |
| `status` | CONFIRMED / EXPECTED / RUMORED / CANCELLED |
| `source_kind` | REGULATOR / EXCHANGE / COMPANY / ORGANIZER / SECONDARY |
| `source_name` | DART / SEC / FDA / 회사명 등 |
| `source_url` | 근거 원문 |
| `source_event_uid` | 원문이 제공하는 ID |
| `evidence_text` | 짧은 근거 문장 |
| `ingest_mode` | AUTO / MANUAL / AUTO+MANUAL |
| `first_seen_at` | 최초 수집 시각 |
| `last_seen_at` | 마지막 확인 시각 |
| `needs_review` | 충돌 또는 불확실성 여부 |

### 3.2 `event_revisions.csv`

`event_id`, `revision_no`, `changed_at`, `field_name`, `old_value`, `new_value`, `source_url`, `change_reason`

### 3.3 `securities.csv`

`ticker`, `company_name`, `country`, `exchange`, `currency`, `benchmark_ticker`, `active_from`, `active_to`

### 3.4 `relations.csv`

`relation_id`, `from_entity`, `to_ticker`, `relation_type`, `relation_grade`, `relation_score`, `relation_known_date`, `relation_start_date`, `relation_end_date`, `evidence_source`, `source_url`, `ingest_mode`

### 3.5 `backtest_event_returns.csv`

`event_id`, `ticker`, `relation_grade`, `event_session_date`, `offset`, `price`, `return_from_d0`, `benchmark_return`, `abnormal_return`, `volume_ratio_20d`

`offset`은 `-60 ... +20`의 **거래일 인덱스**다.

### 3.6 `strategy_summary.csv`

`event_type`, `relation_grade`, `entry_offset`, `exit_offset`, `sample_n`, `mean_return`, `median_return`, `win_rate`, `mean_abnormal_return`, `median_abnormal_return`, `stdev`, `max_loss`, `max_drawdown`, `robustness_score`

---

## 4. 이벤트 ID와 중복 제거

### event_id 원칙

날짜를 ID에 포함하지 않는다. 날짜가 바뀌어도 같은 이벤트여야 한다.

우선순위:
1. `source_name + source_event_uid`
2. 없으면 `source_url + primary_ticker + event_type + announced_date`
3. MANUAL은 UUID

`event_date` 변경은 새 event가 아니라 revision이다.

### Source Priority

1. 규제기관
2. 거래소
3. 기업 공식 IR/공식 공지
4. 공식 주최기관/학회/엔터 플랫폼
5. 보조 데이터 소스

동일 이벤트의 날짜가 충돌할 때 높은 source priority를 기본값으로 사용하되, 수동 override가 있으면 자동 덮어쓰지 않는다.

---

## 5. 관련주 엔진

### 등급

- A: 이벤트 직접 당사자, Relation Score 90~100
- B: 공식적인 경제적 연결이 확인된 기업, Relation Score 60~89
- C: 저장은 가능하지만 V1 백테스트/기본 화면에서 제외

### 자동 매핑

1. `primary_ticker`를 A로 추가
2. 이벤트 날짜 기준 유효한 `relations.csv` 검색
3. `relation_known_date <= announced_at`
4. `relation_start_date <= event_date`
5. `relation_end_date`가 비어 있거나 `event_date <= relation_end_date`
6. `relation_score >= 60`만 B 후보로 채택

### 수동 매핑

사용자가 Google Form에서 A/B를 직접 지정할 수 있다.
수동 관계는 source/evidence와 함께 기록하고 자동 관계와 분리한다.

---

## 6. 거래일 정렬 규칙

`D-day` 화면 표시는 달력 차이로 계산한다.

백테스트는 반드시 거래일 기준으로 계산한다.

### `event_session_date`

- PREMARKET: 해당 날짜가 거래일이면 당일
- INTRADAY: 당일
- AFTERHOURS: 다음 거래일
- DATE_ONLY:
  - 거래일이면 당일
  - 비거래일이면 다음 거래일

이벤트가 과거 데이터에서 시각 정보 없이 날짜만 존재하면 `DATE_ONLY`로 처리하고 결과에 `session_alignment_confidence=LOW`를 남긴다.

---

## 7. 가격 데이터

### Provider interface

```python
class PriceProvider(Protocol):
    def history(
        self,
        ticker: str,
        start: date,
        end: date
    ) -> pd.DataFrame: ...
```

필수 컬럼:
`date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`

V1 기본 provider는 무료 historical price source adapter를 사용하되 provider 교체가 가능해야 한다.

캐시:
`data/cache/prices/<ticker>.csv`

새 실행에서는 필요한 날짜만 증분 업데이트한다.

---

## 8. 백테스트 방법

### 이벤트 윈도우

`-60, -30, -20, -15, -10, -5, -3, -1, 0, +1, +3, +5, +10, +20`

### 수익률

- Absolute Return
- Benchmark Return
- Abnormal Return = Stock Return - Benchmark Return
- CAR = 구간 누적 Abnormal Return

### 통계

- sample_n
- mean
- median
- win_rate
- standard_deviation
- max_gain
- max_loss
- max_drawdown
- average abnormal return
- median abnormal return
- volume ratio vs preceding 20 sessions

### 사전 정의 전략

- D-30 → D0
- D-30 → D-5
- D-20 → D0
- D-20 → D-5
- D-10 → D0
- D-10 → D-1
- D-5 → D0
- D-5 → D+3
- D0 → D+5

V1에서는 모든 가능한 entry/exit 조합을 최적화하지 않는다.
정해진 전략만 비교해 데이터마이닝 과최적화를 줄인다.

### Robustness

최고 전략의 인접 window에서도 방향과 성과가 유지되는지 확인한다.

예:
D-20→D-5가 최고라면 D-20→D-3, D-15→D-5의 결과가 반대 방향이면 robustness를 낮춘다.

---

## 9. Event Score V1

100점.

### A. 일정 확정도: 20
- CONFIRMED 20
- EXPECTED 10
- RUMORED 0

### B. 관계 직접성: 20
`round(relation_score * 0.20)`

### C. 과거 Edge: 30
- median abnormal return: 최대 15
- win rate: 최대 10
- sample size: 최대 5

표본 패널티:
- N < 3: historical edge 최대 5
- 3 ≤ N < 8: 최대 15
- 8 ≤ N < 15: 최대 24
- N ≥ 15: 최대 30

### D. Robustness: 15
- 인접 전략 방향 일치
- 평균/중앙값 괴리
- 최대손실/변동성 패널티

### E. 현재 Setup: 15
- 이벤트 전 과도한 선반영 여부
- 최근 거래량 변화
- D-20~현재 상대수익률

점수 계산식은 `config/score.yaml`로 분리해 코드 수정 없이 조정할 수 있게 한다.

---

## 10. Collector 설계

### 공통 인터페이스

```python
class Collector(Protocol):
    source_name: str
    def collect(self, since: datetime) -> list[RawEvent]: ...
```

모든 Collector는:
- timeout
- retry
- source별 rate limit
- User-Agent
- 실패 로그
- fixture 기반 parser test
를 갖는다.

### 자동화 커버리지 등급

- `AUTO_FULL`: 구조화 API/정형 데이터로 안정적 수집
- `AUTO_PARTIAL`: 공식 페이지 규칙 기반 파싱
- `MANUAL_FALLBACK`: 자동 수집 실패 시 Google Form 보완

### V1 우선 구현 순서

1. DART corporate actions — AUTO_FULL
2. SEC filings / corporate action signals — AUTO_FULL~PARTIAL
3. 공식 기업 IR/공시 기반 PDUFA/임상 키워드 — AUTO_PARTIAL
4. 엔터 공식 공지 registry — AUTO_PARTIAL
5. 게임 공식 공지 registry — AUTO_PARTIAL
6. 지수 변경 공식 발표 registry — AUTO_PARTIAL
7. 실적 일정 — provider별 adapter

FDA/PDUFA, 엔터, 게임, 지수 변경은 하나의 범용 웹 크롤러로 억지로 처리하지 않는다.
`config/site_registry.yaml`에 공식 사이트별 URL, selector, regex, timezone을 등록하는 adapter 방식으로 구현한다.

---

## 11. Dashboard 데이터 계약

### `site/data/events.json`

각 row:
`event_id`, `d_day`, `country`, `ticker`, `company`, `event_type`, `event_name`, `event_date`, `relation_grade`, `relation_score`, `event_score`, `status`, `source_name`, `source_url`

### `site/data/event_details.json`

event_id 기준:
- revisions
- related securities
- backtest summary
- strategy summary
- event curve
- sample count
- latest update

프론트엔드는 canonical CSV를 직접 읽지 않는다.
배포 전에 Python export 단계에서 공개용 JSON을 생성한다.

---

## 12. Google Drive 백업

백업 대상:
- `master_events.csv`
- `relations.csv`
- `backtest_summary.csv`
- `strategy_summary.csv`
- `event_scores.csv`
- `collector_runs.csv`

GitHub Actions에서는 사용자 없는 상태에서도 접근 가능해야 하므로 Google OAuth offline access로 발급한 refresh token을 GitHub Secrets에 저장한다.

필요 Secrets:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_FOLDER_ID`

백업 실패는 전체 수집/Pages 배포를 실패시키지 않고 warning으로 남긴다.

---

# Implementation Tasks

### Task 1: 프로젝트 골격과 도메인 모델

**Files:**
- Create: `pyproject.toml`
- Create: `src/event_radar/models.py`
- Create: `src/event_radar/ids.py`
- Create: `config/event_types.yaml`
- Test: `tests/test_ids.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `RawEvent`, `Event`, `Relation`, `Security` pydantic models
- Produces: `make_event_id(raw: RawEvent) -> str`

- [ ] `test_event_id_does_not_change_when_event_date_changes` 작성
- [ ] 테스트가 실패하는지 확인
- [ ] models와 ID 생성 함수를 최소 구현
- [ ] `pytest tests/test_ids.py tests/test_normalize.py -v` PASS 확인
- [ ] `feat: add event radar domain models` 커밋

### Task 2: 정규화·중복제거·Revision 엔진

**Files:**
- Create: `src/event_radar/normalize.py`
- Create: `src/event_radar/dedupe.py`
- Create: `src/event_radar/revisions.py`
- Test: `tests/test_dedupe.py`
- Test: `tests/test_revisions.py`

**Interfaces:**
- Consumes: `RawEvent`, `Event`
- Produces: `normalize_event(raw) -> Event`
- Produces: `merge_events(existing, incoming) -> MergeResult`

- [ ] 동일 source UID의 날짜 변경이 신규 event가 아닌 revision이 되는 테스트 작성
- [ ] 낮은 source priority가 높은 priority 값을 덮지 못하는 테스트 작성
- [ ] 구현 후 관련 테스트 PASS
- [ ] `feat: add event normalization and revision tracking` 커밋

### Task 3: 관련주 A/B 매핑과 시간축

**Files:**
- Create: `src/event_radar/relations.py`
- Create: `data/canonical/relations.csv`
- Test: `tests/test_relations.py`

**Interfaces:**
- Produces: `resolve_related_securities(event: Event, relations: list[Relation]) -> list[EventSecurity]`

- [ ] 직접 당사자가 A로 자동 등록되는 테스트
- [ ] `relation_known_date > announced_at` 관계가 과거 이벤트에서 제외되는 테스트
- [ ] 만료된 관계가 제외되는 테스트
- [ ] B급 threshold 60 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add time-aware relation engine` 커밋

### Task 4: 수동 입력 Import

**Files:**
- Create: `src/event_radar/manual/google_sheet.py`
- Create: `data/canonical/manual_events.csv`
- Create: `data/canonical/manual_relations.csv`
- Test: `tests/test_manual_merge.py`

**Interfaces:**
- Produces: `load_manual_rows() -> ManualInput`
- Produces: `apply_manual_overrides(auto, manual) -> MergeResult`

- [ ] MANUAL이 AUTO에 의해 덮어써지지 않는 테스트
- [ ] 충돌 시 `needs_review=true` 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add manual event and relation overrides` 커밋

### Task 5: 가격 Provider와 거래일 정렬

**Files:**
- Create: `src/event_radar/prices/base.py`
- Create: `src/event_radar/prices/yahoo.py`
- Create: `src/event_radar/prices/calendar.py`
- Create: `src/event_radar/backtest/align.py`
- Test: `tests/test_calendar_align.py`

**Interfaces:**
- Produces: `PriceProvider.history(...)`
- Produces: `resolve_event_session(event, trading_days) -> date`

- [ ] 주말 DATE_ONLY가 다음 거래일로 이동하는 테스트
- [ ] AFTERHOURS가 다음 거래일 D0가 되는 테스트
- [ ] PREMARKET 거래일은 당일 D0 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add price provider and event session alignment` 커밋

### Task 6: 이벤트 수익률·초과수익률 엔진

**Files:**
- Create: `src/event_radar/backtest/returns.py`
- Create: `src/event_radar/backtest/metrics.py`
- Test: `tests/test_backtest_returns.py`

**Interfaces:**
- Produces: `event_window_returns(...) -> pd.DataFrame`
- Produces: `summarize_event_group(...) -> BacktestSummary`

- [ ] 거래일 offset이 정확한지 테스트
- [ ] abnormal return = stock - benchmark 테스트
- [ ] mean/median/win-rate/MDD 계산 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add event study return engine` 커밋

### Task 7: 전략 비교와 Robustness

**Files:**
- Create: `src/event_radar/backtest/strategies.py`
- Create: `config/backtest.yaml`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Produces: `evaluate_strategies(event_returns, strategy_config) -> list[StrategyResult]`
- Produces: `robustness_score(results) -> float`

- [ ] 사전 정의 9개 전략만 평가하는 테스트
- [ ] 최고 window 인접 결과가 반대면 robustness가 낮아지는 테스트
- [ ] 표본 부족 표시 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add strategy comparison and robustness scoring` 커밋

### Task 8: Event Score

**Files:**
- Create: `src/event_radar/scoring.py`
- Create: `config/score.yaml`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces: `calculate_event_score(input: ScoreInput) -> ScoreResult`

- [ ] N<3일 때 historical edge 상한 5 테스트
- [ ] CONFIRMED가 EXPECTED보다 높은 점수 테스트
- [ ] Relation Score가 점수에 반영되는 테스트
- [ ] 0~100 clamp 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add configurable event scoring` 커밋

### Task 9: DART Collector

**Files:**
- Create: `src/event_radar/collectors/base.py`
- Create: `src/event_radar/collectors/dart.py`
- Test: `tests/collectors/test_dart.py`
- Add fixtures: `tests/fixtures/dart/`

**Interfaces:**
- Produces: `DartCollector.collect(since) -> list[RawEvent]`

- [ ] fixture에서 무상증자 기준일/신주상장일 파싱 테스트
- [ ] 유상증자/CB/BW 이벤트 type mapping 테스트
- [ ] API error가 collector failure로만 기록되는 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add DART corporate action collector` 커밋

### Task 10: SEC Collector

**Files:**
- Create: `src/event_radar/collectors/sec.py`
- Test: `tests/collectors/test_sec.py`
- Add fixtures: `tests/fixtures/sec/`

**Interfaces:**
- Produces: `SecCollector.collect(since) -> list[RawEvent]`

- [ ] ticker/CIK mapping fixture 테스트
- [ ] split/corporate-action signal 정규화 테스트
- [ ] SEC request User-Agent 설정 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add SEC event collector` 커밋

### Task 11: 비정형 공식 일정 Registry Collectors

**Files:**
- Create: `src/event_radar/collectors/fda.py`
- Create: `src/event_radar/collectors/entertainment.py`
- Create: `src/event_radar/collectors/games.py`
- Create: `src/event_radar/collectors/index_changes.py`
- Create: `config/site_registry.yaml`
- Test: source별 fixture tests

**Interfaces:**
- Produces: 공통 `RegistryCollector`
- Config keys: `url`, `event_type`, `selector`, `date_regex`, `ticker_map`, `timezone`

- [ ] HTML selector가 바뀌면 source만 FAILED 처리되는 테스트
- [ ] PDUFA 문장 date regex 테스트
- [ ] 엔터 artist→ticker mapping 테스트
- [ ] 게임 title→publisher ticker mapping 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add registry-based official event collectors` 커밋

### Task 12: 파이프라인·로그·공개 JSON Export

**Files:**
- Create: `src/event_radar/pipeline.py`
- Create: `src/event_radar/export.py`
- Create: `scripts/collect.py`
- Create: `scripts/rebuild_backtest.py`
- Create: `scripts/build_site_data.py`
- Test: `tests/integration/test_pipeline.py`

**Interfaces:**
- Produces: `run_pipeline(now: datetime) -> PipelineReport`
- Produces: `site/data/events.json`, `event_details.json`, `metadata.json`

- [ ] collector 한 개 실패 후에도 다른 collector와 export가 완료되는 통합 테스트
- [ ] 중복/리비전/관계/백테스트/score 전체 흐름 테스트
- [ ] 공개 JSON에 secret field가 없는 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add end-to-end event radar pipeline` 커밋

### Task 13: Google Drive 백업

**Files:**
- Create: `src/event_radar/integrations/google_drive.py`
- Create: `scripts/backup_drive.py`
- Create: `scripts/oauth_bootstrap.py`
- Test: mocked Drive API tests

**Interfaces:**
- Produces: `backup_files(paths: list[Path], folder_id: str) -> BackupReport`

- [ ] refresh-token credential load 테스트
- [ ] 동일 파일명 update 테스트
- [ ] Drive 실패가 non-fatal warning이 되는 테스트
- [ ] 구현 및 PASS
- [ ] `feat: add Google Drive backup` 커밋

### Task 14: GitHub Pages Dashboard

**Files:**
- Create: `site/index.html`
- Create: `site/event.html`
- Create: `site/css/app.css`
- Create: `site/js/app.js`
- Create: `site/js/filters.js`
- Create: `site/js/event-detail.js`
- Create: `site/js/charts.js`

**Interfaces:**
- Consumes: `site/data/*.json`

- [ ] 기간/국가/이벤트/A-B/status filter 동작 확인
- [ ] Event Score 정렬 확인
- [ ] 모바일 360px 화면에서 table/card 전환 확인
- [ ] event detail에 revision/related/backtest/strategy 표시
- [ ] source URL 새 창 연결
- [ ] `feat: add Event Radar dashboard` 커밋

### Task 15: GitHub Actions와 Pages 배포

**Files:**
- Create: `.github/workflows/tests.yml`
- Create: `.github/workflows/collect.yml`
- Create: `.github/workflows/deploy-pages.yml`

**Interfaces:**
- tests: PR/push에서 pytest
- collect: 하루 2회 + workflow_dispatch
- pages: collect 성공 후 또는 main push에서 `site/` 배포

- [ ] collect workflow를 한국시간 아침/저녁 기준으로 예약
- [ ] `workflow_dispatch` 수동 실행 추가
- [ ] secret은 environment로만 주입
- [ ] generated CSV/JSON 갱신 commit은 bot commit으로 남김
- [ ] Pages artifact에는 `site/`만 포함
- [ ] 실제 Actions 1회 실행 후 logs 확인
- [ ] `ci: add scheduled collection and pages deployment` 커밋

### Task 16: 최종 검증과 운영문서

**Files:**
- Create: `README.md`
- Create: `docs/operations.md`
- Create: `docs/data-dictionary.md`

- [ ] `pytest -q` 전체 PASS
- [ ] 신규 event → relation → price → backtest → score → dashboard E2E 확인
- [ ] 날짜 변경 event가 revision으로 나타나는지 확인
- [ ] Google Drive 백업 파일 확인
- [ ] 공개 Pages source에서 secret 문자열 검색 결과 0 확인
- [ ] collector 하나를 의도적으로 실패시켜 graceful degradation 확인
- [ ] 운영문서에 수동 입력·재실행·복구 절차 기록
- [ ] `docs: add Event Radar operations guide` 커밋

---

## 단계별 출시

### Milestone 1 — Foundation
Task 1~8  
완료 조건: 샘플 이벤트 데이터만으로 A/B 관계와 백테스트·Event Score가 계산된다.

### Milestone 2 — Automatic Collection
Task 9~11  
완료 조건: 실제 DART/SEC 및 registry source에서 이벤트가 자동 유입된다.

### Milestone 3 — Product
Task 12~14  
완료 조건: 실제 데이터가 Pages 화면에서 필터·상세·백테스트 차트로 보인다.

### Milestone 4 — Automation
Task 15~16  
완료 조건: PC 없이 GitHub가 자동 갱신하고 Drive 백업까지 완료한다.

---

## V1에서 의도적으로 하지 않는 것

- 자동 주문
- 실시간 틱 데이터
- 모든 뉴스 자동 해석
- LLM 기반 관련주 발굴
- 소셜미디어 루머 수집
- C급 테마주 자동 추천
- 머신러닝 수익률 예측
- 모든 entry/exit 조합 brute-force 최적화
- 사용자 계정/로그인 시스템

이 항목들은 데이터 품질과 실제 이벤트 edge가 검증된 뒤 V2에서 판단한다.

---

## 구현 완료 판정

V1은 다음 시나리오가 사람 개입 없이 동작하면 완료다.

1. GitHub Actions가 예약 실행된다.
2. DART/SEC/등록된 공식 일정 페이지에서 신규 이벤트를 수집한다.
3. 기존 이벤트의 일정 변경을 revision으로 기록한다.
4. A/B 관련주를 이벤트 당시 유효한 관계만으로 연결한다.
5. 필요한 가격 데이터를 증분 수집한다.
6. D-60~D+20 거래일 기준 이벤트 스터디를 계산한다.
7. 9개 사전 정의 매매 전략을 비교한다.
8. Event Score를 계산한다.
9. GitHub Pages가 새 데이터를 표시한다.
10. 핵심 CSV가 Google Drive에 백업된다.
11. 자동수집이 놓친 이벤트/관련주는 Google Form으로 수동 보완할 수 있다.
12. Collector 하나가 실패해도 기존 화면과 다른 Collector는 계속 동작한다.
