FROM python:3.12-slim

WORKDIR /app

COPY app.py monitor.py shopee_import.py offer_workflow.py /app/
COPY samples/ /app/samples/

RUN useradd --create-home --uid 10001 radar \
    && mkdir -p /app/data \
    && chown radar:radar /app/data \
    && chmod 644 /app/*.py \
    && chmod -R a+rX /app/samples

USER radar

CMD ["python", "-u", "app.py", "dry-run"]
