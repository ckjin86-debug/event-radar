# Relation Verification UI Spec

## Goal
Make the Event Radar detail page show how each related stock was produced and whether it is verified/persistent, so users can distinguish direct parties, verified economic relations, theme candidates, proxies, and unmapped events without reading raw CSVs.

## UX
1. Add a top-level **관련주 판단 요약** block before backtest sections.
2. Split current related securities into three visible groups:
   - **검증 A/B**: direct or verified economic relations.
   - **후보 / THEME**: non-persistent thematic candidates.
   - **참고 / 미매핑**: PROXY or UNMAPPED.
3. Each security card shows ticker, grade, relation type/score, provenance state, known date when available, evidence source/text, and a source link when available.
4. Manual/AI-verified A/B relations are visibly marked **영구관계 등록됨**. Auto-discovered A/B are marked **자동 확인**; THEME is **후보**; PROXY is **참고용**.
5. Main event table keeps the compact grade but adds a human-readable mapping status label.

## Data contract
`EventSecurity` and exported JSON may include these optional fields without breaking older rows:
- `evidence_source`
- `source_url`
- `relation_known_date`
- `ingest_mode`
- `from_entity`

Manual relations carry `ingest_mode=MANUAL` and are considered persistent verified relations. Direct event parties may be treated as verified A but not as manual writeback unless a relation row says so.

## Constraints
- Keep the existing static HTML/JS/CSS architecture and GitHub Pages deployment.
- Do not introduce a frontend framework.
- Do not claim THEME/PROXY rows are verified.
- Existing event/backtest behavior must remain unchanged.