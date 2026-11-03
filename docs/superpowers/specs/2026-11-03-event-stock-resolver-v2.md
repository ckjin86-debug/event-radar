# Event Stock Resolver v2 Design

## Goal

Turn Event Radar from a sparse schedule list into a usable event-to-stock pipeline: discover more future catalysts, resolve explicit listed companies automatically, keep market proxies out of A/B stock candidates, and enrich IPO listing dates with evidence-backed related listed companies.

## Current Problems

1. NEWS_FUTURE only yields about four events per live run because discovery uses a narrow fixed query list and requires the future date plus catalyst to be linked in the title only.
2. KIND IPO events use ^KQ11/^KS11 as primary tickers. The relation engine then upgrades those index proxies to A/100 DIRECT, which is not a tradable-company relationship.
3. Korean news events such as 한화시스템 or 삼성바이오로직스 remain UNMAPPED when the article does not include a six-digit ticker even though the listed company name is explicit.
4. IPO events do not search for evidence-backed listed-company relationships such as parent company, largest shareholder, disclosed investor, affiliate, or direct business counterparty.

## Design

### 1. Higher-recall future news discovery

Expand the default Naver queries around future dates and market catalysts. Parse and classify against `title + description`, while preserving the temporal-link guard so unrelated dates and catalysts do not leak through. Keep KIND authoritative for IPO listing dates and continue rejecting generic rights issues.

### 2. Listed-company registry and direct-mention resolution

Build a Korean listed-company registry from OpenDART `corpCode.xml` using the already configured DART API key. Cache it under `data/cache`. Resolve company names mentioned in an event's company/name/evidence to stock codes. Explicit listed-company mentions are A-grade `DIRECT_MENTION` candidates.

Do not treat index/sector proxies (`^KS11`, `^KQ11`, `^GSPC`, `XBI`) as A/B direct securities. They remain informational `PROXY` rows so downstream investment filters can reject them without losing context.

### 3. IPO relationship enrichment

KIND emits IPO listing events with an empty primary ticker rather than a market index proxy. For each IPO event, run bounded Naver enrichment queries for the IPO company with relationship terms such as 최대주주, 모회사, 지분, 투자, 관계사, 공급, 고객. Detect listed-company names through the same DART registry.

Only attach a related listed company when the article text contains both the IPO company and the related listed company plus an explicit relationship term. Score parent/largest-shareholder relationships highest, disclosed investment/stake relationships next, affiliate/business relationships lower. These become B-grade `IPO_*` rows. Do not promote same-industry/theme mentions to B.

### 4. Pipeline integration

Resolve direct listed mentions before theme mapping, merge direct/economic/IPO/theme rows per ticker, and retain the strongest evidence. The generated event-security map and public site data remain the source consumed by bb-invest.

## Safety / Quality Rules

- No look-ahead relationship evidence: article publication time must be at or before the event's current known date context.
- No company-name substring matching shorter than three Korean/Latin characters.
- Exact or normalized listed-company-name mention is required for A direct resolution.
- Market proxies never count as A/B candidates.
- IPO relationship enrichment is evidence-backed; unsupported theme guesses stay absent or THEME, never B.
- A failed DART registry or Naver enrichment call must degrade gracefully and never stop the main pipeline.

## Success Criteria

- Description-only future catalysts can be retained when date and catalyst are temporally linked in the combined title/description text.
- Default future-news query coverage is materially broader than the current 13 queries.
- KIND IPO events no longer export ^KQ11/^KS11 as A/100 direct securities.
- Explicit listed Korean companies in news events resolve to real six-digit tickers.
- IPO events can carry evidence-backed related listed stocks when relationship articles exist.
- Full test suite passes and a live run produces refreshed site data for comparison with the prior 29-event snapshot.