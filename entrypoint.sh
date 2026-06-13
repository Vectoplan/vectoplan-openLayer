#!/usr/bin/env bash
set -e
python -m utils.db_init || true
exec gunicorn -w 2 -k gthread -t 300 -b 0.0.0.0:${DATA_PORT:-8090} "app:create_app()"
