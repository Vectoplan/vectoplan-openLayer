FROM python:3.11-slim AS libredwg-builder

ARG LIBREDWG_VERSION=0.13.3
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl xz-utils \
  && curl -fsSL "https://ftp.gnu.org/gnu/libredwg/libredwg-${LIBREDWG_VERSION}.tar.xz" -o /tmp/libredwg.tar.xz \
  && mkdir -p /tmp/libredwg \
  && tar -xJf /tmp/libredwg.tar.xz -C /tmp/libredwg --strip-components=1 \
  && cd /tmp/libredwg \
  && ./configure --prefix=/usr/local --disable-bindings \
  && make -j"$(nproc)" \
  && make install-strip

# Produktionsnah, klein, ohne Root, Gunicorn
FROM python:3.11-slim

# System-Basics
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENLAYER_DWG_CONVERTER=/usr/local/bin/dxf2dwg

# Optional: Zeit/Locales (keine harte Abhängigkeit)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates curl tini \
  && rm -rf /var/lib/apt/lists/*


COPY --from=libredwg-builder /usr/local/bin/dxf2dwg /usr/local/bin/dxf2dwg
COPY --from=libredwg-builder /usr/local/lib/libredwg.so* /usr/local/lib/
RUN ldconfig
# User anlegen
RUN useradd -u 10001 -m -s /usr/sbin/nologin svc

WORKDIR /service

# Requirements separat für Layer-Caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Quellcode
# Struktur:
# /service/app.py
# /service/app/routes/*.py
# /service/templates/*
# /service/static/*
# /service/.env        (wird zur Laufzeit via docker-compose gemountet/gesetzt)
COPY . .

# Rechte
RUN chown -R svc:svc /service
USER svc

# Port nur dokumentieren (Expose)
EXPOSE 8090

# Healthcheck optional (Compose kann eigenen verwenden)
# HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
#   CMD curl -fsS http://127.0.0.1:8090/health || exit 1

# Start: gunicorn mit wsgi-Bridge, damit der Namenskonflikt app.py <-> app/ kein Problem ist
# OPENLAYER_PORT kann per ENV überschrieben werden
ENV OPENLAYER_PORT=8090
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["gunicorn","-w","2","-b","0.0.0.0:8090","wsgi:application","--timeout","60","--access-logfile","-","--error-logfile","-"]
