# NEWS_FUTURE Compression Design

## Intent
NEWS_FUTURE should surface a small set of decision-relevant forward catalysts, not every article that happens to contain a future date and a broad catalyst word.

## Observed live baseline
- 215 live candidates in the 7-day diagnostic window.
- 107 were `PRODUCT_LAUNCH`; many were promotions, discounts, goods, campaigns, or unrelated articles.
- 28 were `LISTING`, duplicating the official KIND IPO source.
- All 215 lacked an extracted ticker and fell back to `^KS11`, so article-level duplication creates especially noisy dashboard rows.

## Decisions
- Remove `LISTING` from NEWS_FUTURE; KIND remains the authoritative Korean IPO/listing source.
- Tighten `PRODUCT_LAUNCH` to explicit launch language such as `신제품/신작/정식/글로벌/서비스/플랫폼 출시` or `제품 공개`; reject promotion/discount/goods/coupon/campaign/update-only language.
- Require the future-time expression and catalyst language to be locally linked in the same nearby text span so unrelated dates elsewhere in the article do not create false events.
- Broad windows (`YEAR`, `HALF_YEAR`, `QUARTER`) are allowed only for high-impact event types: `PLANT_OPERATION`, `APPROVAL`, `CLINICAL_RESULT`, `M_AND_A`, `CAPEX`, `CAPEX_FINANCING`, `POLICY`, `COURT_RULING`, `TENDER`.
- Collapse duplicate articles into one event using normalized company + event type + date window as the cluster identity. Use a stable cluster-based source UID instead of article URL.
- Preserve the representative article URL/title as evidence and record `cluster_article_count` in `raw_payload`.
- Keep strong market-wide policy/court/tender events even when ticker extraction falls back to `^KS11`; reject obviously low-quality/generic company labels for company-specific event types.

## Non-goals
- Do not add a full DART/KRX company-name-to-ticker resolver in this patch.
- Do not delete canonical history in this patch; fresh collection/export will replace visible site rows through normal pipeline behavior.
- Do not change official-source collectors (FOMC/FDA/KIND/DART/SEC).

## Deployment
After merge, run one fresh scheduled-collection-equivalent execution so `site/data` is regenerated with the IPO/CB export filter and compressed NEWS_FUTURE output, then verify GitHub Pages deploys that data.
