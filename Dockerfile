FROM python:3.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libssl-dev pkg-config && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-webui.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip && /opt/venv/bin/pip install -r requirements.txt -r requirements-webui.txt

FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libssl3 && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . /app
RUN chmod +x /app/docker-entrypoint.sh && mkdir -p /app/downloads /app/sessions && chown -R app:app /app/downloads /app/sessions
USER app
EXPOSE 8080
VOLUME ["/app/downloads", "/app/sessions"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["webui"]
