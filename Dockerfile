# Frontend is pre-built by hle-webapp and committed to frontend/dist/
# via the sync-webapp.yml workflow. No Node.js needed at image build time.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        hle-client==2604.2 \
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

CMD ["/run.sh"]
