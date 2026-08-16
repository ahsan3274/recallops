PYTHON ?= python3

.PHONY: seed test run docker-up reset

seed:
	$(PYTHON) scripts/generate_seed.py

test: seed
	$(PYTHON) -m unittest discover -s tests -v

run: seed
	uvicorn app.main:app --reload

docker-up:
	docker compose up --build

reset:
	curl -X POST http://127.0.0.1:8000/api/reset
