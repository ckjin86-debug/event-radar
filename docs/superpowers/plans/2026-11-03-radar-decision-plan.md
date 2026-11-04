# Event Radar decision depth implementation plan

Spec: `docs/superpowers/specs/2026-11-03-radar-decision-design.md`

Execution: inline under executing-plans, followed by one independent whole-change review. The user explicitly requested both recommended improvements together; proceed with reversible implementation and the existing authorized GitHub deployment.

## Global constraints

Preserve canonical IDs/manual relations; distinguish direct/economic/context/proxy. No fabricated events/prices or paid dependencies. Enforce historical quote and D0 cutoffs. Use event counts for confidence and ticker counts only for security samples. Missing market context remains null. Keep static routes and the existing collector workflow.

## Tasks

- [ ] 1. Repair disjoint price-cache coverage in `prices/base.py` with an interior-gap regression test; retain incremental tail/head behavior. Extend official FOMC history collection and parse cross-month meetings/notation votes correctly; keep historical rows separate from the future radar. Fetch missing actual benchmark history.
- [ ] 2. Add conservative `evidence_relations.py` extraction from existing dated articles; test explicit pairs, negation, three-party ambiguity, cutoff and existing manual-precedence. Restrict body-only company mentions to context candidates; resolve existing economic relations through detected issuer tickers and preserve URLs/known dates.
- [ ] 3. Add `insights.py` for explicit schedule/relation/history/market priority components and reasons/missing inputs. Add recent market snapshots from actual prices. Add historical coverage/outcome exports without relaxing peer matching. Test event-vs-security confidence, absent/stale prices, and multi-ticker historical outcomes.
- [ ] 4. Upgrade dashboard and details with priority explanations, evidence summary, upcoming/watch filters, related-stock reasons, price context, and per-event/ticker history outcomes. Add Node behavioral tests; keep period windows and empty states explicit.
- [ ] 5. Run full verification, source-backed historical expansion/rebuild, independent review, browser checks and GitHub Pages deployment; record before/after data coverage and limitations.

## Review focus

Disjoint cache intervals, holidays/closed sessions, hypothetical economic relations, one event with many tickers, sparse/stale prices, duplicate historical sources, and current context leaking into historical results.
