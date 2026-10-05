# Central app

Python server (standard library only) plus one static page. No build step.

    python -m app.server --demo        # fake data, no database needed
    python -m app.server               # reads the warehouse (needs DATABASE_URL)

Open http://127.0.0.1:8000. Views: Scorecard, Media buying, GEO and search, Reputation, Data status.
Each figure is compared with the previous period of the same length.

- `app/summary.py` turns warehouse rows into per-brand metrics (the tested logic).
- `app/demo.py` generates deterministic demo rows with built-in stories (Brand 1 declining, Brand 2 crawlers blocked).
- Profit is provisional: ad revenue minus ad spend. See docs/metric-definitions.md.

## Actions

The Actions view turns scorecard results into proposed tasks (rules in `config/task_rules.yaml`, logic in `app/tasks.py`) and can create them in Jira or export a CSV. See docs/jira.md.

## Brands and dossier

The Brands tab adds, archives, and manages sites for brands (saved to `config/brands.yaml`). "Open dossier" in the header renders an HTML report with charts. See docs/brands-and-dossier.md.
