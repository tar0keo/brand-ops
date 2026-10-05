# Adding a connector

1. Create `connectors/<name>/__init__.py` with a `Connector(BaseConnector)` class.
2. Implement `fetch(start, end)` yielding `MetricRow` objects (brand_id, day, source, metric, value, dimensions).
3. Read credentials from environment variables and add the names to `.env.example`.
4. Add a test in `tests/` that checks rows against `config/brands.yaml`.
5. Run `python -m connectors.run <name> --dry-run`, then open a pull request.
