FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system sortax && adduser --system --ingroup sortax sortax

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN python -m pip install --upgrade pip && python -m pip install .

USER sortax
EXPOSE 8000

CMD ["uvicorn", "sortax.main:app", "--host", "0.0.0.0", "--port", "8000"]
