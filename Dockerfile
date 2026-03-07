# ---------- Stage 1: Build frontend ----------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Runtime ----------
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        hle-client==1.15.0 \
        fastapi \
        uvicorn

COPY backend/ /app/backend/
COPY --from=frontend /build/dist/ /app/backend/static/
COPY run.sh /run.sh
RUN chmod +x /run.sh && mkdir -p /data/logs

EXPOSE 8099
VOLUME /data

ENV HLE_API_KEY=""
ENV HLE_PORT=8099

CMD ["/run.sh"]
