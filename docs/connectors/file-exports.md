# File-based connectors

These read exports you drop into `data_inbox/`, so no API keys are needed. Run them locally against your database (GitHub Actions cannot see `data_inbox/`, which is git-ignored).

```
python -m connectors.run google_ads --days 30 --dry-run
python -m connectors.run google_ads --days 30
```

Use a large `--days` (such as 365) for a first import of history. Rows outside the window are ignored.

## Google Ads

1. Reports > custom table with columns Day, Campaign, Cost, Clicks, Impr., Conversions, Conv. value.
2. Download as CSV (the UTF-8 and "Excel .csv" variants both work) into `data_inbox/google_ads/`.
3. In `config/file_sources.yaml`, add `campaign_rules` mapping campaign names to brand ids. Every campaign must match, or the run stops and lists the ones that don't.
4. Keep brand names in campaign names so the rules stay simple.

Overlapping exports are safe: for the same day and campaign, the file with the later name wins.

## GEO tracker

1. Export prompt-level results as CSV: date, engine, prompt (or brand), and a mentioned flag.
2. Edit `geo_tracker.columns` in `config/file_sources.yaml` to match your vendor's headers.
3. Each prompt must match a `text` or `id` in `config/prompts.yaml`, or the export needs a brand column.

Output: `geo_prompt_runs` and `geo_mentions` per brand, day, and engine. Raw answer text is not loaded yet.

## AI crawler logs

1. Export Apache or Nginx access logs in combined format (`.log` or `.log.gz`).
2. Put them in `data_inbox/bot_logs/<brand_id>/`, one folder per brand.
3. All files are summed, so don't leave duplicate copies of the same period.

Output: `ai_crawler_hits` per bot and `ai_crawler_errors` per bot and status code.

Limits: bots are identified by user agent, which can be spoofed. CDN logs (such as Cloudflare Logpush) use other formats and need a converter. Google's AI crawling tokens (Google-Extended) don't appear in logs.

## Meta Ads

1. In Ads Manager, build a report at campaign level with Breakdown > By time > Day.
2. Include columns: Campaign name, Amount spent, Impressions, Link clicks, Purchases, Purchases conversion value.
3. Export as CSV into `data_inbox/meta_ads/`.
4. In `config/meta_ads.yaml`, match the column names (the currency in "Amount spent (USD)" varies) and add `campaign_rules`.

Without the Day breakdown the export has date ranges instead of daily rows and can't be loaded. Overlapping exports are safe: for the same day and campaign, the later file name wins.

## Trustpilot

1. In Trustpilot Business, export your reviews as CSV into `data_inbox/trustpilot/`.
2. In `config/trustpilot.yaml`, match the column names and add `brand_rules` that map a domain or business unit to a brand id.

Reviews are de-duplicated by review ID, so overlapping exports are safe. Reviews that were later removed stay in your data until you delete the older files and reload from a fresh export.
