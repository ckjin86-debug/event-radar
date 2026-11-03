# Event Radar correctness repair

Goal: Repair the reported related-stock, news and backtest defects without inventing relationships or historical outcomes.

Architecture: Keep the existing Python collectors/pipeline/export and static JavaScript dashboard. Revalidate persisted news using the same date/catalyst rules as ingestion; expose resolved securities in the list contract; calculate each event/security sample separately.

- [ ] Reproduce expired/explicit-year/relative-month news parsing and unrelated historical-date selection. Reject retrospective or unsupported dates, prefer a future catalyst clause, and revalidate canonical news on export.
- [ ] Reproduce blank dashboard tickers despite resolved securities. Export and search all securities, retain source and known date, persist the OpenDART registry cache for credential-free rebuilds.
- [ ] Reproduce multiple-ticker strategy failure, incorrect benchmark compounding and fabricated D0 from stale prices. Correct calculations, exclude period-only/cancelled peers, and bound peer outcomes to the target information cutoff.
- [ ] Run the full pytest suite and JavaScript behavioral checks. Rebuild public JSON from existing canonical data and cached actual prices. Inspect desktop/detail/mobile rendering and deliver the verified changes through GitHub.

Review focus: missing prices must remain missing; period schedules must not become exact historical samples; unrelated criminal/political stories must not pass just because of a keyword; proxy indices must never display as the IPO security; cached rebuilds must retain verified stock mappings.
