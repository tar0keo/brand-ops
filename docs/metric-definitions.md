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
