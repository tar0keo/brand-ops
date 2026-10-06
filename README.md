# brand-ops

Central brand operations app: connectors pull data from ad, analytics, GEO, reputation, and work-management tools into one warehouse, tagged by brand.

## Quickstart

1. `cp .env.example .env`
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install -r requirements-dev.txt`
4. `make test`
5. `make up` (starts local Postgres and creates the tables)
6. `make sync-example` (loads fake ad data for every brand)

`make dry-run` runs the example connector without a database.

## Layout

- `connectors/` one folder per source, all writing the same row shape
- `warehouse/migrations/` table definitions
- `config/` brands, tracked GEO prompts, alert thresholds
- `app/` central app (not built yet)
- `sample_data/` fake data generator (not built yet)
- `docs/` metric definitions and runbooks

## Rules

- Never commit credentials or data exports. Use `.env` locally and GitHub Secrets in workflows.
- Brands, prompts, and thresholds change by pull request.

## Desktop app

`python brandops_desktop.py` runs the app in its own window with a local database. See docs/desktop.md.

## Research runner

`python -m runner --dry-run` shows what the research runner would ask an AI engine; see docs/research-runner.md.
