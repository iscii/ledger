.PHONY: dev build up down test clean clean-db demo demo-with-ui api _check_root

_check_root:
	@test -f pyproject.toml || \
	  (echo "Error: run from project root" && exit 1)

dev:
	npm run dev

build:
	docker compose build

up:
	docker compose up

down:
	docker compose down

test:
	uv run pytest tests/

api: _check_root
	uv run backstep-api

demo: _check_root
	uv run python examples/demo_agent.py

demo-with-ui: _check_root
	@echo "[backstep] Starting API..."
	@uv run backstep-api &
	@sleep 1
	@echo "[backstep] Running demo..."
	@uv run python examples/demo_agent.py

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete

clean-db:
	rm -f backstep.db demo.db test_ledger.db
	rm -rf ~/.backstep/
