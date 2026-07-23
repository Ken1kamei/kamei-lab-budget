FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY web_app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY web_app/ /app/
RUN chmod +x /app/start.sh && \
    DEBUG=false BUILD_STATIC=true SECRET_KEY=build-only-static-secret \
    DATABASE_URL=sqlite:////tmp/kamei-budget-build.sqlite3 \
    python manage.py collectstatic --noinput

CMD ["/app/start.sh"]
