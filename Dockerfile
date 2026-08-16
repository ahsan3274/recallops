FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY agent_cards ./agent_cards
COPY seed ./seed
COPY scenarios ./scenarios

RUN pip install --no-cache-dir ".[google]"

USER 65532:65532

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
