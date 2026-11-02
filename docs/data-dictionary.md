# Event Radar Data Dictionary (데이터 명세서)

본 문서는 Event Radar 시스템에서 관리하는 모든 표준 저장소 및 배포 파일의 스키마와 필드 정의를 기술합니다.

---

## 1. Canonical Datasets (`data/canonical/`)

### 1.1 `events.csv` (표준 이벤트 마스터)
날짜가 바뀌어도 불변하는 고유 식별자 `event_id`를 기준으로 정규화된 확정형 이벤트 테이블입니다.

| 필드명 | 타입 | 필수 | 설명 | 예시 |
|---|---|---|---|---|
| `event_id` | String | Y | 이벤트 불변 고유 ID | `KR_DART_20261102000543` |
| `country` | String | Y | 대상 국가 (`KR`, `US`) | `KR` |
| `event_type` | String | Y | 표준 이벤트 코드 | `BONUS_ISSUE`, `EARNINGS` |
| `event_name` | String | Y | 사람이 읽는 이벤트 명칭 | `삼성전자 무상증자 신주배정` |
| `primary_ticker` | String | Y | 직접 당사자 종목 티커 | `005930`, `AAPL` |
| `primary_company` | String | Y | 직접 당사자 법인명 | `삼성전자` |
| `announced_at` | DateTime | Y | 시장에 최초로 알려진 시각 (ISO) | `2026-11-02T09:00:00` |
| `event_date` | Date | Y | 현재 예정된 이벤트 날짜 (YYYY-MM-DD) | `2026-11-20` |
| `event_time_context` | String | Y | `PREMARKET`, `INTRADAY`, `AFTERHOURS`, `DATE_ONLY` | `DATE_ONLY` |
| `status` | String | Y | `CONFIRMED`, `EXPECTED`, `RUMORED`, `CANCELLED` | `CONFIRMED` |
| `source_kind` | String | Y | `REGULATOR`, `EXCHANGE`, `COMPANY`, `ORGANIZER`, `SECONDARY` | `REGULATOR` |
| `source_name` | String | Y | 소스 명칭 (`DART`, `SEC`, `FDA_PDUFA` 등) | `DART` |
| `source_url` | String | N | 근거 원문 URL | `https://dart.fss.or.kr/...` |
| `source_event_uid` | String | N | 원천 제공 고유 접수/문서 번호 | `20261102000543` |
| `evidence_text` | String | N | 핵심 근거 문장 | `1주당 신주 0.5주 배정` |
| `ingest_mode` | String | Y | `AUTO`, `MANUAL`, `AUTO+MANUAL` | `AUTO` |
| `first_seen_at` | DateTime | Y | 최초 파이프라인 수집 시각 | `2026-11-02T10:00:00` |
| `last_seen_at` | DateTime | Y | 최근 정상 수집 확인 시각 | `2026-11-02T10:00:00` |
| `needs_review` | Boolean | Y | 수동 데이터와 공식 공시간 불일치 여부 | `False` |

### 1.2 `event_revisions.csv` (일정 변경 및 수정 이력)
이벤트 날짜, 상태 등이 변경될 때 누적 기록되는 revision 로그입니다.

| 필드명 | 타입 | 설명 |
|---|---|---|
| `event_id` | String | 대상 이벤트 ID |
| `revision_no` | Integer | 변경 회차 (1부터 증가) |
| `changed_at` | DateTime | 변경 감지 시각 |
| `field_name` | String | 변경된 필드 (`event_date`, `status` 등) |
| `old_value` | String | 이전 값 |
| `new_value` | String | 변경된 값 |
| `source_url` | String | 변경 근거 URL |
| `change_reason` | String | 변경 사유 |

### 1.3 `relations.csv` (경제적 연관관계 마스터)
당사자와 관련주 간의 공식적 경제 관계 테이블입니다.

| 필드명 | 타입 | 설명 |
|---|---|---|
| `relation_id` | String | 관계 고유 ID (`REL_...`) |
| `from_entity` | String | 주체 엔터티 (티커, 법인명, 아티스트명 등) |
| `to_ticker` | String | 연결되는 상장 종목 티커 |
| `relation_type` | String | 관계 성격 (`DIRECT`, `SUPPLIER`, `AGENCY`, `PUBLISHER` 등) |
| `relation_grade` | String | 등급 (`A`: 직접 당사자, `B`: 공식 경제관계 60점이상, `C`: 제외) |
| `relation_score` | Integer | 0 ~ 100점 관계 직접성 점수 |
| `relation_known_date` | Date | 시장에 관계가 공표된 날짜 (Look-ahead bias 방지) |
| `relation_start_date` | Date | 관계 유효 시작일 |
| `relation_end_date` | Date | 관계 만료일 (없으면 빈값) |
| `evidence_source` | String | 관계 증빙 출처 |
| `source_url` | String | 증빙 공시/보도 URL |
| `ingest_mode` | String | `AUTO` 또는 `MANUAL` |

---

## 2. Derived Datasets (`data/derived/`)

### 2.1 `backtest_event_returns.csv`
각 이벤트 발생 시점 전후 거래일 기준 수익률 및 초과수익률 프로파일입니다.
- `offset`: `-60` (D-60) ~ `+20` (D+20) 거래일 오프셋
- `return_from_d0`: D0 가격 대비 누적 수익률
- `benchmark_return`: 벤치마크(KOSPI / S&P500) 동기간 누적 수익률
- `abnormal_return`: `return_from_d0 - benchmark_return` (시장 초과수익률)
- `volume_ratio_20d`: 이전 20거래일 평균 거래량 대비 당일 거래량 비율

### 2.2 `strategy_summary.csv`
9대 사전 정의 진입/청산 전략 평가 결과:
- `entry_offset`, `exit_offset`, `sample_n`, `mean_return`, `median_return`, `win_rate`, `mean_abnormal_return`, `median_abnormal_return`, `stdev`, `max_loss`, `max_drawdown`, `robustness_score`.

### 2.3 `event_scores.csv`
100점 만점 Event Score 및 5대 기둥 분해 점수:
- `schedule_points` (20점), `relation_points` (20점), `edge_points` (30점), `robustness_points` (15점), `setup_points` (15점).

---

## 3. Public Web Contracts (`site/data/`)

### 3.1 `events.json`
메인 화면 목록 렌더링용 경량 JSON 배열입니다.
```json
[
  {
    "event_id": "KR_DART_20261102000543",
    "d_day": 18,
    "country": "KR",
    "ticker": "005930",
    "company": "삼성전자",
    "event_type": "BONUS_ISSUE",
    "event_name": "삼성전자 무상증자 신주배정",
    "event_date": "2026-11-20",
    "relation_grade": "A",
    "relation_score": 100,
    "event_score": 85,
    "status": "CONFIRMED",
    "source_name": "DART",
    "source_url": "https://dart.fss.or.kr/..."
  }
]
```

### 3.2 `event_details.json`
상세 분석 모달 및 페이지 렌더링용 JSON 객체입니다.
- Key: `event_id`
- Values: `revisions`, `related_securities`, `backtest_summary`, `strategy_summary`, `event_curve` (D-60~D+20 배열), `score_breakdown`.

### 3.3 `metadata.json`
```json
{
  "generated_at": "2026-11-03T00:00:00",
  "total_events": 5,
  "kr_events": 4,
  "us_events": 1,
  "version": "1.0.0",
  "collector_status": {
    "DART": "SUCCESS",
    "SEC": "SUCCESS"
  }
}
```
