# SEC Automatic Filing Discovery Design

Date: 2026-11-03
Repository: `ckjin86-debug/event-radar`

## Intent

Remove the manual `SEC_CIKS` watchlist requirement and make Event Radar automatically discover relevant U.S. public-company filings across EDGAR. The goal is that the scheduled collector can find new event candidates without the user maintaining CIKs or ticker lists.

## Current State

`SecCollector` currently reads a comma-separated `SEC_CIKS` environment variable and calls `https://data.sec.gov/submissions/CIK##########.json` once per configured company. This works for a small watchlist but does not scale to broad U.S. market coverage and requires manual maintenance.

## Selected Approach

Use SEC filing indexes as the discovery layer, then enrich only the filings that match Event Radar's target forms/events.

Flow:

1. Scheduled collection determines the relevant SEC filing day/window.
2. Read the SEC daily filing index for that period rather than iterating through thousands of companies.
3. Filter index rows before any company-specific enrichment. Initial target forms are `8-K` / `8-K/A`; architecture should permit additional forms later.
4. For each candidate filing, resolve company identity using SEC CIK/ticker/company mappings (`company_tickers.json` / `company_tickers_exchange.json`) and/or the filing metadata.
5. Fetch only the candidate filing/submission metadata needed to classify Event Radar event types such as earnings, stock split, and offering.
6. Normalize candidates into the existing `RawEvent` model and pass them into the existing dedupe/revision/relations/backtest/export pipeline.
7. Persist enough source UID/accession metadata that repeated scheduled runs are idempotent.

## Why This Approach

### Considered: Manual CIK watchlist

Simple and cheap but requires ongoing user maintenance and misses companies not explicitly listed. Rejected for the target product.

### Considered: Iterate every listed company's submissions JSON

Would technically remove manual configuration, but requires a large number of repeated company-level requests every run. It works against SEC fair-access guidance and is inefficient for discovery.

### Selected: Filing-index-first discovery

The daily index already answers the key first question: "what was filed?" Event Radar can filter centrally and make follow-up requests only for candidate filings. This minimizes requests, removes the manual watchlist, and naturally includes newly listed or previously unknown companies.

## SEC Data Sources

Use public SEC resources without API keys:

- EDGAR filing indexes under `https://www.sec.gov/Archives/edgar/`
- `https://www.sec.gov/files/company_tickers.json`
- `https://www.sec.gov/files/company_tickers_exchange.json`
- Existing `data.sec.gov/submissions/CIK##########.json` only when enrichment is necessary

Automated requests must identify the client with an appropriate User-Agent and stay comfortably below the SEC's current fair-access ceiling of 10 requests/second.

## Collector Behavior

### Discovery window

Scheduled runs happen twice daily. Each run should include a small overlap window so late index updates do not create gaps. Existing event IDs/accession numbers handle duplicates.

### Candidate filtering

Start conservatively with forms and event patterns the project already models:

- 8-K / 8-K/A
- Earnings / Item 2.02
- Stock split or security-holder-right changes / Item 3.03 or explicit split language
- Offering / Item 3.02 or explicit offering language

Do not classify unrelated 8-K filings as events merely because they are 8-Ks.

### Identity resolution

Maintain an in-run mapping cache keyed by CIK. Prefer SEC mappings for ticker/company identity. If no ticker can be resolved, skip public-equity event creation rather than inventing one.

### Failure behavior

- A failed SEC request must not crash the whole multi-source pipeline.
- Partial SEC results may be returned if some candidate enrichment fails.
- Collector logs should distinguish discovery failure from per-filing enrichment failure where practical.

## Configuration Changes

Remove `SEC_CIKS` from the scheduled workflow and from normal production configuration.

Keep test-only fixture injection supported for deterministic unit tests.

No SEC secret/API key is required.

## Testing

Use TDD and add coverage for:

1. Daily index parsing and filtering.
2. Only target forms trigger enrichment.
3. CIK-to-ticker resolution through SEC mapping data.
4. Duplicate/accession handling across overlapping discovery windows.
5. Unrelated 8-K filings are ignored.
6. Individual enrichment failures degrade gracefully.
7. Workflow no longer references `SEC_CIKS`.
8. Existing fixture-based SEC tests continue to work.

All existing tests must remain green.

## Non-goals for This Change

- Historical multi-year SEC backfill. That is a separate follow-up because it has different volume/rate-limit concerns.
- Adding new Event Radar event taxonomies beyond the currently supported SEC categories.
- Building a paid real-time SEC feed.
- Reworking the A/B related-stock UI.

## Follow-up

After this change lands, the next highest-value project is historical event backfill so the real-price backtest has enough comparable samples to produce meaningful historical edge statistics.
