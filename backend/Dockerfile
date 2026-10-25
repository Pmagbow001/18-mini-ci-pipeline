FROM node:22-bookworm-slim AS node

FROM python:3.12-slim
WORKDIR /srv

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && adduser --disabled-password --gecos "" --uid 10001 appuser

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser backend/app ./app
COPY --chown=appuser:appuser backend/tests ./tests
COPY --chown=appuser:appuser sample-repo /sample-repo

USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
