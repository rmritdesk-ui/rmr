FROM python:3.13-slim-bookworm AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RMR_HOST=0.0.0.0 \
    RMR_PORT=8000 \
    RMR_DATA_DIR=/data


RUN groupadd --system --gid 10001 rmr && useradd --system --uid 10001 --gid rmr --home-dir /app rmr
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

FROM dependencies AS verification
COPY pyproject.toml ./
COPY rmr_platform ./rmr_platform
COPY public ./public
COPY templates ./templates
COPY static ./static
COPY qa ./qa
COPY scripts/container-entrypoint.sh /usr/local/bin/rmr-entrypoint

# Fail the Docker build itself if any launcher-invoked gate is omitted or cannot execute.
RUN test -f /app/qa/v5412_interaction_regression_gate.py \
 && test -f /app/qa/v5412_theme_preservation_gate.py \
 && test -f /app/qa/v5412c_container_dependency_audit.py \
 && test -f /app/rmr_platform/product_owner_qc.py \
 && test -f /app/rmr_platform/server.py \
 && python /app/qa/v5412c_container_dependency_audit.py --root /app --entrypoint /usr/local/bin/rmr-entrypoint --output /tmp/V5412C-CONTAINER-DEPENDENCY-AUDIT-BUILD.json \
 && python /app/qa/v5412_interaction_regression_gate.py --root /app --output /tmp/V5412-INTERACTION-REGRESSION-BUILD.json \
 && python /app/qa/v5412_theme_preservation_gate.py --root /app --output /tmp/V5412-THEME-PRESERVATION-BUILD.json

RUN chmod 0755 /usr/local/bin/rmr-entrypoint && mkdir -p /data/training /data/backups && chown -R rmr:rmr /app /data

USER rmr

# Optional CI/development target; never the production image.
FROM verification AS test
USER root
COPY requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt \
 && python -m playwright install --with-deps chromium
COPY tests ./tests
COPY scripts/test_*_postgres.py ./scripts/
COPY scripts/container-entrypoint.sh ./scripts/
COPY docker-compose.production.yml ./
COPY docs/CPANEL-PRODUCTION-DEPLOYMENT.md ./docs/
COPY deploy/apache-rmr-ssl-include.conf.example ./deploy/
COPY .env.example ./
ENV RMR_DATA_DIR=/tmp/rmr-release-tests \
    RMR_AUTO_MIGRATE=false \
    RMR_AUTO_SEED=false \
    RMR_PIQ_WORKER_ENABLED=false \
    RMR_CB1_WORKER_ENABLED=false \
    RMR_PIQ_LIVE_DISCOVERY_ENABLED=false \
    RMR_PIQ_LIVE_RESEARCH_ENABLED=false
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

# Runtime gets verified source/assets only, no qa/tests/reports/local env.
FROM dependencies AS runtime
ARG RMR_VERSION=5.4.1.2-interaction-regression-correction-po1
ARG RMR_REVISION=local
LABEL org.opencontainers.image.title="RMR Global with integrated ProspectIQ" \
      org.opencontainers.image.version="${RMR_VERSION}" \
      org.opencontainers.image.revision="${RMR_REVISION}"
COPY --from=verification --chown=rmr:rmr /app/rmr_platform ./rmr_platform
COPY --from=verification --chown=rmr:rmr /app/public ./public
COPY --from=verification --chown=rmr:rmr /app/templates ./templates
COPY --from=verification --chown=rmr:rmr /app/static ./static
COPY --from=verification /usr/local/bin/rmr-entrypoint /usr/local/bin/rmr-entrypoint
RUN mkdir -p /data/training /data/backups && chown -R rmr:rmr /data
USER rmr
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=10s --timeout=8s --start-period=20s --retries=12 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)); raise SystemExit(0 if data.get('status')=='healthy' else 1)"

ENTRYPOINT ["/usr/local/bin/rmr-entrypoint"]
CMD ["python", "-m", "rmr_platform.server"]
