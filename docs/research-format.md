# Market research: file format

The idea: instead of checking every brand in every engine, ask a few consumer-style questions per loan category ("What are the 10 best personal loan companies?") in each AI engine and in Google, record who gets listed, and compare. The questions live in `config/research.yaml`, and you can edit them for each category from the Market research tab (Edit the questions for this category). The same files are used whether you type them in or an automated runner (your service accounts) produces them.

## What to record
For each question, in each engine, one list of the companies named, in the order shown. Include the web address when the engine gives one, so the same company is counted once across engines. Use `google_organic` (kind "seo") for the normal Google results list: that is the SEO baseline the AI answers are compared with.

## Option 1: CSV (best for typing by hand)
One row per listed company. Excel and Google Sheets "CSV" exports both work.

| Column | Required | Notes |
|---|---|---|
| date | yes | The day you asked. 2026-10-05 or 10/05/2026 |
| category | yes | A category id (`auto`) or its label (`Auto loans`) from config/categories.yaml |
| question | yes | Exactly as asked |
| engine | yes | An id or label from config/research.yaml (`chatgpt`, `gemini`, `perplexity`, `claude`, `google_ai_overview`, `google_organic`) |
| rank | yes | Position in the answer: 1, 2, 3 ... |
| name | yes | The company as listed |
| url | no | The link given, if any |
| note | no | Anything you want to remember |
| answer, model, location | no | The full answer text; the model or version; where the search was made from |

Other headings are understood too (for example prompt for question, position for rank, company for name, link for url). Copy `sample_data/research/example.csv` to start.

## Option 2: JSON Lines (best for automated runners)
One line per run. Keeps the full answer and the sources the engine cited, which a flat CSV can't hold well.

```json
{"date": "2026-10-05", "category": "auto", "question": "Where can I refinance my car loan?", "engine": "gemini", "model": "example-model", "location": "US", "answer": "Full answer text (optional)", "results": [{"rank": 1, "name": "Acme Lending", "url": "https://www.acme-lending.example.com"}], "citations": [{"url": "https://guide.example.org/refinance", "title": "Refinancing guide"}]}
```

- `results` items can be plain names (`["Acme", "Brand 7"]`); rank then follows the order.
- `citations` can be plain addresses or objects with url and title.
- A `.json` file holding one object, a list of runs, or `{"runs": [...]}` also works. See `sample_data/research/example.jsonl`.

## Getting files in
- **Import files** on the Market research tab, or
- put files in `data_inbox/research/` and click **Import inbox folder**. Automated runners should write their `.jsonl` files here.

A file is imported all or nothing: if any row has a problem (unknown engine, bad rank, empty name), nothing from that file is loaded and the problems are listed with row numbers, so a half-loaded file never skews the numbers. Importing the same run again (same date, category, question, engine, model, and location) replaces it instead of duplicating it.

## How the comparison works
For each question and engine, the app uses the latest run within the selected period. Companies are matched to your brands by site first, then by name (whole names only, so "Brand 7" never matches "Brand 70"). The category view shows how often each company is listed in AI answers versus SEO results, who ranks higher where, who appears in one but not the other, how far each AI answer overlaps with the Google list, which sites the AI answers cite, and which question and engine combinations still have no run. In demo mode, imports are kept in memory only.
