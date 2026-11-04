FROM python:3.12-slim
WORKDIR /app
COPY app.py monitor.py shopee_import.py offer_workflow.py marketplaces.py web_panel.py /app/
COPY samples/ /app/samples/
COPY assets/ /app/assets/
RUN useradd --create-home --uid 10001 radar \
    && mkdir -p /app/data/inbox \
    && chown -R radar:radar /app/data \
    && chmod 644 /app/*.py \
    && chmod -R a+rX /app/samples
USER radar
ENV PYTHONUNBUFFERED=1 PORT=8080 DATA_DIR=/app/data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)" || exit 1
CMD ["python", "-u", "web_panel.py"]
