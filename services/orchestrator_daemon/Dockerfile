# SPDX-License-Identifier: MPL-2.0
ARG PYTHON_IMAGE=python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
FROM ${PYTHON_IMAGE}

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.9.8 \
    && uv sync --frozen --no-dev --no-install-project

COPY services/orchestrator_daemon/app ./app
COPY data ./data
COPY configs ./configs
COPY packs ./packs
RUN mkdir -p /var/lib/grnd0 && chown -R 65532:65532 /var/lib/grnd0

USER 65532:65532
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
