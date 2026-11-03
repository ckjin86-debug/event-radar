# IPO / Convertible Noise Filtering Design

## Intent
Event Radar should surface forward-looking events that can plausibly change trading decisions, not every financing or IPO process milestone.

## Decisions
- KIND IPO: emit only `IPO_LISTING` / 상장예정일 as the main event.
- Do not emit bookbuilding start/end, subscription start/end, or payment events.
- DART convertible-related disclosures: generic CB/BW issuance, repricing, repurchase, sale, and other financing notices are excluded.
- Keep only explicit exercise/conversion disclosures that point to an actual new-share listing event, e.g. `전환청구권행사` or `신주인수권행사` with `신주상장`/`상장예정` evidence.
- Existing CAPEX-backed rights-issue behavior is unchanged.
- Existing historical canonical data is not deleted in this patch; new collection is filtered at source. A separate export cleanup can hide stale generic convertible rows if needed.

## Approaches considered
1. Filter only in the site export. Rejected because noisy events would still contaminate canonical data, scoring, and backtests.
2. Filter at collectors. Chosen because noise is stopped before normalization/scoring and keeps downstream logic simpler.
3. Add a market-cap/share-count materiality engine now. Deferred because current DART collector does not have a reliable live denominator for outstanding shares, and adding one would turn this small behavior fix into a larger data-integration project.

## Constraints
- Preserve current collector interfaces and failure isolation.
- Keep fixture compatibility where the fixture represents an explicit conversion-to-listing event.
- TDD: new expectations must fail before production code changes.
