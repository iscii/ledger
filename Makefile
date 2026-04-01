.PHONY: dev build up down test clean demo demo-with-ui

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

demo:
	uv run python examples/demo_agent.py

demo-with-ui:
	@echo "Starting API server in background..."
	@BACKSTEP_DB=$${BACKSTEP_DB:-$$HOME/.backstep/backstep.db} \
	  uv run backstep-api &
	@echo "Running demo agent..."
	@sleep 1
	@uv run python examples/demo_agent.py
	@echo ""
	@echo "Open http://localhost:3000 to see the session"

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
