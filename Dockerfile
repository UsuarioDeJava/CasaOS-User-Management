# Web UI assets: Tailwind CSS compiled from the templates, and the icon font.
# Everything is served by the app itself, so the UI works without internet.
# Platform independent output, so it runs on the build machine only.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json web/
RUN npm ci --prefix web --no-audit --no-fund
COPY web web
COPY app/templates app/templates
RUN npx --prefix web tailwindcss -c web/tailwind.config.js -i web/input.css \
        -o static/app.css --minify \
 && mkdir -p static/fontawesome/css \
 && cp web/node_modules/@fortawesome/fontawesome-free/css/all.min.css static/fontawesome/css/ \
 && cp -r web/node_modules/@fortawesome/fontawesome-free/webfonts static/fontawesome/

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
COPY --from=web /build/static static

ENV DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=4)"

ARG VERSION=dev
ARG COMMIT=unknown
LABEL org.opencontainers.image.title="CasaOS User Management" \
      org.opencontainers.image.description="Web UI to manage CasaOS users" \
      org.opencontainers.image.source="https://github.com/UsuarioDeJava/casaos-user-management" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT}"

# One worker: the failed-login throttle lives in memory.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", \
     "--access-logfile", "-", "app:app"]
