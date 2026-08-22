FROM python:3.14.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY requirements.txt ./
RUN python -m pip install --upgrade "pip==25.3" \
    && python -m pip install --requirement requirements.txt \
    && python -m pip check

FROM python:3.14.7-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:${PATH}"
RUN groupadd --gid 10002 stub \
    && useradd --uid 10002 --gid stub --create-home --shell /usr/sbin/nologin stub
WORKDIR /stub
COPY --from=builder /opt/venv /opt/venv
COPY --chown=stub:stub erp_stub ./erp_stub
USER stub
EXPOSE 8080
CMD ["uvicorn", "erp_stub.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
