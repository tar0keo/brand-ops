# Research runner

The runner asks the consumer questions in `config/research.yaml` of an AI engine and saves the answers in the file format the Market research tab imports. It does not browse the web itself: it asks the engine through its API, and the engine searches the web when its search option is on.

Only **Claude** can be run so far. The other engines in the config (ChatGPT, Gemini, Perplexity, Google results) are still entered by hand or imported from files. Adding another engine means writing a small class in `runner/engines.py` that turns one question into an answer, and giving that engine an `api:` block in the config.

## One-time setup
1. Create an API key in the Claude Console and put it in the `ANTHROPIC_API_KEY` environment variable. In PowerShell, for the current window: `$env:ANTHROPIC_API_KEY = "your-key"`. To keep it for later sessions, `setx ANTHROPIC_API_KEY "your-key"` stores it in your Windows user environment, where anyone using your account can read it. The key is never written to a file or printed.
2. Web search must be enabled for your organization in the Claude Console (an administrator can do this). Without it the API refuses the request, and the runner says so.
3. Run it from the project folder with Python. It is not part of the packaged Windows app.

## Using it
| Command | What it does |
|---|---|
| `py -m runner --dry-run` | Lists what would be asked and the cost limits. Calls nothing. Start here. |
| `py -m runner --category auto --questions 1` | A first real test: one question. |
| `py -m runner` | Asks every category's questions (up to 40). Writes a file; then use **Import inbox folder** in the app. |
| `py -m runner --import` | The same, and loads the results straight into the app. Use this for scheduled runs. |

Options: `--category ID`, `--questions N` (per category), `--max-runs N` (safety cap, default 40), `--within-days N` (skip questions this engine already answered in the last N days, default 6, so a weekly run only fills gaps), `--force` (ask anyway), `--model NAME`, `--no-system` (ask the bare question), `--delay SECONDS`, `--home FOLDER`, `--out FOLDER`.

By default it reads the questions and the database of the desktop app (`%APPDATA%\BrandOps` on Windows), so the app and the runner always agree. Use `--home` for a different data folder.

## What it asks, and how
- **Questions** come from the config, one per category question, asked exactly as written.
- **Settings** for the engine are in `config/research.yaml` under `api:`: `model`, `web_search` (true or false), `max_searches` per question, and an optional `country` (two letters) to localise the search. The defaults are the Sonnet model, web search on, 4 searches.
- **A short instruction** is sent with each question: answer as to a consumer, and list any companies as a numbered list, best first. That makes the answer easy to read into a ranked list. It is the one way the runner differs from a customer simply typing the question; `--no-system` removes it, at the price of more answers needing a check.

## Cost
Each question can use up to `max_searches` web searches. Search is billed per search on top of the normal token costs, and the provider documents it as token-heavy, so check the current prices before a big run. `--dry-run` prints the maximum number of searches a run could use. `--max-runs` caps a run, and `--within-days` stops repeat questions being paid for twice.

## Where the results go
- A good run writes `data_inbox/research/runner-claude-<date-time>.jsonl` (inside the data folder). Import it with **Import inbox folder** on the Market research tab, or let `--import` do it. It then appears in Latest results, Trends over time, and the report. Running again later adds new runs and never overwrites older ones.
- If the list of companies cannot be read reliably from an answer (fewer than 3 names, or less than 60% of the list items look like company names), that answer goes to `data_inbox/research/needs_review/` with the full text and the reason, and is left out of the import file. Read it and add the list by hand if it is worth keeping.
- The file also keeps the full answer text and the sources the engine cited.

## Limits
- **It is not a copy of what customers see.** The API gives a consistent, repeatable answer, but the Claude app has its own settings, personalisation, and model choice. Treat it as a steady measuring instrument: compare weeks with weeks, and read the full answers when something looks odd.
- **Reading the list is rule-based.** It copes with numbered lists, headings, and bullets, bold or linked names, and drops lists of advice. Unusual layouts land in needs_review.
- **Web addresses** come from links in the answer, or from a cited source that clearly belongs to the company. Companies without one are still counted by name.
- **It stops on a bad key** and after three failures in a row, and keeps whatever it already collected.

## Running it every week
Windows Task Scheduler: create a weekly task whose action runs `py -m runner --import` with the project folder as the start location. The task runs as you, so it sees your `ANTHROPIC_API_KEY` if you used `setx`. On Mac or Linux use cron with the same command and the key exported in the job.
