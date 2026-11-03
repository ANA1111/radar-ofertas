FROM python:3.12-slim

WORKDIR /app

COPY app.py monitor.py /app/
COPY samples/ /app/samples/

RUN useradd --create-home --uid 10001 radar \
    && chmod 644 /app/app.py /app/monitor.py \
    && chmod -R a+rX /app/samples

USER radar

CMD ["python", "-u", "app.py", "dry-run"]
