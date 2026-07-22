FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATABASE_URL=sqlite:////tmp/kamei-budget.sqlite3

WORKDIR /app

COPY web_app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY web_app/ /app/
COPY streamlit_app/utils/parse_invoice.py /streamlit_app/utils/parse_invoice.py
RUN chmod +x /app/start.sh && \
    DEBUG=false SECRET_KEY=build-only-static-secret python manage.py collectstatic --noinput

CMD ["/app/start.sh"]
