.PHONY: audit check dev format install lint migrate test typecheck

install:
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade 'pip>=26.1.2'
	.venv/bin/pip install -e '.[dev]'

dev:
	.venv/bin/uvicorn growth_os.main:app --reload

migrate:
	.venv/bin/alembic upgrade head

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff format .

typecheck:
	.venv/bin/mypy

audit:
	.venv/bin/pip-audit

check: lint typecheck test audit

