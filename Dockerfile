FROM python:3.14.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt ./
RUN python -m pip install --upgrade "pip==25.3" \
    && python -m pip install --requirement requirements.txt \
    && python -m pip check


FROM python:3.14.7-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home \
        --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app order_assistant ./order_assistant
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini

USER app
EXPOSE 8000

CMD ["uvicorn", "order_assistant.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
