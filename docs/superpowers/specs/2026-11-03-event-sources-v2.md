# Event Sources v2 Design

## Intent
Make Event Radar materially richer without turning it into a noisy news feed. Add four independent sources—future-oriented news, FDA, KIND IPO schedules, and FOMC—then normalize them into the existing event pipeline.

## Goals
- Add `NewsFutureCollector`, `FdaCollector` (rebuilt on official FDA calendar data), `KindIpoCollector`, and `FomcCollector`.
- News only creates future event candidates when the article contains both a future-time expression and a market-relevant catalyst expression.
- Exact-date official sources are `CONFIRMED`; news-only candidates are `EXPECTED`.
- Support fuzzy news timing with `date_precision`, `window_start`, and `window_end` while retaining `event_date` for backward compatibility.
- Do not let a missing optional credential or one broken source stop the pipeline.
- Keep collectors independent so each source can fail/degrade without affecting the others.

## Non-goals
- Full NLP/LLM extraction inside GitHub Actions.
- Complete PDUFA calendar reconstruction.
- CPI/jobs/PPI macro releases in this change; only FOMC is added to macro now.
- Automatic sector relation graphs for macro events in this change.

## Source decisions
### News
Use NAVER API HUB, not the legacy NAVER Developers Search endpoint. Credentials are optional environment variables `NAVER_API_HUB_KEY_ID` and `NAVER_API_HUB_KEY`. Without them the collector returns no events and logs a non-fatal disabled/empty result. Search queries combine future-time terms with catalyst terms. Only title/description snippets are parsed; article bodies are not scraped.

### FDA
Use the official FDA Advisory Committee Calendar as the scheduled-event source. Emit advisory meetings with identifiable drug/company/ticker only when mapping evidence exists; otherwise emit the meeting as a regulator-level event anchored to a market proxy ticker `XBI` so the event remains visible and backtestable at sector level. Drug approval outcomes are not used as a future scheduled source in this change.

### KIND
Use KRX KIND public offering progress data. Emit IPO demand forecast start/end, subscription start/end, payment date, and listing expected date when present. Before listing, company events may not have a stock code, so use `KOSDAQ_IPO`/`KOSPI_IPO` proxy tickers for visibility until a listing ticker is available.

### FOMC
Use the Federal Reserve official meeting calendar. Emit the policy-decision day (the final day of each meeting) as `FOMC_DECISION`, `CONFIRMED`, primary ticker `^GSPC`.

## News date precision
- Exact day: `EXACT_DATE`, window start=end=that date.
- Week expression: `WEEK`, Monday-Sunday window.
- Month / 내달 / 다음달 / 11월: `MONTH`, first-last day of month.
- Quarter / 1분기: `QUARTER`.
- Half-year: `HALF_YEAR`.
- 연내 / year-only: `YEAR`.
For backward compatibility, `event_date` is `window_start`. UI must display the precision/window so it is not presented as an exact day.

## Relevance filter for news
A candidate needs at least one future-time signal and one catalyst signal. Initial catalysts: approval, launch/release, plant operation, construction, large order/contract, bid/tender, policy/regulation, court ruling, clinical result, listing/IPO, merger/acquisition, production ramp, investment/capex. Generic financing/rights-issue news is excluded unless facility/capex language is also present.

## Deduplication
Existing source UID/date merge remains authoritative. News source UID is a stable hash of canonical article URL + normalized candidate phrase. Official sources use source-native URL/date/company identifiers.

## Failure behavior
- 404/selector changes => collector logs failure and returns `[]`.
- Missing NAVER credentials => collector returns `[]` without failing the whole pipeline.
- Parse uncertainty => skip rather than invent an exact date.

## Approaches considered
1. One monolithic multi-source collector: rejected because one source change would break the whole bundle.
2. Independent collectors feeding the existing pipeline: selected; best fit with current graceful-degradation architecture.
3. External database/event service: rejected for now because GitHub-based operation is already working and the user wants a simple personal system.
