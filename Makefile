.PHONY: up down sync-example dry-run test
up:
	docker compose up -d
down:
	docker compose down
sync-example:
	DATABASE_URL=$${DATABASE_URL:-postgresql://brandops:brandops@localhost:5432/brandops} python -m connectors.run example --days 30
dry-run:
	python -m connectors.run example --days 3 --dry-run
test:
	pytest -q
