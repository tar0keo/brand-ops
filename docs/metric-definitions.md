# Metric definitions

Owner: Analytics. Changes go through pull request.

| Metric | Definition | Status |
|---|---|---|
| net_profit | Revenue minus ad spend, plus (TBD) refunds, chargebacks, tooling, creative, staff | TBD, decide first |
| roas | revenue / ad_spend | Draft |
| conversion_rate | orders / sessions | Draft |
| ai_citation_share | Share of tracked prompt runs where the brand is cited | Draft |
| trustpilot_score | Average star rating over the last 90 days | Draft |

## GA4 metrics (source: ga4)

Each row carries a `channel` dimension. AI referrals use `channel = ai_referral` plus an `engine` dimension.

| Metric | GA4 field | Notes |
|---|---|---|
| sessions | sessions | |
| key_events | keyEvents | Whatever each property marks as a key event |
| transactions | transactions | Ecommerce purchases |
| revenue | totalRevenue | Differs from ad-platform revenue; do not add the two |

## File-based sources

| Source | Metrics | Dimensions |
|---|---|---|
| google_ads | ad_spend, clicks, impressions, conversions, revenue | campaign |
| geo_tracker | geo_prompt_runs, geo_mentions | engine |
| bot_logs | ai_crawler_hits, ai_crawler_errors | bot (errors also carry status) |

ai_citation_share = geo_mentions / geo_prompt_runs. It counts "brand mentioned", not necessarily linked.

## Meta Ads and Trustpilot

| Source | Metrics | Dimensions |
|---|---|---|
| meta_ads | ad_spend, clicks, impressions, conversions, revenue | campaign |
| trustpilot | reviews_new, reviews_replied | stars (on reviews_new) |

- meta_ads uses the same metric names as google_ads. Spend can be summed across ad sources. Revenue is platform-reported with its own attribution window, so it overlaps GA4 and Google Ads revenue; do not add them.
- trustpilot_score over a window = sum(stars x reviews_new) / sum(reviews_new). Replies are counted on the review's date, not the reply date.
