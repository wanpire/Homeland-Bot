.PHONY: setup build up down restart logs migrate bot test test-down

setup:
	bash scripts/setup.sh

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec bot alembic upgrade head

bot:
	docker compose exec bot python -m app.main

_TEST_COMPOSE = docker compose -f docker-compose.test.yml -p homeland_bot_test

test:
	$(_TEST_COMPOSE) up -d --build
	$(_TEST_COMPOSE) exec -T test-runner pip install -q -r requirements-dev.txt
	$(_TEST_COMPOSE) exec -T test-runner python -m pytest tests/ -v

test-down:
	$(_TEST_COMPOSE) down -v
