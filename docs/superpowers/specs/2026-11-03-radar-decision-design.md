# Event Radar evidence and historical depth

User direction: improve event selection and related-stock/historical detail together, using the recommended combined approach. Existing Python pipeline and GitHub Pages remain the platform. Implementation choices below are the builder's decisions.

## Approach

An appearance-only refresh would leave empty studies and constant scores. Loosening matching would increase numbers by comparing unrelated events. Instead, repair price coverage, add source-backed historical schedules, extract narrowly evidenced economic connections, and display a transparent monitoring priority with its missing inputs.

## Result

The dashboard opens with a compact evidence summary and upcoming events ordered by monitoring priority. Each row explains schedule precision, strongest relationship, historical sample availability, and available recent price/volume observations. This is a monitoring score, not a probability or a buy recommendation. Unknown market inputs contribute no fictitious points.

Detail pages show direct participants, economic counterparties and context/theme mentions separately, with the quoted evidence, URL and known date. Economic connections may be extracted only from a dated same-clause statement with exactly two listed parties and an explicit ownership, investment, supply or contract relationship. Negated, speculative, multi-company and after-cutoff evidence is excluded. Discovered links remain derived and do not silently overwrite manual canonical relations.

Backtests keep strict country/type/family/grade matching and the D0/quote cutoff checks. They show eligible historical events, events with usable prices, D+5 complete events and event-security samples separately. Each historical card has actual outcomes per ticker. Additional official FOMC history is ingested separately from future radar rows; no invented events or prices. Restore existing Korean historical samples by fetching missing benchmark intervals.

## Constraints

No paid service, new API credential, fabricated price, or permanent manual-relation replacement. Existing IDs and static routes remain usable. Price downloads are cached; disjoint cache blocks do not count as complete coverage. Missing data stays null. Multiple securities in one event do not count as independent historical events for confidence. Current price context is dated and cannot enter historical study results. Completed FOMC meetings are historical records, not future watchlist entries.

## Verification

Use failing-then-passing tests for cache interior gaps, relationship attribution/cutoffs, priority missing data and confidence, history coverage/outcomes, and dashboard filters. Run complete pytest and Node tests, independently review the diff, rebuild using actual source data, verify desktop/mobile/detail views, and deploy through the existing GitHub Pages workflow.
