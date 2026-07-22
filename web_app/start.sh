#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py sync_sheets
python manage.py verify_parity
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8080}" --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile -
