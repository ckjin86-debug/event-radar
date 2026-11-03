# Evidence-First Related Securities + News Recall Design

## Intent
Event Radar should connect each scheduled event to investable securities before backtesting, while avoiding theme-based guesswork. NEWS_FUTURE should also surface more than the current four 7-day survivors without returning to article-level noise.

## Goals
- Resolve listed Korean and U.S. companies mentioned directly in an event to real tickers.
- Treat directly named listed companies as Grade A relations.
- Expand to Grade B only from stored, dated relation evidence with score >= 60.
- Preserve look-ahead protections already present in `relations.py`.
- Increase NEWS_FUTURE recall selectively while keeping title-level future/catalyst evidence and clustering.

## Non-goals
- No LLM/theme guessing for related stocks.
- No broad sector peer expansion without evidence.
- No backtest strategy redesign in this change; this change supplies cleaner event-security inputs for the next phase.

## Approach
### Chosen: official entity universe + evidence relations
- Korea: OpenDART `corpCode.xml` supplies `corp_name` + six-digit `stock_code`.
- U.S.: SEC `company_tickers.json` supplies issuer title + ticker.
- Match normalized company names appearing in `event_name`, `primary_company`, and `evidence_text`.
- Directly named listed issuers become Grade A (`DIRECT_MENTION`, score 100).
- Existing dated `relations.csv` expands from every Grade A entity/ticker to Grade B/A according to stored score.

### Rejected: theme keyword related stocks
Fast but contaminates backtests with weak causal links.

### Rejected: manual-only ticker mapping
Precise but does not scale and leaves NEWS_FUTURE market-proxy events unusable.

## News recall adjustment
Keep current title-only qualification, temporal linkage, clustering, listing exclusion, and false-positive filters. Increase recall by expanding search queries toward high-impact scheduled catalysts (groundbreaking/operation, approval/clinical, court ruling, M&A completion, contract/tender) and allow strong MONTH windows for those high-impact types. PRODUCT_LAUNCH remains exact-date only.

## Success criteria
- A NEWS_FUTURE event naming a listed issuer no longer defaults to `^KS11` when the issuer can be resolved.
- Multiple directly named listed companies can be mapped as Grade A for one event.
- Grade B comes only from existing evidence relations and remains time-aware.
- Existing relation tests continue to pass.
- Live NEWS_FUTURE diagnostic rises above four survivors without reintroducing obvious promotion/listing noise; target operating band is roughly 10-25 candidates per 7-day scan, treated as a tuning target rather than a hard invariant.
