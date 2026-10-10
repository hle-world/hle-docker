# Frontend is pre-built by hle-webapp and committed to frontend/dist/
# via the sync-webapp.yml workflow. No Node.js needed at image build time.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        hle-client==2610.5 \
        fastapi \
        uvicorn

COPY backend/ /app/backend/
COPY frontend/dist/ /app/backend/static/
COPY run.sh /run.sh
RUN chmod +x /run.sh && mkdir -p /data/logs

EXPOSE 8099
VOLUME /data

ENV HLE_API_KEY=""
ENV HLE_PORT=8099
# Set to an `hle_...` key (older `hlea_...` tokens also work) to run as a dashboard-managed agent instead of the
# single-tunnel backend + UI. See docker-compose.yml, profile "agent".
ENV HLE_AGENT_TOKEN=""
# Tells hle-client how it was installed, so `hle update` gives image-pull
# guidance instead of guessing from /.dockerenv.
ENV HLE_INSTALL_METHOD=docker

CMD ["/run.sh"]
