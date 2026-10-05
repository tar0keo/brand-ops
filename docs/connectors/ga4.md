# GA4 connector

Pulls daily sessions, key events, transactions, and revenue per brand, split by channel. Sessions from AI engines are tagged `channel = ai_referral` with an `engine` dimension.

## Setup

1. In Google Cloud, create or pick a project and enable the Google Analytics Data API.
2. Create a service account and download its JSON key.
3. In each GA4 property: Admin, Property access management, add the service account email as Viewer.
4. Put each brand's property ID in `config/ga4.yaml`.
5. Locally, set `GOOGLE_APPLICATION_CREDENTIALS` to the key file path, then run `python -m connectors.run ga4 --days 7 --dry-run`.
6. In GitHub, add secrets `GA4_SERVICE_ACCOUNT_JSON` (the whole key file) and `DATABASE_URL`.

## Known limits

- GA4 data can change for 24 to 48 hours after the fact, so schedule runs with `--days 3` or more. Re-loading is safe because rows are upserted.
- Referrer names for AI engines vary, and some AI traffic arrives with no referrer and shows up as direct. Treat the AI numbers as a floor.
- Google AI Overviews clicks are counted as ordinary Google organic search and can't be separated here.
- Large properties may return sampled or thresholded data.
- The connector assumes one GA4 property per brand. If several brands share a property, add a hostname dimension and split on it.
