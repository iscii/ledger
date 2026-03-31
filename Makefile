.PHONY: dev build up down test clean

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

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
