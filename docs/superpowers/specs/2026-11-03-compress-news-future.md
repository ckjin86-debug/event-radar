# NEWS_FUTURE Compression Design

## Intent
NEWS_FUTURE should surface a small set of decision-relevant forward catalysts, not every article that happens to contain a future date and a broad catalyst word.

## Observed live baseline
- 215 live candidates in the 7-day diagnostic window.
- 107 were `PRODUCT_LAUNCH`; many were promotions, discounts, goods, campaigns, or unrelated articles.
- 28 were `LISTING`, duplicating the official KIND IPO source.
- All 215 lacked an extracted ticker and fell back to `^KS11`, so article-level duplication created especially noisy dashboard rows.

## Decisions
- Remove `LISTING` from NEWS_FUTURE; KIND remains the authoritative Korean IPO/listing source.
- Use the news **title** for future-date and catalyst qualification. Description text remains evidence but cannot create an event by itself.
- Tighten `PRODUCT_LAUNCH` to explicit launch language such as `신제품/신작/정식/글로벌/서비스/플랫폼 출시` or `제품 공개`; reject promotion/discount/goods/coupon/campaign/update-only language.
- Require `PRODUCT_LAUNCH` to have an `EXACT_DATE`; month/quarter/year launch windows are too noisy for the main radar.
- Require the future-time expression and catalyst language to be locally linked in the same title clause.
- Broad windows (`YEAR`, `HALF_YEAR`, `QUARTER`) are allowed only for high-impact event types: `PLANT_OPERATION`, `APPROVAL`, `CLINICAL_RESULT`, `M_AND_A`, `CAPEX`, `CAPEX_FINANCING`, `POLICY`, `COURT_RULING`, `TENDER`.
- Parse `내달/다음달 N일` as an exact date before falling back to a month window.
- Treat `인수권` as a financing/warrant term, not an M&A `인수` signal.
- Collapse duplicate articles into one event using normalized company + event type + date window as the cluster identity. Use a stable cluster-based source UID instead of article URL.
- Preserve the representative article URL/title as evidence and record `cluster_article_count` and source URLs in `raw_payload`.
- Keep strong market-wide policy/court/tender events even when ticker extraction falls back to `^KS11`; reject obviously low-quality/generic company labels for company-specific event types.

## Live result
With the same 7-day live diagnostic approach, the candidate set fell from **215 to 4**:
- Samsung Biologics acquisition completion (`M_AND_A`)
- Heungkuk Life / Hanwha Systems court ruling (`COURT_RULING`, exact day derived from `내달 6일`)
- Silver Palace global release (`PRODUCT_LAUNCH`, exact date)
- Hyundai Motor Group Saemangeum AI Valley groundbreaking (`CAPEX`)

The remaining four still use `^KS11` because company-name-to-ticker resolution is intentionally outside this patch.

## Non-goals
- Do not add a full DART/KRX company-name-to-ticker resolver in this patch.
- Do not delete canonical history in this patch; fresh collection/export will replace visible site rows through normal pipeline behavior.
- Do not change official-source collectors (FOMC/FDA/KIND/DART/SEC).

## Deployment
After merge, run one fresh scheduled-collection-equivalent execution so `site/data` is regenerated with the IPO/CB export filter and compressed NEWS_FUTURE output, then verify GitHub Pages deploys that data.
